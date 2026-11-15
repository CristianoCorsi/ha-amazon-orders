#!/usr/bin/env python3
"""Local human-only login relay. stdout is reserved for the order count.

No Amazon request is made at startup: open the displayed localhost link to
begin. This is a research prototype, NOT a production HA Ingress endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import logging
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amazon_orders_ha.auth import AuthRequired, ProxyAuthProvider  # noqa: E402


def count_recent_orders(provider: ProxyAuthProvider) -> int:
    """One last-30-days list operation, no details, 20–40s between pages."""
    from amazonauth.util import select_one
    from amazonorders.orders import AmazonOrders

    session = provider.new_session()
    if not session.auth_cookies_stored():
        session.session.close()
        raise AuthRequired("Missing auth cookies")
    original = session.request
    last = 0.0

    def read_only(method, url, **kwargs):
        nonlocal last
        parts = urlsplit(url)
        if (
            method.upper() != "GET"
            or parts.scheme != "https"
            or parts.hostname != "www.amazon.it"
            or not (parts.path.startswith("/your-orders") or parts.path == "/gp/css/order-history")
        ):
            raise AuthRequired("Unexpected order-list request")
        if last:
            time.sleep(max(0.0, random.uniform(20, 40) - (time.monotonic() - last)))
        response = original(method, url, **kwargs)
        last = time.monotonic()
        session.check_response(response)
        if select_one(response.parsed, session.config.selectors.ORDER_HISTORY_COUNT_SELECTOR) is None:
            raise AuthRequired("Order history marker missing: challenge or changed HTML")
        return response

    session.request = read_only
    session.is_authenticated = True  # The following GET validates, never calls login().
    try:
        orders = AmazonOrders(session).get_orders(time_filter="last30", full_details=False, keep_paging=True)
        provider._session = session
        provider._verified = True
        return len(orders)
    except Exception:
        session.session.close()
        provider.invalidate()
        raise


async def serve(args: argparse.Namespace) -> None:
    from aiohttp import web

    data_dir = args.data_dir.expanduser().resolve()
    # Never reuse/copy a user's existing session. mktemp creates an empty dir.
    if data_dir.exists() and (not data_dir.is_dir() or any(data_dir.iterdir())):
        raise ValueError("--data-dir must be a new or empty temporary directory")
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    data_dir.chmod(0o700)
    provider = ProxyAuthProvider(
        data_dir, "http://localhost:8098/", register_device=args.register_device, lifetime=args.timeout
    )
    url = provider.start()
    app = web.Application(client_max_size=2 * 1024 * 1024)

    async def landing(request):
        return web.Response(
            content_type="text/html",
            text=(
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                "<h1>Amazon login experiment</h1><p>This localhost relay handles your password and OTP "
                "transiently. It saves cookies, never credentials. Do not enable DEBUG logs.</p>"
                + (
                    "<p>Experimental device registration is enabled: this creates an Amazon account device "
                    "and saves a long-lived refresh token. Remove it manually in Amazon afterwards.</p>"
                    if args.register_device
                    else ""
                )
                + '<p><a href="'
                + html.escape(url, quote=True)
                + '">Start Amazon sign-in</a></p>'
                "<p>If a JavaScript/CAPTCHA challenge loops, stop; use the real-browser fallback.</p>"
            ),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"},
        )

    async def health(request):
        return web.json_response({"state": provider.status()["state"]}, headers={"Cache-Control": "no-store"})

    app.router.add_get("/", landing)
    app.router.add_get("/healthz", health)
    app.router.add_route("*", "/{tail:.*}", provider.handle)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, host="127.0.0.1", port=8098).start()
        print("Open http://localhost:8098 in your own browser. No upstream requests yet.", file=sys.stderr, flush=True)
        print("Temporary session directory: " + str(data_dir), file=sys.stderr, flush=True)
        await asyncio.wait_for(provider.captured.wait(), timeout=args.timeout)
        count = await asyncio.to_thread(count_recent_orders, provider)
        print(count, flush=True)
        print("Read-only check succeeded. Remove the temporary directory when finished.", file=sys.stderr, flush=True)
        await asyncio.sleep(2)
    finally:
        await runner.cleanup()
        await provider.aclose()
        provider.invalidate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True, type=Path, help="New/empty TEMP directory; never your existing Amazon config"
    )
    parser.add_argument(
        "--register-device",
        action="store_true",
        help="EXPERIMENTAL: create a virtual device and retain a renewable token",
    )
    parser.add_argument("--timeout", type=int, default=900, help="Human login time limit in seconds (default 900)")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    os.umask(0o077)
    # Upstream's DEBUG helper dumps raw requests/forms/cookies. Disable all
    # logging for this standalone process, including server exception tracebacks.
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 130
    except TimeoutError:
        print("Login timed out; no count was produced.", file=sys.stderr)
        return 2
    except Exception:
        print("Login/check failed; no count was produced. No sensitive exception details were logged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
