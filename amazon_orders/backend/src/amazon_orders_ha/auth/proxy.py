"""Human-operated authcaptureproxy adapter (async, aiohttp). No network until a browser request.

``LoginProxy`` owns one login attempt: a random capability path, Host/Origin checks, a deadline. It knows nothing
about storage: results are handed to callbacks. ``server.LoginServer`` runs it on its own port.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .base import CookieStore
from .cookies import cookiejar_records
from .urls import checked_https, split_host, upstream_url


def amazon_error_summary(response: Any) -> str:
    """Amazon's error code/message from an api.amazon.com answer (they carry no secrets), else the content type."""
    try:
        body = response.json()
        err = (body.get("response") or {}).get("error") or body.get("error") or {}
        if isinstance(err, dict) and err:
            parts = [str(err.get(k))[:160] for k in ("code", "message", "index") if err.get(k) is not None]
            return " | ".join(parts)
        return "keys: " + ",".join(sorted(body))[:160]
    except Exception:
        return "non-JSON answer (" + str(response.headers.get("content-type", "?"))[:60] + ")"


def describe_error(exc: BaseException) -> str:
    """Exception summary safe for logs: no query strings (they carry one-time codes), no bodies, no cookies."""
    import re

    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        u = exc.request.url
        return f"{type(exc).__name__}: HTTP {exc.response.status_code} from {u.host}{u.path}"
    if isinstance(exc, httpx.HTTPError):
        try:
            u = exc.request.url
            return f"{type(exc).__name__} contacting {u.host}{u.path}"
        except RuntimeError:
            return type(exc).__name__
    text = re.sub(r"\?\S*", "?…", str(exc))[:200]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__

log = logging.getLogger(__name__)

PATH_PREFIX = "auth/proxy/"


