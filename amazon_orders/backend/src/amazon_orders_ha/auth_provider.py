"""Authentication interface used by the sync engine, plus a cookie-file provider.

The real login flows live in ``amazon_orders_ha.auth`` (separate work stream). This module only defines
the contract and a provider that reuses the cookie jar amazon-orders already stores.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


class AuthRequired(Exception):
    """No valid Amazon session: the user has to sign in again."""


@runtime_checkable
class AuthProvider(Protocol):
    def status(self) -> dict[str, Any]:
        """``{state: 'ok'|'auth_required'|'in_progress', method, expires_hint}``."""

    def start(self) -> str:
        """Begin an authentication flow and return the URL to send the user to."""

    def logout(self) -> None: ...

    def get_session(self) -> Any:
        """Authenticated ``amazonorders.session.AmazonSession`` or raise ``AuthRequired``."""


def build_config(data_dir: Path, domain: str, cookie_path: Path | None = None) -> Any:
    """AmazonOrdersConfig that keeps everything under ``<data>/amazonorders/``."""
    from amazonorders.conf import AmazonOrdersConfig

    adir = Path(data_dir) / "amazonorders"
    adir.mkdir(parents=True, exist_ok=True)
    return AmazonOrdersConfig(
        config_path=str(adir / "config.yml"),
        data={
            "domain": domain,
            "cookie_jar_path": str(cookie_path or adir / f"cookies.{domain}.json"),
            "output_dir": str(adir / "output"),
            "warn_on_missing_required_field": True,
        },
    )


class CookieFileAuthProvider:
    """Uses the cookie jar written by amazon-orders (or by a browser sign-in) in the data dir."""

    method = "cookie_file"

    def __init__(self, data_dir: Path, domain: str = "amazon.it", cookie_path: Path | None = None):
        self.data_dir = Path(data_dir)
        self.domain = domain
        self.cookie_path = cookie_path or self.data_dir / "amazonorders" / f"cookies.{domain}.json"
        self.config = None

    def _config(self) -> Any:
        if self.config is None:
            self.config = build_config(self.data_dir, self.domain, self.cookie_path)
        return self.config

    def get_session(self) -> Any:
        from amazonorders.session import AmazonSession

        if not self.cookie_path.is_file():
            raise AuthRequired("no stored Amazon session")
        session = AmazonSession(config=self._config())
        if not session.auth_cookies_stored():
            raise AuthRequired("stored session has no authentication cookies")
        session.is_authenticated = True
        return session

    def status(self) -> dict[str, Any]:
        try:
            session = self.get_session()
        except AuthRequired:
            return {"state": "auth_required", "method": self.method, "expires_hint": None}
        except Exception:  # unreadable jar etc.; never log contents
            log.warning("Cannot read stored session")
            return {"state": "auth_required", "method": self.method, "expires_hint": None}
        names = set(session.config.constants.COOKIES_SET_WHEN_AUTHENTICATED)
        exp = [c.expires for c in session.session.cookies if c.name in names and c.expires]
        hint = datetime.fromtimestamp(min(exp), UTC).date().isoformat() if exp else None
        return {"state": "ok", "method": self.method, "expires_hint": hint}

    def start(self) -> str:
        raise AuthRequired("interactive sign-in is provided by the auth subpackage")

    def logout(self) -> None:
        if self.cookie_path.exists():
            self.cookie_path.unlink()


class DevAuthProvider:
    """Frontend development only (AMAZON_ORDERS_DEV_AUTH=1): reports a valid session, never sessions."""

    method = "dev"

    def status(self) -> dict[str, Any]:
        return {"state": "ok", "method": self.method, "expires_hint": None}

    def start(self) -> str:
        return "#dev-login"

    def logout(self) -> None:
        pass

    def get_session(self) -> Any:
        raise AuthRequired("dev auth provider has no real session")
