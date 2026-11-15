"""Production provider: device registered through the login proxy, cookies renewed from the refresh token."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from .base import AUTH_COOKIE, AuthRequired, AuthStatus, AuthTemporarilyUnavailable, CookieStore
from .device import TokenRejected, TokenTransient, deregister_device, exchange_refresh_token
from .proxy import LoginProxy
from .server import LoginServer
from .urls import format_netloc, is_lan_host, split_host

if TYPE_CHECKING:
    from amazonorders.session import AmazonSession

log = logging.getLogger(__name__)

RENEW_MARGIN = 600  # seconds: renew when the auth cookie expires within this window
RENEW_MAX_AGE = 24 * 3600  # proactive renewal job: refresh cookies at least this often
TRANSIENT_BACKOFF = 900  # seconds without renewal attempts after a network/5xx failure


class DeviceAuthProvider:
    """Sign in once through the login proxy (device registration), then renew cookies without the user.

    Files, all in ``<data>/auth/`` (dir 0700, files 0600): ``device.json`` (refresh token, device serial, domain)
    and ``cookies.<domain>.json`` (the amazon-orders jar). ``get_session`` performs no Amazon request unless the
    cookies are missing/expired, in which case it makes exactly one renewal attempt, then raises ``AuthRequired``.
    """

    def __init__(
        self,
        data_dir: Path,
        domain: str = "amazon.it",
        *,
        login_port: int = 8098,
        login_host: str = "",
        lifetime: float = 900,
        bind_host: str = "0.0.0.0",
        register_device: bool = True,
        login_transport: Any = None,
        api_transport: Any = None,
        clock=time.time,
        renew_max_age: float = RENEW_MAX_AGE,
        transient_backoff: float = TRANSIENT_BACKOFF,
        grace: float = 2.0,
    ) -> None:
        self.domain = domain
        self.store = CookieStore(Path(data_dir) / "auth", domain)
        self.device_path = self.store.directory / "device.json"
        self.login_port = int(login_port)
        self.login_host = (login_host or "").strip()
        if self.login_host:
            split_host(self.login_host)  # fail early on a malformed override
        self.lifetime = lifetime
        self.bind_host = bind_host
        self.register_device = register_device
        self.login_transport = login_transport
        self.api_transport = api_transport
        self.clock = clock
        self.renew_max_age = renew_max_age
        self.transient_backoff = transient_backoff
        self.grace = grace
        self.last_logout_remote: bool | None = None
        self._io = threading.RLock()  # session cache + renewals (may hold Amazon requests)
        self._state = threading.Lock()  # tiny critical sections, never held across I/O
        self._session: AmazonSession | None = None
        self._server: LoginServer | None = None
        self._url: str | None = None
        self._login_completed = False
        self._rejected = False
        self._retry_after = 0.0

    # ------------------------------------------------------------------ local files

    def _device(self) -> dict[str, str] | None:
        try:
            data = json.loads(self.device_path.read_text())
        except (OSError, ValueError):
            return None
        token = data.get("refresh_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            return None
        return {"refresh_token": token, "device_serial": str(data.get("device_serial", "")),
                "domain": str(data.get("domain") or self.domain)}

    def _save_device(self, token: str, serial: str, domain: str) -> None:
        from amazonauth.util import write_private_file

        write_private_file(
            str(self.device_path), json.dumps({"refresh_token": token, "device_serial": serial, "domain": domain})
        )

    def _jar_records(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.store.cookie_path.read_text())
        except (OSError, ValueError):
            return []
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    def _auth_cookie_expiry(self, records: list[dict[str, Any]]) -> tuple[bool, float | None]:
        """(present, earliest expiry epoch or None for a session cookie)."""
        found = [c for c in records if c.get("name") == AUTH_COOKIE]
        if not found:
            return False, None
        exp = [c["expires"] for c in found if isinstance(c.get("expires"), int | float) and c["expires"] > 0]
        return True, (min(exp) if exp and len(exp) == len(found) else None)

    def _cookies_usable(self, records: list[dict[str, Any]]) -> bool:
        present, exp = self._auth_cookie_expiry(records)
        return present and (exp is None or exp > self.clock() + RENEW_MARGIN)

    def _drop_session(self) -> None:
        if self._session is not None:
            try:
                self._session.session.close()
            except Exception:
                pass
        self._session = None

    # ------------------------------------------------------------------ status

    def status(self) -> AuthStatus:
        present, exp = self._auth_cookie_expiry(self._jar_records())
        has_device = self._device() is not None
        usable = self._cookies_usable(self._jar_records())
        method = "device" if has_device else ("cookies" if present else None)
        if has_device:
            state = "auth_required" if self._rejected else "ok"
        else:
            state = "ok" if usable else "auth_required"
        hint = datetime.fromtimestamp(exp, UTC).date().isoformat() if exp else None
        result: AuthStatus = {"state": state, "method": method, "expires_hint": hint}
        server, url = self._server, self._url
        # After capture the port stays open for a short grace period; the login is done.
        if server is not None and server.running and url and not server.proxy.captured.is_set():
            result["state"] = "in_progress"
            result["login_url"] = url
        return result

    def pop_login_completed(self) -> bool:
        with self._state:
            done, self._login_completed = self._login_completed, False
        return done

    # ------------------------------------------------------------------ renewal

    def _http(self) -> httpx.Client:
        return httpx.Client(transport=self.api_transport, trust_env=False, timeout=30, follow_redirects=False)

    def _renew(self) -> None:
        """One exchange of the refresh token for cookies; stores them (in place on the live session)."""
        with self._io:
            device = self._device()
            if device is None:
                raise AuthRequired("no registered device; sign in")
            if self._rejected:
                raise AuthRequired("Amazon no longer accepts the registered device; sign in again")
            if self.clock() < self._retry_after:
                raise AuthTemporarilyUnavailable("cookie renewal postponed after a network error")
            try:
                with self._http() as client:
                    records = exchange_refresh_token(client, device["refresh_token"], self.domain)
            except TokenRejected as exc:
                self._rejected = True
                self._drop_session()
                log.warning("Refresh token rejected by Amazon (%s)", exc)
                raise AuthRequired("Amazon no longer accepts the registered device; sign in again") from None
            except TokenTransient as exc:
                self._retry_after = self.clock() + self.transient_backoff
                log.warning("Cookie renewal failed temporarily (%s)", exc)
                raise AuthTemporarilyUnavailable("cookie renewal failed; will retry later") from None
            self._retry_after = 0.0
            self.store.import_cookies(records, session=self._session)
            log.info("Amazon cookies renewed from the device refresh token")

    def renew_session(self) -> bool:
        """Amazon rejected the cookies we are using: renew once, in place. False when that is not possible."""
        with self._io:
            try:
                self._renew()
            except (AuthRequired, AuthTemporarilyUnavailable):
                return False
            return True

    def renew_if_due(self) -> bool:
        """Proactive job (hourly check): renew when the jar is older than ``renew_max_age`` or unusable."""
        with self._io:
            if self._device() is None or self._rejected:
                return False
            try:
                age = self.clock() - os.path.getmtime(self.store.cookie_path)
            except OSError:
                age = float("inf")
            if age < self.renew_max_age and self._cookies_usable(self._jar_records()):
                return False
            try:
                self._renew()
            except (AuthRequired, AuthTemporarilyUnavailable):
                return False
            return True

    # ------------------------------------------------------------------ session

    def get_session(self) -> AmazonSession:
        with self._io:
            records = self._jar_records()
            if not self._cookies_usable(records):
                if self._device() is None:
                    raise AuthRequired("no stored Amazon session" if not records else "stored session expired")
                self._renew()  # AuthRequired / AuthTemporarilyUnavailable propagate: exactly one attempt
            elif self._rejected:
                raise AuthRequired("Amazon no longer accepts the registered device; sign in again")
            if self._session is None:
                self._session = self.store.new_session()
            if not self._session.auth_cookies_stored():
                self._drop_session()
                raise AuthRequired("stored session has no authentication cookies")
            self._session.is_authenticated = True
            return self._session

    # ------------------------------------------------------------------ interactive sign-in

    def _public_base(self, host: str | None) -> str:
        if self.login_host:
            name, port = split_host(self.login_host)
            return f"http://{format_netloc(name, port or self.login_port)}/"
        if not host:
            raise AuthRequired("Cannot tell which host to use for the login link; set the login_host option")
        try:
            name, _ = split_host(host)
        except ValueError:
            raise AuthRequired("Cannot tell which host to use for the login link; set the login_host option") from None
        if not is_lan_host(name):
            raise AuthRequired(
                "Sign-in is served over plain HTTP and only from the local network. Open Home Assistant from the "
                "LAN (or through your VPN), or set the login_host option."
            )
        return f"http://{format_netloc(name, self.login_port)}/"

    def start(self, host: str | None = None) -> str:
        """Open the login port and return the URL to visit. Idempotent while a login is running."""
        with self._state:
            server, url = self._server, self._url
            if server is not None and server.running and url:
                return url
            base = self._public_base(host)
            proxy = LoginProxy(
                base,
                self.store,
                register_device=self.register_device,
                transport=self.login_transport,
                api_transport=self.api_transport,
                lifetime=self.lifetime,
                on_device=self._save_device,
                on_cookies=self.store.import_cookies,
                on_captured=self._on_captured,
            )
            server = LoginServer(
                proxy, self.login_port, self.bind_host, on_finished=self._on_finished, grace=self.grace
            )
            server.start()  # AuthRequired when the port cannot be bound
            self._server, self._url = server, proxy.url
            return proxy.url

    async def _on_captured(self) -> bool:
        return await asyncio.to_thread(self._finish_login)

    def _finish_login(self) -> bool:
        with self._io:
            try:
                self._rejected = False
                self._retry_after = 0.0
                if self.register_device:
                    self._renew()
                self._drop_session()
                self.get_session()
            except (AuthRequired, AuthTemporarilyUnavailable):
                return False
            with self._state:
                self._login_completed = True
            return True

    def _on_finished(self, captured: bool) -> None:
        log.info("Login port closed (%s)", "completed" if captured else "timeout or cancelled")

    def close(self) -> None:
        """Stop a running login and release the port (add-on shutdown)."""
        server = self._server
        if server is not None:
            server.stop()
        with self._io:
            self._drop_session()

    # ------------------------------------------------------------------ logout

    def logout(self) -> None:
        """Close the login port, deregister the device at Amazon (best effort), delete local auth data."""
        server = self._server
        if server is not None:
            server.stop()  # before taking _io: a login in flight needs it to finish
        with self._io:
            device = self._device()
            remote: bool | None = None
            if device is not None:
                with self._http() as client:
                    remote = deregister_device(client, device["refresh_token"], device["domain"])
                if not remote:
                    log.warning("Could not deregister the device at Amazon; remove it in your account's device list")
            self._drop_session()
            self.device_path.unlink(missing_ok=True)
            self.store.clear()
            for leftover in self.store.directory.glob(".*.tmp"):
                leftover.unlink(missing_ok=True)
            self._rejected = False
            self._retry_after = 0.0
            self.last_logout_remote = remote
            with self._state:
                self._login_completed = False
                self._url = None


def create_auth_provider(settings: Any) -> DeviceAuthProvider:
    """Factory used by ``service.make_auth_provider``."""
    opts = settings.options
    return DeviceAuthProvider(
        settings.data_dir,
        opts.domain,
        login_port=opts.login_port,
        login_host=opts.login_host,
    )
