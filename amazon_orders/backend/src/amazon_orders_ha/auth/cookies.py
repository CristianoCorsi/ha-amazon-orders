"""Conversions to amazon-auth's public import_cookies format (no I/O)."""

from __future__ import annotations

from http.cookiejar import CookieJar
from typing import Any


def is_site_domain(candidate: str, site: str) -> bool:
    host = candidate.lstrip(".").lower()
    return host == site or host.endswith("." + site)


def cookiejar_records(jar: CookieJar, site: str = "amazon.it") -> list[dict[str, Any]]:
    """Keep domain/path collisions, secure flags and session-cookie expiry."""
    return [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": c.secure, "expires": c.expires}
        for c in jar
        if is_site_domain(c.domain, site) and not c.is_expired()
    ]
