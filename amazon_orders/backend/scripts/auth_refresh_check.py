#!/usr/bin/env python3
"""Check that a registered-device refresh token renews web cookies without a login.

Reads ``device.json`` written by ``auth_proxy_demo.py --register-device``, exchanges the
refresh token for fresh amazon.it web cookies, stores them in a NEW empty directory and runs
the same read-only last-30-days check. stdout carries only the order count; the token and
cookies are never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth_proxy_demo import count_recent_orders  # noqa: E402

from amazon_orders_ha.auth import CookieAuthProvider  # noqa: E402
from amazon_orders_ha.auth.device import exchange_cookie_records, token_form  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-dir", required=True, type=Path, help="Directory holding device.json")
    parser.add_argument("--data-dir", required=True, type=Path, help="NEW empty directory for the renewed cookies")
    args = parser.parse_args()

    if args.data_dir.exists() and any(args.data_dir.iterdir()):
        print("--data-dir must be empty", file=sys.stderr)
        return 2
    device = json.loads((args.device_dir / "device.json").read_text())

    import httpx

    with httpx.Client(trust_env=False, timeout=30, follow_redirects=False) as client:
        response = client.post("https://api.amazon.com/auth/token", data=token_form(device["refresh_token"]))
    if response.status_code != 200:
        print(f"Token exchange failed with HTTP {response.status_code}", file=sys.stderr)
        return 1

    provider = CookieAuthProvider(args.data_dir)
    provider.import_cookies(exchange_cookie_records(response.json()))
    print(count_recent_orders(provider), flush=True)
    print("Renewal check succeeded: fresh cookies obtained without a login.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
