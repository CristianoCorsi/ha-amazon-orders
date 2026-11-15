"""Amazon mobile-device protocol: registration payloads, refresh-token exchange, deregistration.

Protocol reference: LordHenry76/ha-amazon-orders api/auth.py (Apache-2.0,
Copyright 2024 Simone Chemelli and contributors via aioamazondevices) and alexapy ``secureauth.py``.
This module builds payloads and parses answers; the login proxy supplies the human-completed browser auth.
HTTP helpers take an ``httpx`` client so tests can inject a ``MockTransport``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from .cookies import is_site_domain

API_BASE = "https://api.amazon.com"

APP_NAME = "Home Assistant Amazon Orders Auth Experiment"
DEVICE_TYPE = "A2IVLV5VM2W81"
APP_VERSION = "2.2.663733.0"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class DeviceFlow:
    """Ephemeral PKCE state; never serialize the verifier or authorization code."""

    def __init__(self) -> None:
        self.serial = uuid.uuid4().hex.upper()
        self.client_id = f"{self.serial}#{DEVICE_TYPE}".encode().hex()
        self.verifier = _b64(secrets.token_bytes(32))
        self.frc = base64.b64encode(secrets.token_bytes(313)).decode().rstrip("=")
        self.signin_url = "https://www.amazon.com/ap/signin?" + urlencode(
            {
                "openid.return_to": "https://www.amazon.com/ap/maplanding",
                "openid.oa2.code_challenge_method": "S256",
                "openid.assoc_handle": "amzn_dp_project_dee_ios",
                "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
                "pageId": "amzn_dp_project_dee_ios",
                "accountStatusPolicy": "P1",
                "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
                "openid.mode": "checkid_setup",
                "openid.ns.oa2": "http://www.amazon.com/ap/ext/oauth/2",
                "openid.oa2.client_id": "device:" + self.client_id,
                "language": "en-US",
                "openid.ns.pape": "http://specs.openid.net/extensions/pape/1.0",
                "openid.oa2.code_challenge": _b64(hashlib.sha256(self.verifier.encode()).digest()),
                "openid.oa2.scope": "device_auth_access",
                "openid.ns": "http://specs.openid.net/auth/2.0",
                "openid.pape.max_auth_age": "0",
                "openid.oa2.response_type": "code",
            }
        )

    def app_cookies(self) -> dict[str, str]:
        return {
            "amzn-app-id": "MAPiOSLib/6.0/ToHideRetailLink",
            "frc": self.frc,
            "map-md": base64.b64encode(
                json.dumps(
                    {
                        "device_user_dictionary": [],
                        "device_registration_data": {"software_version": "35602678"},
                        "app_identifier": {"app_version": APP_VERSION, "bundle_id": "com.amazon.echo"},
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }

    def registration_body(self, code: str) -> dict[str, Any]:
        return {
            "requested_extensions": ["device_info"],
            "cookies": {"website_cookies": [], "domain": ".amazon.com"},
            "registration_data": {
                "domain": "Device",
                "app_version": APP_VERSION,
                "device_type": DEVICE_TYPE,
                "device_name": APP_NAME,
                "os_version": "18.5",
                "device_serial": self.serial,
                "device_model": "iPhone",
                "app_name": APP_NAME,
                "software_version": "35602678",
            },
            "auth_data": {
                "use_global_authentication": "true",
                "client_id": self.client_id,
                "authorization_code": code,
                "code_verifier": self.verifier,
                "code_algorithm": "SHA-256",
                "client_domain": "DeviceLegacy",
            },
            "user_context_map": {"frc": self.frc},
            "requested_token_type": ["bearer", "website_cookies"],
        }


def token_form(refresh_token: str, domain: str = "amazon.it", token_type: str = "auth_cookies") -> dict[str, str]:
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "di.sdk.version": "6.12.4",
        "source_token": refresh_token,
        "source_token_type": "refresh_token",
        "requested_token_type": token_type,
        "domain": "www." + domain,
        "package_name": "com.amazon.echo",
        "platform": "iOS",
        "di.hw.version": "iPhone",
        "di.os.name": "iOS",
        "di.os.version": "18.5",
        "current_version": "6.12.4",
        "previous_version": "6.12.4",
    }


def exchange_cookie_records(payload: dict[str, Any], site: str = "amazon.it") -> list[dict[str, Any]]:
    result = []
    for domain, cookies in payload["response"]["tokens"]["cookies"].items():
        if not is_site_domain(domain, site):
            continue
        for cookie in cookies:
            expiry = cookie.get("Expires")
            if isinstance(expiry, str) and not expiry.isdigit():
                expiry = int(parsedate_to_datetime(expiry).timestamp()) if expiry else None
            elif expiry is not None:
                expiry = int(expiry)
            result.append(
                {
                    "name": cookie["Name"],
                    "value": str(cookie["Value"]).removeprefix('"').removesuffix('"'),
                    "domain": domain,
                    "path": cookie.get("Path", "/"),
                    "secure": cookie.get("Secure", True),
                    "expires": expiry,
                }
            )
    if not result:
        raise ValueError("No cookies for the site in token exchange")
    return result


class TokenRejected(Exception):
    """Amazon definitively refused the refresh token (revoked device, bad request)."""


class TokenTransient(Exception):
    """Network failure, HTTP 429/5xx: nothing is known about the token."""


def exchange_refresh_token(client: httpx.Client, refresh_token: str, domain: str = "amazon.it") -> list[dict[str, Any]]:
    """Exchange the device refresh token for fresh web cookies (one request; no login)."""
    try:
        response = client.post(API_BASE + "/auth/token", data=token_form(refresh_token, domain))
    except httpx.HTTPError as exc:
        raise TokenTransient(type(exc).__name__) from None
    if response.status_code in (400, 401, 403):
        raise TokenRejected(f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise TokenTransient(f"HTTP {response.status_code}")
    try:
        return exchange_cookie_records(response.json(), domain)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise TokenRejected("unexpected token answer") from None


def deregister_device(client: httpx.Client, refresh_token: str, domain: str = "amazon.it") -> bool:
    """Best effort: remove the virtual device from the account. Never raises; True when Amazon said 200.

    Endpoint as used by alexapy (``SecureAuth.async_deregister``): ``POST api.amazon.com/auth/deregister`` with a
    bearer access token and ``{"requested_deregister_type": "deregister_device"}``. The access token comes from the
    same ``/auth/token`` endpoint with ``requested_token_type=access_token`` (as in LordHenry76, which marks its
    deregistration unverified). Not verified against Amazon by this project.
    """
    try:
        response = client.post(API_BASE + "/auth/token", data=token_form(refresh_token, domain, "access_token"))
        if response.status_code != 200:
            return False
        access = response.json().get("access_token")
        if not isinstance(access, str) or not access:
            return False
        response = client.post(
            API_BASE + "/auth/deregister",
            json={"requested_deregister_type": "deregister_device"},
            headers={"Authorization": f"Bearer {access}"},
        )
        return response.status_code == 200
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
