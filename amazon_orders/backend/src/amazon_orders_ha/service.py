"""Runtime wiring: database, auth provider, sync engine, HA integration, background loop."""

from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .auth_provider import AuthProvider, CookieFileAuthProvider, DevAuthProvider
from .config import Settings
from .db import Database
from .ha import HAEvents, HAIntegration, MqttPublisher
from .sync import SyncEngine

log = logging.getLogger(__name__)


def make_auth_provider(settings: Settings) -> AuthProvider:
    """Use the ``auth`` subpackage when it provides ``create_auth_provider``; else the cookie file."""
    if os.environ.get("AMAZON_ORDERS_DEV_AUTH") == "1":
        return DevAuthProvider()
    try:
        mod = importlib.import_module("amazon_orders_ha.auth")
        factory = getattr(mod, "create_auth_provider", None)
        if factory:
            return factory(settings)
    except ImportError:
        pass
    return CookieFileAuthProvider(settings.data_dir, settings.options.domain)


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

    def __init__(self, rt: Runtime):
        self.rt = rt
        self.thread: threading.Thread | None = None
        self.wake = threading.Event()
        self._last_hourly = 0.0

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="sync-runner", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.rt.engine.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=10)
        self.rt.integration.mqtt.close()

    def _loop(self) -> None:
        import time

        eng = self.rt.engine
        while not eng.stop.is_set():
            try:
                eng.tick()
                if time.monotonic() - self._last_hourly >= self.HOURLY:
                    self._last_hourly = time.monotonic()
                    self.rt.integration.run()
            except Exception:
                log.exception("scheduler tick failed")
            self.wake.wait(self.TICK_SECONDS)
            self.wake.clear()
