"""Strict path-prefix rewriting, shared with proxy security checks."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .cookies import is_site_domain


def checked_https(url: str, site: str, *, waf: bool = False) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    allowed = is_site_domain(host, site)
    if waf:
        allowed |= any(
            is_site_domain(host, root) for root in ("awswaf.com", "amazoncognito.com", "ssl-images-amazon.com")
        )
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443) or not allowed:
        raise ValueError("Upstream origin is not allowed")
    return url


def rewrite_url(target: str, page_url: str, proxy_base: str) -> str:
    """Resolve relative form actions before moving them beneath the proxy base."""
    site = (urlsplit(page_url).hostname or "").removeprefix("www.")
    parts = urlsplit(checked_https(urljoin(page_url, target), site))
    base = urlsplit(proxy_base)
    return urlunsplit((base.scheme, base.netloc, base.path.rstrip("/") + parts.path, parts.query, parts.fragment))


def upstream_url(request_path: str, proxy_base: str, site: str) -> str:
    """Reject prefix escapes, even before the upstream client sees the URL."""
    parts = urlsplit(request_path)
    prefix = urlsplit(proxy_base).path.rstrip("/") + "/"
    if parts.scheme or parts.netloc or not parts.path.startswith(prefix):
        raise ValueError("Wrong proxy path")
    tail = parts.path[len(prefix) :]
    decoded = tail
    for _ in range(4):
        decoded = unquote(decoded)
    if "\\" in decoded or any(p in (".", "..") for p in decoded.split("/")):
        raise ValueError("Unsafe path")
    if tail.startswith("__amzn_host__"):
        host, _, path = tail[len("__amzn_host__") :].partition("/")
        target = "https://" + host + "/" + path
    else:
        target = "https://www." + site + "/" + tail
    if parts.query:
        target += "?" + parts.query
    return checked_https(target, site, waf=True)


_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*$")
_LAN_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa", ".localdomain")
# Tailscale: MagicDNS names and tailnet addresses. Traffic inside a tailnet is end-to-end encrypted
# (WireGuard), so serving the plain-HTTP login page there is as safe as on the home LAN.
_TAILSCALE_SUFFIXES = (".ts.net",)
_TAILSCALE_NETS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


def is_tailscale_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(_TAILSCALE_SUFFIXES)
    return any(ip in net for net in _TAILSCALE_NETS)


def split_host(value: str | None) -> tuple[str, int | None]:
    """Hostname and optional port from a Host / X-Forwarded-Host style value (first entry of a list wins).

    Raises ValueError for anything that is not a plain hostname or IP literal, so the result is safe to embed in a URL.
    """
    raw = (value or "").split(",")[0].strip()
    if not raw or any(c in raw for c in "/\\@?#% \t\r\n"):
        raise ValueError("Invalid host")
    parts = urlsplit("//" + raw)
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ValueError("Invalid host") from None
    if not host:
        raise ValueError("Invalid host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST_RE.match(host):
            raise ValueError("Invalid host") from None
    return host.lower(), port


def is_lan_host(host: str) -> bool:
    """Loopback, private/link-local IPs, single-label and mDNS/LAN-style names. The login relay speaks plain HTTP."""
    if is_tailscale_host(host):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith(_LAN_SUFFIXES)
    return ip.is_private or ip.is_loopback or ip.is_link_local


def resolves_to_lan(host: str) -> bool:
    """True when a DNS name resolves only to LAN addresses (e.g. a local DNS entry like ha.example.net)."""
    import socket

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    ips = {info[4][0] for info in infos}
    return bool(ips) and all(is_lan_host(ip) for ip in ips)


def format_netloc(host: str, port: int | None) -> str:
    bracket = f"[{host}]" if ":" in host else host
    return f"{bracket}:{port}" if port else bracket
