"""Runtime wiring: database, auth provider, sync engine, HA integration, background loop."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .auth import AuthProvider, CookieFileAuthProvider, DevAuthProvider, create_auth_provider
from .config import Settings
from .db import Database
from .ha import HAEvents, HAIntegration, MqttPublisher
from .sync import SyncEngine

log = logging.getLogger(__name__)


def make_auth_provider(settings: Settings) -> AuthProvider:
    """DeviceAuthProvider; ``AMAZON_ORDERS_DEV_AUTH=1`` and ``AMAZON_ORDERS_AUTH=cookie_file`` are dev-only."""
    if os.environ.get("AMAZON_ORDERS_DEV_AUTH") == "1":
        return DevAuthProvider()
    if os.environ.get("AMAZON_ORDERS_AUTH") == "cookie_file":
        return CookieFileAuthProvider(settings.data_dir, settings.options.domain)
    return create_auth_provider(settings)


@dataclass
class Runtime:
    settings: Settings
    db: Database
    auth: AuthProvider
    engine: SyncEngine
    integration: HAIntegration
    now: Callable[[], datetime] = field(default=datetime.now)
    runner: BackgroundRunner | None = None

    def today(self) -> date:
        return self.now().date()


def build_runtime(settings: Settings, auth: AuthProvider | None = None, events: HAEvents | None = None,
                  mqtt: MqttPublisher | None = None, engine_kwargs: dict[str, Any] | None = None) -> Runtime:
    db = Database(settings.db_path)
    auth = auth or make_auth_provider(settings)
    events = events or HAEvents()
    mqtt = mqtt or MqttPublisher(settings.options)
    holder: dict[str, Any] = {}
    engine = SyncEngine(db, settings.options, auth, notify=events.fire,
                        on_synced=lambda: holder["integration"].run(), **(engine_kwargs or {}))
    integration = HAIntegration(db, settings.options, events, mqtt, engine.status)
    holder["integration"] = integration
    return Runtime(settings, db, auth, engine, integration)


class BackgroundRunner:
    """One daemon thread: scheduler ticks plus hourly deadline-event checks."""

    TICK_SECONDS = 30
    HOURLY = 3600
    RENEW_CHECK = 3600  # the provider itself decides whether its cookies are older than 24 h

    def __init__(self, rt: Runtime):
        self.rt = rt
        self.thread: threading.Thread | None = None
        self.wake = threading.Event()
        self._last_hourly = 0.0
        self._last_renew = -1e9

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="sync-runner", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.rt.engine.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=10)
        self.rt.integration.mqtt.close()
        close = getattr(self.rt.auth, "close", None)
        if close:
            close()

    def _loop(self) -> None:
        import time

        eng = self.rt.engine
        while not eng.stop.is_set():
            try:
                self._renew_cookies()
                eng.tick()
                if time.monotonic() - self._last_hourly >= self.HOURLY:
                    self._last_hourly = time.monotonic()
                    self.rt.integration.run()
            except Exception:
                log.exception("scheduler tick failed")
            self.wake.wait(self.TICK_SECONDS)
            self.wake.clear()

    def _renew_cookies(self) -> None:
        """Proactive cookie renewal (device auth): cheap local check hourly, Amazon call only when due."""
        import time

        renew = getattr(self.rt.auth, "renew_if_due", None)
        if renew is None or time.monotonic() - self._last_renew < self.RENEW_CHECK:
            return
        self._last_renew = time.monotonic()
        try:
            renew()
        except Exception:
            log.exception("proactive cookie renewal failed")
