"""DeviceAuthProvider: renewal, status, logout/deregistration, port lifecycle. Synthetic data, no network."""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from amazon_orders_ha.auth import AuthRequired, AuthTemporarilyUnavailable, DeviceAuthProvider

NOW = 1_800_000_000.0  # fixed epoch for the injected clock
DAY = 86400


def cookie_payload(value: str = "fresh", expires: int | None = None, domain: str = ".amazon.it") -> dict:
    expires = expires if expires is not None else int(NOW + 7 * DAY)
    cookies = [
        {"Name": "x-acbit", "Value": f'"{value}"', "Path": "/", "Secure": True, "Expires": expires},
        {"Name": "session-id", "Value": "sid", "Path": "/", "Secure": True, "Expires": expires},
    ]
    return {"response": {"tokens": {"cookies": {domain: cookies, ".amazon.com": [{"Name": "x", "Value": "y"}]}}}}


class FakeAmazon:
    """httpx.MockTransport handler recording requests; ``token`` decides the /auth/token answer."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.token: Callable[[httpx.Request], httpx.Response] = lambda r: httpx.Response(200, json=cookie_payload())
        self.deregister_status = 200

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/auth/token":
            form = parse_qs(request.content.decode())
            if form["requested_token_type"] == ["access_token"]:
                return httpx.Response(200, json={"access_token": "synthetic-access"})
            return self.token(request)
        if path == "/auth/deregister":
            return httpx.Response(self.deregister_status, json={})
        if path == "/auth/register":
            return httpx.Response(
                200, json={"response": {"success": {"tokens": {"bearer": {"refresh_token": "synthetic-refresh"}}}}}
            )
        return httpx.Response(404)


class Clock:
    def __init__(self, t: float = NOW) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def amazon() -> FakeAmazon:
    return FakeAmazon()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def make_provider(tmp_path: Path, amazon: FakeAmazon, clock: Clock):
    made: list[DeviceAuthProvider] = []

    def factory(**kw) -> DeviceAuthProvider:
        kw.setdefault("api_transport", amazon.transport)
        kw.setdefault("clock", clock)
        p = DeviceAuthProvider(tmp_path, "amazon.it", bind_host="127.0.0.1", **kw)
        made.append(p)
        return p

    yield factory
    for p in made:
        p.close()


def register(p: DeviceAuthProvider, token: str = "synthetic-refresh") -> None:
    p._save_device(token, "SERIAL123", "amazon.it")


def jar(p: DeviceAuthProvider, value: str, expires: int | None) -> None:
    p.store.import_cookies([{"name": "x-acbit", "value": value, "domain": ".amazon.it", "path": "/",
                             "secure": True, "expires": expires}])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(cond: Callable[[], bool], timeout: float = 8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# ------------------------------------------------------------------ storage

def test_device_file_is_private(make_provider):
    p = make_provider()
    register(p)
    assert p.device_path.stat().st_mode & 0o777 == 0o600
    assert p.store.directory.stat().st_mode & 0o777 == 0o700
    assert json.loads(p.device_path.read_text()) == {
        "refresh_token": "synthetic-refresh", "device_serial": "SERIAL123", "domain": "amazon.it"}


def test_cookie_jar_written_by_renewal_is_private(make_provider):
    p = make_provider()
    register(p)
    p.get_session()
    assert p.store.cookie_path.stat().st_mode & 0o777 == 0o600
    assert p.store.cookie_path.parent == p.device_path.parent


# ------------------------------------------------------------------ status transitions

def test_status_transitions(make_provider, amazon, clock):
    p = make_provider()
    assert p.status() == {"state": "auth_required", "method": None, "expires_hint": None}
    with pytest.raises(AuthRequired):
        p.get_session()
    assert amazon.calls == []  # nothing to renew from, no request
    register(p)
    assert p.status()["state"] == "ok" and p.status()["method"] == "device"
    p.get_session()
    st = p.status()
    assert st["state"] == "ok" and st["method"] == "device" and st["expires_hint"] == "2027-01-22"
    assert "login_url" not in st
    amazon.token = lambda r: httpx.Response(400, json={})
    clock.t += 30 * DAY  # jar expired -> renewal -> Amazon rejects the token
    with pytest.raises(AuthRequired):
        p.get_session()
    assert p.status()["state"] == "auth_required" and p.status()["method"] == "device"
    p.logout()
    assert p.status() == {"state": "auth_required", "method": None, "expires_hint": None}


def test_cookies_only_session_reports_method_cookies(make_provider, amazon):
    p = make_provider()
    jar(p, "browser", int(NOW + DAY))
    assert p.status()["state"] == "ok" and p.status()["method"] == "cookies"
    assert p.get_session().is_authenticated
    assert amazon.calls == []


# ------------------------------------------------------------------ renewal

def test_get_session_renews_expired_cookies_from_refresh_token(make_provider, amazon, clock):
    p = make_provider()
    register(p)
    jar(p, "stale", int(NOW - 3600))
    session = p.get_session()
    assert len(amazon.calls) == 1
    req = amazon.calls[0]
    assert str(req.url) == "https://api.amazon.com/auth/token"
    form = parse_qs(req.content.decode())
    assert form["source_token"] == ["synthetic-refresh"] and form["source_token_type"] == ["refresh_token"]
    assert form["requested_token_type"] == ["auth_cookies"] and form["domain"] == ["www.amazon.it"]
    values = {c.name: c.value for c in session.session.cookies}
    assert values["x-acbit"] == "fresh"
    assert session.is_authenticated and session.config.site == "amazon.it"
    assert p.get_session() is session and len(amazon.calls) == 1  # valid: no request, same object


def test_cookies_close_to_expiry_are_renewed(make_provider, amazon):
    p = make_provider()
    register(p)
    jar(p, "old", int(NOW + 60))  # inside the renewal margin
    p.get_session()
    assert len(amazon.calls) == 1


def test_missing_cookies_with_device_renew(make_provider, amazon):
    p = make_provider()
    register(p)
    assert p.get_session().is_authenticated
    assert len(amazon.calls) == 1


def test_rejected_token_gets_exactly_one_attempt_then_auth_required(make_provider, amazon):
    amazon.token = lambda r: httpx.Response(401, json={"error": "invalid_grant"})
    p = make_provider()
    register(p)
    with pytest.raises(AuthRequired):
        p.get_session()
    with pytest.raises(AuthRequired):
        p.get_session()
    assert p.renew_session() is False
    assert len(amazon.calls) == 1
    assert p.status()["state"] == "auth_required"


def test_new_login_clears_rejection(make_provider, amazon):
    amazon.token = lambda r: httpx.Response(400, json={})
    p = make_provider()
    register(p)
    with pytest.raises(AuthRequired):
        p.get_session()
    amazon.token = lambda r: httpx.Response(200, json=cookie_payload())
    assert p._finish_login() is True  # what a completed sign-in runs
    assert p.get_session().is_authenticated and p.pop_login_completed() is True
    assert p.pop_login_completed() is False


def test_transient_failure_is_not_auth_required_and_backs_off(make_provider, amazon, clock):
    amazon.token = lambda r: httpx.Response(503)
    p = make_provider()
    register(p)
    with pytest.raises(AuthTemporarilyUnavailable):
        p.get_session()
    with pytest.raises(AuthTemporarilyUnavailable):
        p.get_session()
    assert len(amazon.calls) == 1 and p.status()["state"] == "ok"
    amazon.token = lambda r: httpx.Response(200, json=cookie_payload())
    clock.t += 901
    assert p.get_session().is_authenticated and len(amazon.calls) == 2


def test_network_error_is_transient(make_provider, amazon):
    def boom(r):
        raise httpx.ConnectError("down")

    amazon.token = boom
    p = make_provider()
    register(p)
    with pytest.raises(AuthTemporarilyUnavailable):
        p.get_session()


def test_renew_session_updates_live_session_in_place(make_provider, amazon):
    p = make_provider()
    register(p)
    session = p.get_session()
    amazon.token = lambda r: httpx.Response(200, json=cookie_payload("second"))
    assert p.renew_session() is True
    assert p.get_session() is session
    assert {c.name: c.value for c in session.session.cookies}["x-acbit"] == "second"
    assert "second" in p.store.cookie_path.read_text()


def test_proactive_renewal_only_when_jar_is_a_day_old(make_provider, amazon, clock):
    p = make_provider()
    assert p.renew_if_due() is False  # no device
    register(p)
    p.get_session()
    n = len(amazon.calls)
    os.utime(p.store.cookie_path, (clock.t, clock.t))  # file mtimes are real time; align with the fake clock
    clock.t += 23 * 3600
    assert p.renew_if_due() is False and len(amazon.calls) == n
    os.utime(p.store.cookie_path, (clock.t - 25 * 3600, clock.t - 25 * 3600))
    amazon.token = lambda r: httpx.Response(200, json=cookie_payload("daily", int(clock.t + 7 * DAY)))
    assert p.renew_if_due() is True and len(amazon.calls) == n + 1


# ------------------------------------------------------------------ logout

def test_logout_deregisters_device_and_deletes_local_data(make_provider, amazon):
    p = make_provider()
    register(p)
    p.get_session()
    p.logout()
    paths = [str(c.url) for c in amazon.calls]
    assert paths[-2:] == ["https://api.amazon.com/auth/token", "https://api.amazon.com/auth/deregister"]
    dereg = amazon.calls[-1]
    assert dereg.headers["authorization"] == "Bearer synthetic-access"
    assert json.loads(dereg.content) == {"requested_deregister_type": "deregister_device"}
    assert p.last_logout_remote is True
    assert not p.device_path.exists() and not p.store.cookie_path.exists()
    with pytest.raises(AuthRequired):
        p.get_session()


def test_logout_is_best_effort_when_deregistration_fails(make_provider, amazon):
    amazon.deregister_status = 500
    p = make_provider()
    register(p)
    p.get_session()
    p.logout()
    assert p.last_logout_remote is False
    assert not p.device_path.exists() and not p.store.cookie_path.exists()


def test_logout_without_device_makes_no_request(make_provider, amazon):
    p = make_provider()
    jar(p, "browser", None)
    p.logout()
    assert amazon.calls == [] and p.last_logout_remote is None and not p.store.cookie_path.exists()


# ------------------------------------------------------------------ URL host derivation

@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("homeassistant.local:8123", "http://homeassistant.local:8098/"),
        ("homeassistant.local", "http://homeassistant.local:8098/"),
        ("192.168.1.20:8123", "http://192.168.1.20:8098/"),
        ("[fd00::5]:8123", "http://[fd00::5]:8098/"),
        ("HomeAssistant:8123, proxy.example.org", "http://homeassistant:8098/"),
        ("localhost:8099", "http://localhost:8098/"),
    ],
)
def test_public_base_uses_browser_host_without_its_port(make_provider, host, expected):
    assert make_provider(login_port=8098)._public_base(host) == expected


@pytest.mark.parametrize(
    "host", [None, "", "ha.example.org", "8.8.8.8:8123", "bad host", "a/b", "x@y", "ex%61mple.lan"]
)
def test_public_or_malformed_hosts_are_refused(make_provider, host):
    with pytest.raises(AuthRequired):
        make_provider()._public_base(host)


def test_login_host_option_overrides_header_and_may_carry_port(make_provider):
    p = make_provider(login_host="ha.example.org", login_port=8098)
    assert p._public_base("192.168.1.20:8123") == "http://ha.example.org:8098/"
    p = make_provider(login_host="10.0.0.2:18098", login_port=8098)
    assert p._public_base(None) == "http://10.0.0.2:18098/"
    with pytest.raises(ValueError):
        make_provider(login_host="http://evil/")


# ------------------------------------------------------------------ login port lifecycle

def test_port_is_bound_only_while_login_runs(make_provider):
    port = free_port()
    p = make_provider(login_port=port)
    assert not port_open(port)
    url = p.start(host="localhost:8123")
    assert urlsplit(url).netloc == f"localhost:{port}" and urlsplit(url).path.startswith("/auth/proxy/")
    assert port_open(port)
    st = p.status()
    assert st["state"] == "in_progress" and st["login_url"] == url
    assert p.start(host="other.local") == url  # idempotent while running
    p.logout()
    assert wait_for(lambda: not port_open(port))
    assert p.status()["state"] == "auth_required" and "login_url" not in p.status()
    # a second login can reuse the port
    url2 = p.start(host="localhost")
    assert url2 != url and port_open(port)


def test_port_closes_on_timeout(make_provider):
    port = free_port()
    p = make_provider(login_port=port, lifetime=0.4)
    p.start(host="localhost")
    assert port_open(port)
    assert wait_for(lambda: not port_open(port))
    assert wait_for(lambda: p.status()["state"] == "auth_required")


def test_port_in_use_raises_auth_required(make_provider):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        p = make_provider(login_port=busy.getsockname()[1])
        with pytest.raises(AuthRequired, match="port"):
            p.start(host="localhost")
        assert p.status()["state"] == "auth_required"


def _get(port: int, path: str, host: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Host": host, "Sec-Fetch-Mode": "navigate"})
    r = conn.getresponse()
    body = r.read().decode()
    conn.close()
    return r.status, body


def test_cookie_capture_completes_login_and_closes_port(make_provider, amazon):
    def upstream(request):
        return httpx.Response(200, request=request, headers={
            "Content-Type": "text/html", "Set-Cookie": "x-acbit=synthetic; Domain=.amazon.it; Path=/; Secure"},
            text="ok")

    port = free_port()
    p = make_provider(login_port=port, register_device=False, login_transport=httpx.MockTransport(upstream),
                      grace=0.2)
    path = urlsplit(p.start(host="localhost")).path
    assert _get(port, "/other", f"localhost:{port}")[0] == 403  # not the capability path
    assert _get(port, path, "evil.example")[0] == 403  # wrong Host
    status, body = _get(port, path, f"localhost:{port}")
    assert status == 200 and "Signed in" in body
    assert wait_for(lambda: not port_open(port))
    st = p.status()
    assert st["state"] == "ok" and st["method"] == "cookies"
    assert p.pop_login_completed() is True
    assert p.get_session().is_authenticated


def test_device_registration_capture_stores_token_then_renews(make_provider, amazon):
    from amazon_orders_ha.auth.device import DeviceFlow

    port = free_port()
    p = make_provider(login_port=port, grace=0.2)
    p.start(host="localhost")
    server = p._server
    proxy = server.proxy
    proxy.device = DeviceFlow()  # normally created on the first proxied request

    class Resp:
        url = "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=SYNTHETIC-CODE"

    import asyncio

    html = asyncio.run_coroutine_threadsafe(proxy._capture(Resp(), {}, {}), server._loop).result(15)
    assert "Signed in" in html
    assert [c.url.path for c in amazon.calls] == ["/auth/register", "/auth/token"]
    body = json.loads(amazon.calls[0].content)
    assert body["auth_data"]["authorization_code"] == "SYNTHETIC-CODE"
    assert p.device_path.stat().st_mode & 0o777 == 0o600
    assert wait_for(lambda: not port_open(port))
    assert p.status()["state"] == "ok" and p.status()["method"] == "device"
    assert p.pop_login_completed() is True
    assert p.get_session().is_authenticated


def test_device_mode_proxies_global_signin_with_pkce(make_provider):
    seen: list[httpx.Request] = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, request=request, headers={"Content-Type": "text/html"}, text="<form></form>")

    port = free_port()
    p = make_provider(login_port=port, login_transport=httpx.MockTransport(upstream))
    path = urlsplit(p.start(host="ha.local")).path
    assert seen == []  # nothing leaves before the human opens the link
    status, _ = _get(port, path, f"ha.local:{port}")
    assert status == 200 and len(seen) == 1
    query = parse_qs(seen[0].url.query.decode())
    assert seen[0].url.host == "www.amazon.com" and seen[0].url.path == "/ap/signin"
    assert query["openid.oa2.scope"] == ["device_auth_access"] and "openid.oa2.code_challenge" in query


def test_link_port_and_bind_port_are_independent(make_provider):
    """In the add-on the listener binds 8098 in the container; the link uses the mapped host port."""
    p = make_provider(login_port=18098, bind_port=8098)
    assert p.bind_port == 8098
    assert p._public_base("192.168.1.10") == "http://192.168.1.10:18098/"


def test_factory_binds_container_port(tmp_path):
    from types import SimpleNamespace

    from amazon_orders_ha.auth.provider import CONTAINER_LOGIN_PORT, create_auth_provider

    opts = SimpleNamespace(domain="amazon.it", login_port=9000, login_host="")
    p = create_auth_provider(SimpleNamespace(data_dir=tmp_path, options=opts))
    assert p.bind_port == CONTAINER_LOGIN_PORT == 8098 and p.login_port == 9000


def test_public_browser_host_falls_back_to_supervisor_lan_address(make_provider, monkeypatch):
    import amazon_orders_ha.auth.provider as prov

    monkeypatch.setattr(prov, "resolves_to_lan", lambda host: False)
    p = make_provider(login_port=8098, lan_address=lambda: "192.168.1.20")
    assert p._public_base("ha.example.org:8123") == "http://192.168.1.20:8098/"
    p = make_provider(login_port=8098, lan_address=lambda: None)
    with pytest.raises(AuthRequired, match="login_host"):
        p._public_base("ha.example.org:8123")


def test_local_dns_name_is_kept(make_provider, monkeypatch):
    import amazon_orders_ha.auth.provider as prov

    monkeypatch.setattr(prov, "resolves_to_lan", lambda host: host == "ha.example.net")
    p = make_provider(login_port=8098, lan_address=lambda: "192.168.1.20")
    assert p._public_base("ha.example.net:8123") == "http://ha.example.net:8098/"


def test_supervisor_lan_address_prefers_primary_interface(monkeypatch):
    from amazon_orders_ha.auth.provider import supervisor_lan_address

    payload = {"data": {"interfaces": [
        {"interface": "wlan0", "primary": False, "ipv4": {"address": ["192.168.50.9/24"]}},
        {"interface": "eth0", "primary": True, "ipv4": {"address": ["192.168.1.20/24"]}},
    ]}}
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    assert supervisor_lan_address(transport) == "192.168.1.20"
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    assert supervisor_lan_address(transport) is None


@pytest.mark.parametrize("host", ["100.101.2.3:8123", "homeassistant.tail1234.ts.net", "[fd7a:115c:a1e0::1]:8123"])
def test_tailscale_hosts_are_used_directly(make_provider, host):
    from amazon_orders_ha.auth.urls import split_host

    p = make_provider(login_port=8098, lan_address=lambda: "192.168.1.20")
    name, _ = split_host(host)
    assert p._public_base(host).startswith("http://" + (f"[{name}]" if ":" in name else name) + ":8098/")


def test_supervisor_lan_address_skips_tailscale_interface(monkeypatch):
    from amazon_orders_ha.auth.provider import supervisor_lan_address

    payload = {"data": {"interfaces": [
        {"interface": "tailscale0", "primary": True, "ipv4": {"address": ["100.101.2.3/32"]}},
        {"interface": "eth0", "primary": False, "ipv4": {"address": ["192.168.1.20/24"]}},
    ]}}
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    assert supervisor_lan_address(transport) == "192.168.1.20"


def test_describe_error_never_leaks_query_strings():
    from amazon_orders_ha.auth.proxy import describe_error

    req = httpx.Request("POST", "https://api.amazon.com/auth/register?code=SECRET")
    exc = httpx.HTTPStatusError("boom", request=req, response=httpx.Response(400, request=req))
    assert describe_error(exc) == "HTTPStatusError: HTTP 400 from api.amazon.com/auth/register"
    msg = describe_error(ValueError("bad url https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=SECRET"))
    assert "SECRET" not in msg and msg.startswith("ValueError")
