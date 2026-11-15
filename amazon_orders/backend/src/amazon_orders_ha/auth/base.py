"""Auth contract (one interface for the whole backend) and isolated amazon-orders cookie storage."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from amazonorders.session import AmazonSession

#: Cookie that amazon-auth 1.1.0 uses as "this jar is authenticated" marker (all sites).
AUTH_COOKIE = "x-acbit"


class AuthRequired(RuntimeError):
    """No valid Amazon session: the human has to sign in again."""


class AuthTemporarilyUnavailable(RuntimeError):
    """Renewal failed for a transient reason (network, HTTP 5xx/429). The session is not known to be bad."""


class AuthStatus(TypedDict):
    state: str  # 'ok' | 'auth_required' | 'in_progress'
    method: str | None  # 'device' | 'cookies' | ... | None when nothing is stored
    expires_hint: str | None
    login_url: NotRequired[str]  # only while state == 'in_progress'
    last_error: NotRequired[str]  # e.g. 'duplicate_device' after a failed sign-in


@runtime_checkable
class AuthProvider(Protocol):
    """What the sync engine and the API need. All methods are synchronous and thread-safe.

    Optional capabilities, discovered with ``getattr`` (see :class:`RenewableAuth`), are not part of the
    required surface so that simple providers and test fakes stay small.
    """

    def status(self) -> AuthStatus:
        """No network. ``login_url`` is present only while ``state == 'in_progress'``."""

    def start(self, host: str | None = None) -> str:
        """Begin an interactive sign-in; return the absolute URL the user must open.

        ``host`` is the host (optionally with port) the user's browser used to reach the add-on. Raises
        :class:`AuthRequired` when no flow can be started.
        """

    def logout(self) -> None:
        """Forget the session locally (and deregister the device at Amazon, best effort, if one exists)."""

    def get_session(self) -> AmazonSession:
        """Authenticated ``AmazonSession`` (no Amazon request unless cookies must be renewed) or ``AuthRequired``."""


class RenewableAuth(Protocol):
    def renew_session(self) -> bool:
        """Amazon rejected the current cookies: renew once, in place. True when fresh cookies are in use."""

    def renew_if_due(self) -> bool:
        """Proactive renewal job. True when a renewal happened."""

    def pop_login_completed(self) -> bool:
        """True exactly once after an interactive sign-in finished successfully."""


class CookieStore:
    """One amazon-orders cookie jar in a private directory. Never calls login(), never reads user config/env."""

    def __init__(self, directory: Path, domain: str = "amazon.it") -> None:
        self.directory = Path(directory).resolve()
        forbidden = (Path.home() / ".config" / "amazonorders").resolve()
        if self.directory == forbidden or forbidden in self.directory.parents:
            raise ValueError("Refusing the user's existing amazonorders directory")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.domain = domain
        self.cookie_path = self.directory / f"cookies.{domain}.json"

    def new_session(self) -> AmazonSession:
        from amazonorders.conf import AmazonOrdersConfig
        from amazonorders.session import AmazonSession

        class IsolatedConfig(AmazonOrdersConfig):
            @classmethod
            def read_environment(cls) -> dict[str, Any]:
                # AMAZON_COOKIE_JAR_PATH & co. must not escape the add-on data directory.
                return {}

        if self.cookie_path.is_symlink():
            raise ValueError("Cookie file must not be a symlink")
        config = IsolatedConfig(
            config_path=str(self.directory / "unused-config.yml"),
            data={
                "cookie_jar_path": str(self.cookie_path),
                "domain": self.domain,
                "output_dir": str(self.directory / "output"),
                "warn_on_missing_required_field": True,
                "request_timeout": 30,
            },
        )
        return AmazonSession(config=config, debug=False)

    def import_cookies(self, records: list[dict[str, Any]], session: AmazonSession | None = None) -> None:
        """Replace the stored cookies (no network). With ``session``, update that live session in place."""
        own = session is None
        session = session or self.new_session()
        try:
            session.import_cookies(records, verify=False)
        finally:
            if own:
                session.session.close()

    def clear(self) -> None:
        self.cookie_path.unlink(missing_ok=True)
