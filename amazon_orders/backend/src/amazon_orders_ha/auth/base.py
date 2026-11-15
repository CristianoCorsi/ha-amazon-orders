"""Synchronous backend contract and isolated amazon-orders cookie storage."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from amazonorders.session import AmazonSession


class AuthRequired(RuntimeError):
    """The worker must stop and ask the human to sign in."""


class AuthStatus(TypedDict):
    state: str
    method: str
    expires_hint: str | None


@runtime_checkable
class AuthProvider(Protocol):
    def status(self) -> AuthStatus: ...
    def start(self) -> str: ...
    def logout(self) -> None: ...
    def get_session(self) -> AmazonSession: ...


class CookieAuthProvider:
    """Never invokes login(), prompts for credentials, or reads the home config.

    get_session() may perform ONE read-only order-history verification. Invoke
    it in the backend's single request gate/thread, never in an async route.
    invalidate() must be called on subsequent Amazon authentication failures.
    """

    method = "cookies"

    def __init__(self, data_dir: Path, domain: str = "amazon.it") -> None:
        if domain != "amazon.it":
            raise ValueError("Only amazon.it is enabled in this prototype")
        self.data_dir = Path(data_dir).resolve()
        forbidden = (Path.home() / ".config" / "amazonorders").resolve()
        if self.data_dir == forbidden or forbidden in self.data_dir.parents:
            raise ValueError("Refusing the user's existing amazonorders directory")
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cookie_path = self.data_dir / "cookies.amazon.it.json"
        self.domain = domain
        self._session: AmazonSession | None = None
        self._verified = False

    def new_session(self) -> AmazonSession:
        from amazonorders.conf import AmazonOrdersConfig
        from amazonorders.session import AmazonSession

        class IsolatedConfig(AmazonOrdersConfig):
            @classmethod
            def read_environment(cls) -> dict[str, Any]:
                # AMAZON_COOKIE_JAR_PATH and class hooks must not escape /data.
                return {}

        if self.cookie_path.is_symlink():
            raise ValueError("Cookie file must not be a symlink")
        config = IsolatedConfig(
            config_path=str(self.data_dir / "unused-config.yml"),
            data={
                "cookie_jar_path": str(self.cookie_path),
                "domain": self.domain,
                "warn_on_missing_required_field": True,
                "request_timeout": 30,
            },
        )
        return AmazonSession(config=config, debug=False)

    def import_cookies(self, records: list[dict[str, Any]]) -> None:
        self.invalidate()
        session = self.new_session()
        try:
            session.import_cookies(records, verify=False)
        finally:
            session.session.close()

    def status(self) -> AuthStatus:
        return {"state": "ok" if self._verified else "auth_required", "method": self.method, "expires_hint": None}

    def start(self) -> str:
        raise AuthRequired("No interactive transport has been configured")

    def invalidate(self) -> None:
        self._verified = False
        if self._session is not None:
            self._session.session.close()
        self._session = None

    def get_session(self) -> AmazonSession:
        if self._session is not None and self._verified:
            return self._session
        session = self.new_session()
        try:
            if not session.check_session(verify=True):
                raise AuthRequired("Sign in again")
        except Exception:
            session.session.close()
            self.invalidate()
            raise AuthRequired("Session verification failed; sign in again") from None
        session.is_authenticated = True
        self._session = session
        self._verified = True
        return session

    def logout(self) -> None:
        # Local logout only: upstream logout() would send an Amazon request.
        self.invalidate()
        self.cookie_path.unlink(missing_ok=True)
        (self.data_dir / "device.json").unlink(missing_ok=True)
