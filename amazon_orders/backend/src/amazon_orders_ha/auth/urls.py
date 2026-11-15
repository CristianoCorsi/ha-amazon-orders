"""Strict path-prefix rewriting, shared with proxy security checks."""

from __future__ import annotations

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
