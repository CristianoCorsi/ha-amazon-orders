"""``python -m amazon_orders_ha`` — run the server on port 8099."""

from __future__ import annotations

import logging
import os

import uvicorn

from .api import create_app
from .config import load_settings
from .service import build_runtime


def main() -> None:
    settings = load_settings()
    logging.basicConfig(level=getattr(logging, settings.options.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rt = build_runtime(settings)
    app = create_app(rt, background=os.environ.get("AMAZON_ORDERS_NO_SYNC") != "1")
    uvicorn.run(app, host=os.environ.get("AMAZON_ORDERS_HOST", "0.0.0.0"),
                port=int(os.environ.get("AMAZON_ORDERS_PORT", "8099")), log_level="warning",
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