class LoginProxy:
    def __init__(
        self,
        public_base_url: str,
        store: CookieStore,
        *,
        register_device: bool = True,
        transport: Any = None,
        api_transport: Any = None,
        lifetime: float = 900,
        on_device: Callable[[str, str, str], None] | None = None,
        on_cookies: Callable[[list[dict[str, Any]]], None] | None = None,
        on_captured: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        import asyncio

        self.public_base_url = public_base_url.rstrip("/") + "/"
        parts = urlsplit(self.public_base_url)
        if parts.scheme not in ("https", "http") or not parts.netloc or parts.query or parts.fragment:
            raise ValueError("Invalid public base URL")
        self.store = store
        self.domain = store.domain
        self.register_device = register_device
        self.transport = transport
        self.api_transport = api_transport
        self.lifetime = lifetime
        self.on_device = on_device
        self.on_cookies = on_cookies
        self.on_captured = on_captured
        self.proxy: Any = None
        self.device: Any = None
        self.captured = asyncio.Event()
        self.url = self.public_base_url + PATH_PREFIX + secrets.token_urlsafe(32) + "/"
        self.deadline = time.monotonic() + lifetime
        self._lock = asyncio.Lock()
        self._active = True
        self._finishing = False
        self._phase = "start"

    @property
    def active(self) -> bool:
        return self._active and not self._finishing and time.monotonic() < self.deadline

    async def _make_proxy(self) -> None:
        import httpx
        from authcaptureproxy import AuthCaptureProxy
        from authcaptureproxy.examples.amazon_waf import AmazonWAFInterceptor
        from yarl import URL

        # Upstream DEBUG output includes passwords, headers and response bodies.
        # Library consumers must not override this logger level during login.
        for name in ("authcaptureproxy", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL + 1)
        site = "amazon.com" if self.register_device else self.domain
        inner = self.transport or httpx.AsyncHTTPTransport(retries=0)

        class RestrictedTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                checked_https(str(request.url), site, waf=True)
                # Do not replay a credential-bearing 307/308 across origins.
                origin = request.extensions.setdefault("auth_origin", request.url.host)
                if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.host != origin:
                    raise ValueError("Refusing cross-host form replay")
                return await inner.handle_async_request(request)

            async def aclose(self):
                await inner.aclose()

        base = self.url

        class HumanProxy(AuthCaptureProxy):
            async def modify_headers(self, target, request):
                # Allowlist: never forward HA cookies, Supervisor/Authorization,
                # X-Ingress-*, CF-* or forwarded client identity headers.
                headers = {
                    k: v
                    for k, v in request.headers.items()
                    if k.lower()
                    in {
                        "user-agent",
                        "accept",
                        "accept-language",
                        "content-type",
                        "x-requested-with",
                        "amz-aamation-resp",
                    }
                    or k.lower().startswith("x-amz-")
                }
                if request.headers.get("Origin"):
                    headers["Origin"] = "https://www." + site
                if request.headers.get("Referer"):
                    try:
                        ref = urlsplit(request.headers["Referer"])
                        headers["Referer"] = upstream_url(ref.path + ("?" + ref.query if ref.query else ""), base, site)
                    except ValueError:
                        pass
                return headers

        client = httpx.AsyncClient(
            transport=RestrictedTransport(), trust_env=False, timeout=httpx.Timeout(60, connect=30), max_redirects=8
        )
        session = self.store.new_session()
        try:
            constants = session.config.constants
            target = str(URL(constants.SIGN_IN_URL).with_query(constants.SIGN_IN_QUERY_PARAMS))
        finally:
            session.session.close()
        if self.register_device:
            from .device import DeviceFlow

            self.device = DeviceFlow()
            target = self.device.signin_url
            for name, value in self.device.app_cookies().items():
                client.cookies.set(name, value, domain=".amazon.com", path="/")
        self.proxy = HumanProxy(URL(self.url), URL(target), session=client)
        self.proxy.interceptors = [AmazonWAFInterceptor()]
        self.proxy.tests = {"capture": self._capture}

    async def _capture(self, response, data, query):
        if not self.active:
            return None
        if self.register_device:
            values = parse_qs(urlsplit(str(response.url)).query)
            code = values.get("openid.oa2.authorization_code", [None])[0]
            if code is None or urlsplit(str(response.url)).path != "/ap/maplanding":
                return None
            await self._register(code)
        else:
            records = cookiejar_records(self.proxy.session.cookies.jar, self.domain)
            # x-acbit is amazon-auth 1.1.0's authenticated marker for amazon.it.
            if not any(c["name"] == "x-acbit" for c in records):
                return None
            if self.on_cookies:
                self.on_cookies(records)
        self._finishing = True
        ok = True
        if self.on_captured:
            self._phase = "activating session"
            try:
                ok = await self.on_captured()
            except Exception as exc:
                log.warning("Signed in, but the session could not be activated: %s", describe_error(exc))
                ok = False
        self.captured.set()
        if ok:
            return "<h1>Signed in</h1><p>You can close this tab and return to Home Assistant.</p>"
        return (
            "<h1>Signed in, but the session could not be activated</h1>"
            "<p>Return to Home Assistant and check the status.</p>"
        )

    async def _register(self, code: str) -> None:
        import httpx

        from .device import API_BASE

        # Explicit device-registration mode and a completed human login are both prerequisites.
        async with httpx.AsyncClient(
            transport=self.api_transport, trust_env=False, timeout=30, follow_redirects=False
        ) as client:
            self._phase = "device registration"
            response = await client.post(API_BASE + "/auth/register", json=self.device.registration_body(code))
            if response.status_code != 200:
                log.warning("Amazon refused the device registration: HTTP %s %s",
                            response.status_code, amazon_error_summary(response))
            response.raise_for_status()
            token = response.json()["response"]["success"]["tokens"]["bearer"]["refresh_token"]
        self._phase = "saving device token"
        # Save immediately: if the later cookie exchange fails, the registered device must stay identifiable.
        if self.on_device:
            self.on_device(token, self.device.serial, self.domain)
        self.device = None

    async def handle(self, request):
        from aiohttp import web

        if not self.active:
            return web.Response(status=410, text="Login expired or completed. Start again.")
        # A random path is a short-lived bearer capability, not a public proxy.
        expected = urlsplit(self.public_base_url)
        try:
            host = split_host(request.host)[0]
        except ValueError:
            return web.Response(status=403, text="Unexpected Host")
        if host != expected.hostname:
            return web.Response(status=403, text="Unexpected Host")
        origin = request.headers.get("Origin")
        # Browsers send "Origin: null" on same-origin form POSTs when the page's
        # referrer policy is no-referrer (Amazon's pages may set one). Accept it
        # only when Fetch Metadata confirms the request comes from this origin.
        same_site = request.headers.get("Sec-Fetch-Site") in ("same-origin", "none")
        if origin is not None and origin != f"{expected.scheme}://{expected.netloc}" and not (
            origin == "null" and same_site
        ):
            return web.Response(status=403, text="Unexpected Origin")
        if request.method not in ("GET", "POST", "HEAD", "OPTIONS"):
            return web.Response(status=405)
        site = "amazon.com" if self.register_device else self.domain
        try:
            target = upstream_url(request.raw_path, self.url, site)
            parts = urlsplit(target)
            if parts.hostname == "www." + site and not (
                parts.path == "/" or parts.path.startswith(("/ap/", "/ax/", "/aaut/", "/cvf/", "/errors/"))
            ):
                raise ValueError("Not a sign-in path")
        except ValueError:
            return web.Response(status=403, text="Destination not allowed")
        async with self._lock:
            if not self.active:
                return web.Response(status=410, text="Login completed")
            if self.proxy is None:
                await self._make_proxy()
            self._phase = "relay " + request.method + " " + urlsplit(str(request.rel_url)).path.rsplit("/", 1)[-1][:40]
            try:
                response = await self.proxy.all_handler(request)
                # Even the upstream AJAX header-preservation branch must not set
                # Amazon cookies on the Home Assistant/browser origin.
                for name in (
                    "Set-Cookie",
                    "Location",
                    "Content-Security-Policy",
                    "Content-Security-Policy-Report-Only",
                ):
                    response.headers.popall(name, None)
                response.headers["Cache-Control"] = "no-store"
                response.headers["Referrer-Policy"] = "same-origin"
                return response
            except Exception as exc:
                log.warning("Login relay failed (step: %s): %s", self._phase, describe_error(exc))
                log.debug("Login relay failure details", exc_info=True)
                return web.Response(
                    status=502,
                    text="Login relay failed. Do not retry repeatedly.",
                    headers={"Cache-Control": "no-store"},
                )
            finally:
                self.proxy.data.clear()
                self.proxy.query.clear()
                self.proxy.init_query.clear()
                self.proxy.last_resp = None
                if self._finishing and self.proxy is not None:
                    self.proxy.session.cookies.clear()

    def create_app(self):
        from aiohttp import web

        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        return app

    async def aclose(self) -> None:
        self._active = False
        self.device = None
        if self.proxy is not None:
            self.proxy.session.cookies.clear()
            self.proxy.data.clear()
            self.proxy.query.clear()
            self.proxy.last_resp = None
            await self.proxy.session.aclose()
            self.proxy = None
