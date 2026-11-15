"""Human-operated authcaptureproxy adapter. No network until a browser request."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .base import AuthStatus, CookieAuthProvider
from .cookies import cookiejar_records
from .urls import checked_https, upstream_url


class ProxyAuthProvider(CookieAuthProvider):
    method = "login_proxy"

    def __init__(
        self,
        data_dir: Path,
        public_base_url: str = "http://localhost:8098/",
        domain: str = "amazon.it",
        *,
        register_device: bool = False,
        transport: Any = None,
        lifetime: int = 900,
    ) -> None:
        super().__init__(data_dir, domain)
        self.public_base_url = public_base_url.rstrip("/") + "/"
        parts = urlsplit(self.public_base_url)
        if parts.scheme not in ("https", "http") or not parts.netloc or parts.query or parts.fragment:
            raise ValueError("Invalid public base URL")
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Non-loopback login requires HTTPS")
        self.register_device = register_device
        self.transport = transport
        self.lifetime = lifetime
        self.proxy: Any = None
        self.device: Any = None
        self.captured = asyncio.Event()
        self._deadline = 0.0
        self._url: str | None = None
        self._lock = asyncio.Lock()
        self._in_progress = False

    def start(self) -> str:
        if self._in_progress and time.monotonic() < self._deadline:
            assert self._url is not None
            return self._url
        if self.proxy is not None:
            raise RuntimeError("Close the previous proxy with await aclose() before restarting")
        self._url = self.public_base_url + "auth/proxy/" + secrets.token_urlsafe(32) + "/"
        self._deadline = time.monotonic() + self.lifetime
        self._in_progress = True
        self.captured.clear()
        return self._url

    def status(self) -> AuthStatus:
        status = super().status()
        if self._in_progress and time.monotonic() < self._deadline:
            status["state"] = "in_progress"
        return status

    async def _make_proxy(self) -> None:
        import httpx
        from authcaptureproxy import AuthCaptureProxy
        from authcaptureproxy.examples.amazon_waf import AmazonWAFInterceptor
        from yarl import URL

        # Upstream DEBUG output includes passwords, headers and response bodies.
        # Library consumers must not override this logger level during login.
        logging.getLogger("authcaptureproxy").setLevel(logging.CRITICAL + 1)
        logging.getLogger("httpx").setLevel(logging.CRITICAL + 1)
        logging.getLogger("httpcore").setLevel(logging.CRITICAL + 1)
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

        base = self._url
        assert base is not None

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
        session = self.new_session()
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
        self.proxy = HumanProxy(URL(self._url), URL(target), session=client)
        self.proxy.interceptors = [AmazonWAFInterceptor()]
        self.proxy.tests = {"capture": self._capture}

    async def _capture(self, response, data, query):
        if not self._in_progress or time.monotonic() >= self._deadline:
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
            self.import_cookies(records)
        self._in_progress = False
        self.captured.set()
        return "<h1>Session captured</h1><p>Read-only order verification is running. Close this tab.</p>"

    async def _register(self, code: str) -> None:
        import httpx
        from amazonauth.util import write_private_file

        from .device import exchange_cookie_records, token_form

        # Explicit flag and completed human login are both prerequisites.
        async with httpx.AsyncClient(trust_env=False, timeout=30, follow_redirects=False) as client:
            response = await client.post(
                "https://api.amazon.com/auth/register", json=self.device.registration_body(code)
            )
            response.raise_for_status()
            token = response.json()["response"]["success"]["tokens"]["bearer"]["refresh_token"]
            # Save immediately: if cookie exchange fails the registered device
            # must still be identifiable and revocable by the user.
            write_private_file(
                str(self.data_dir / "device.json"),
                json.dumps(
                    {
                        "refresh_token": token,
                        "device_serial": self.device.serial,
                        "domain": self.domain,
                    }
                ),
            )
            response = await client.post("https://api.amazon.com/auth/token", data=token_form(token))
            response.raise_for_status()
            self.import_cookies(exchange_cookie_records(response.json()))
        self.device = None

    async def handle(self, request):
        from aiohttp import web

        if not self._in_progress or self.captured.is_set() or time.monotonic() >= self._deadline or self._url is None:
            return web.Response(status=410, text="Login expired or completed. Start again.")
        # A random path is a short-lived bearer capability, not a public proxy.
        expected = urlsplit(self.public_base_url)
        if request.host != expected.netloc:
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
            target = upstream_url(request.raw_path, self._url, site)
            parts = urlsplit(target)
            if parts.hostname == "www." + site and not (
                parts.path == "/" or parts.path.startswith(("/ap/", "/ax/", "/aaut/", "/cvf/", "/errors/"))
            ):
                raise ValueError("Not a sign-in path")
        except ValueError:
            return web.Response(status=403, text="Destination not allowed")
        async with self._lock:
            if self.captured.is_set():
                return web.Response(status=410, text="Login completed")
            if self.proxy is None:
                await self._make_proxy()
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
            except Exception:
                return web.Response(
                    status=502,
                    text="Login relay failed. Do not retry repeatedly; use the remote-browser fallback.",
                    headers={"Cache-Control": "no-store"},
                )
            finally:
                self.proxy.data.clear()
                self.proxy.query.clear()
                self.proxy.init_query.clear()
                self.proxy.last_resp = None
                if self.captured.is_set():
                    self.proxy.session.cookies.clear()

    def create_app(self):
        from aiohttp import web

        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        return app

    def logout(self) -> None:
        self._in_progress = False
        self._deadline = 0
        self.device = None
        if self.proxy is not None:
            self.proxy.session.cookies.clear()
            self.proxy.data.clear()
            self.proxy.query.clear()
            self.proxy.last_resp = None
        super().logout()

    async def aclose(self) -> None:
        self._in_progress = False
        self.device = None
        if self.proxy is not None:
            await self.proxy.session.aclose()
            self.proxy = None
