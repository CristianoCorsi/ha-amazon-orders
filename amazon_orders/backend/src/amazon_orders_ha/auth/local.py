"""Development-only providers: a plain cookie file and a fake always-ok provider."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import AuthRequired, AuthStatus, CookieStore

log = logging.getLogger(__name__)


class CookieFileAuthProvider:
    """DEV ONLY: reuses a cookie jar already present in ``<data>/amazonorders/``. No sign-in, no renewal."""

    method = "cookie_file"

    def __init__(self, data_dir: Path, domain: str = "amazon.it", cookie_path: Path | None = None):
        self.data_dir = Path(data_dir)
        self.domain = domain
        self.store = CookieStore(self.data_dir / "amazonorders", domain)
        self.cookie_path = cookie_path or self.store.cookie_path
        if cookie_path is not None:
            self.store.cookie_path = cookie_path

    def get_session(self) -> Any:
        if not self.cookie_path.is_file():
            raise AuthRequired("no stored Amazon session")
        session = self.store.new_session()
        if not session.auth_cookies_stored():
            session.session.close()
            raise AuthRequired("stored session has no authentication cookies")
        session.is_authenticated = True
        return session

    def status(self) -> AuthStatus:
        try:
            session = self.get_session()
        except AuthRequired:
            return {"state": "auth_required", "method": self.method, "expires_hint": None}
        except Exception:  # unreadable jar etc.; never log contents
            log.warning("Cannot read stored session")
            return {"state": "auth_required", "method": self.method, "expires_hint": None}
        names = set(session.config.constants.COOKIES_SET_WHEN_AUTHENTICATED)
        exp = [c.expires for c in session.session.cookies if c.name in names and c.expires]
        session.session.close()
        hint = datetime.fromtimestamp(min(exp), UTC).date().isoformat() if exp else None
        return {"state": "ok", "method": self.method, "expires_hint": hint}

    def start(self, host: str | None = None) -> str:
        raise AuthRequired("interactive sign-in is not available with the cookie-file provider")

    def logout(self) -> None:
        self.cookie_path.unlink(missing_ok=True)


class DevAuthProvider:
    """Frontend development only (AMAZON_ORDERS_DEV_AUTH=1): reports a valid session, never sessions."""

    method = "dev"

    def status(self) -> AuthStatus:
        return {"state": "ok", "method": self.method, "expires_hint": None}

    def start(self, host: str | None = None) -> str:
        return "#dev-login"

    def logout(self) -> None:
        pass

    def get_session(self) -> Any:
        raise AuthRequired("dev auth provider has no real session")
