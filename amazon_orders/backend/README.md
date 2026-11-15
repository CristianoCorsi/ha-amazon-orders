# amazon_orders_ha (backend)

FastAPI backend of the ha-amazon-orders add-on. Contract: `docs/SPEC.md`.

```bash
cd amazon_orders/backend
uv venv .venv --python 3.13 && uv pip install -p .venv/bin/python -e ".[dev]"

# synthetic data for frontend development (no Amazon access)
.venv/bin/python -m amazon_orders_ha.dev seed --data-dir ./dev-data --reset
AMAZON_ORDERS_DATA_DIR=./dev-data AMAZON_ORDERS_NO_SYNC=1 AMAZON_ORDERS_DEV_AUTH=1 \
  AMAZON_ORDERS_FRONTEND_DIR=../frontend/build .venv/bin/python -m amazon_orders_ha   # http://localhost:8099

.venv/bin/pytest -q && .venv/bin/ruff check src tests
```

Environment: `AMAZON_ORDERS_DATA_DIR` (default `/data`), `AMAZON_ORDERS_OPTIONS_FILE` (default
`<data>/options.json`), `AMAZON_ORDERS_FRONTEND_DIR`, `AMAZON_ORDERS_PORT` (8099), `AMAZON_ORDERS_NO_SYNC=1`
(no background jobs), `AMAZON_ORDERS_DEV_AUTH=1` (fake "ok" auth for UI work), `SUPERVISOR_TOKEN`.

Auth: `service.make_auth_provider` returns `amazon_orders_ha.auth.DeviceAuthProvider` (login proxy on its own port,
`login_port` option, default 8098, bound only during sign-in; device refresh token in `<data>/auth/`; cookies renewed
automatically). Design and security notes: `docs/auth-design.md`. Dev-only: `AMAZON_ORDERS_DEV_AUTH=1`,
`AMAZON_ORDERS_AUTH=cookie_file`. Standalone checks: `scripts/auth_proxy_demo.py`, `scripts/auth_refresh_check.py`
(run in this venv; they contact Amazon only when a human drives them). All tests, including `tests/auth/`, run offline.
