"""Runs a LoginProxy on its own TCP port in a private event-loop thread; the port is bound only while it lives."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable

from .base import AuthRequired
from .proxy import LoginProxy

log = logging.getLogger(__name__)

#: Seconds the listener stays up after capture so the browser receives the final page.
GRACE_AFTER_CAPTURE = 2.0


class LoginServer:
    def __init__(
        self,
        proxy: LoginProxy,
        port: int,
        bind_host: str = "0.0.0.0",
        on_finished: Callable[[bool], None] | None = None,
        grace: float = GRACE_AFTER_CAPTURE,
    ) -> None:
        self.proxy = proxy
        self.port = port
        self.bind_host = bind_host
        self.on_finished = on_finished
        self.grace = grace
        self.bound_port: int | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._running = threading.Event()

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self, timeout: float = 10) -> None:
        """Bind the port. Raises AuthRequired when it cannot be bound."""
        self._thread = threading.Thread(target=self._run, name="login-proxy", daemon=True)
        self._running.set()
        self._thread.start()
        if not self._ready.wait(timeout) or self._error is not None:
            self.stop()
            raise AuthRequired(f"Cannot open login port {self.port} (already in use?)")

    def stop(self, join: bool = True) -> None:
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:  # loop already closed
                pass
        if join and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=15)

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.warning("Login proxy thread failed")
        finally:
            self._running.clear()
            self._ready.set()
            if self.on_finished:
                try:
                    self.on_finished(self.proxy.captured.is_set())
                except Exception:
                    log.exception("login finished hook failed")

    async def _main(self) -> None:
        from aiohttp import web

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        runner = web.AppRunner(self.proxy.create_app(), access_log=None)
        await runner.setup()
        try:
            try:
                site = web.TCPSite(runner, host=self.bind_host, port=self.port)
                await site.start()
                socks = getattr(site._server, "sockets", None) or []
                self.bound_port = socks[0].getsockname()[1] if socks else self.port
            except OSError as exc:
                self._error = exc
                return
            self._ready.set()
            captured = asyncio.ensure_future(self.proxy.captured.wait())
            stopped = asyncio.ensure_future(self._stop.wait())
            remaining = max(0.0, self.proxy.deadline - time.monotonic())
            try:
                done, _ = await asyncio.wait(
                    {captured, stopped}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                if captured in done and stopped not in done:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.grace)
                    except TimeoutError:
                        pass
            finally:
                captured.cancel()
                stopped.cancel()
        finally:
            await runner.cleanup()
            await self.proxy.aclose()
