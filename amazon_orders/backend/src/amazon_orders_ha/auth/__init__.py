"""Amazon authentication: one AuthProvider contract, a production DeviceAuthProvider, dev providers.

Heavy dependencies (aiohttp, authcaptureproxy) are imported lazily when a login actually starts.
"""

from .base import (
    AuthProvider,
    AuthRequired,
    AuthStatus,
    AuthTemporarilyUnavailable,
    CookieStore,
    RenewableAuth,
)
from .local import CookieFileAuthProvider, DevAuthProvider
from .provider import DeviceAuthProvider, create_auth_provider

__all__ = [
    "AuthProvider",
    "AuthRequired",
    "AuthStatus",
    "AuthTemporarilyUnavailable",
    "CookieFileAuthProvider",
    "CookieStore",
    "DevAuthProvider",
    "DeviceAuthProvider",
    "RenewableAuth",
    "create_auth_provider",
]
