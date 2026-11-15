"""FastAPI application: the HTTP API of SPEC §10 plus the static frontend."""

import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, repo
from .auth_provider import AuthRequired
from .ics import build_ics
from .service import BackgroundRunner, Runtime

log = logging.getLogger(__name__)

_INGRESS_RE = re.compile(r"^/[A-Za-z0-9_./~-]*$")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class StatePatch(BaseModel):
    status: Literal["none", "keep", "to_return", "returned"] | None = None
    note: str | None = Field(default=None, max_length=4000)
    warranty_until_override: date | None = None
    warranty_months_override: int | None = Field(default=None, ge=1, le=240)


class BackfillBody(BaseModel):
    action: Literal["start", "pause"]


class PurgeBody(BaseModel):
    scope: str = Field(pattern=r"^(all|year:\d{4}|order:[A-Za-z0-9-]+)$")


def _valid_date(v: str | None, name: str) -> str | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ApiError(422, "validation_error", f"{name} must be YYYY-MM-DD") from None


def create_app(rt: Runtime, background: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if background:
            rt.runner = BackgroundRunner(rt)
            rt.runner.start()
        yield
        if rt.runner:
            rt.runner.stop()

    app = FastAPI(title="Amazon Orders", version=__version__, lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    opts = rt.settings.options

    def conn_dep():
        c = rt.db.connect()
        try:
            yield c
        finally:
            c.close()

    Conn = Annotated[Any, Depends(conn_dep)]

    # ---- errors
    @app.exception_handler(ApiError)
    async def _api_error(_r: Request, e: ApiError):
        return _err(e.status, e.code, e.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_r: Request, e: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return _err(e.status_code, code, str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, e: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in err['loc'][1:])}: {err['msg']}" for err in e.errors())
        return _err(422, "validation_error", msg)

    @app.exception_handler(Exception)
    async def _unhandled(_r: Request, e: Exception):
        log.exception("unhandled error")
        return _err(500, "internal_error", "internal error")

    # ---- shared filter parsing
    def filters(
        q: str | None = None,
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: str | None = None,
        seller: str | None = None,
        status: Literal["none", "keep", "to_return", "returned", "cancelled"] | None = None,
        min: float | None = None,
        max: float | None = None,
        sort: Literal["date_desc", "date_asc", "total_desc", "total_asc", "price_desc", "price_asc",
                      "title_asc"] = "date_desc",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> repo.Filters:
        return repo.Filters(q=(q or "").strip() or None, date_from=_valid_date(from_, "from"),
                            date_to=_valid_date(to, "to"), seller=seller or None, status=status, min=min,
                            max=max, sort=sort, page=page, page_size=page_size)

    F = Annotated[repo.Filters, Depends(filters)]
    today = rt.today

    # ---- status / settings
    @app.get("/api/status")
    def status():
        s = rt.engine.status()
        s["currency"] = repo.CURRENCY
        s["version"] = __version__
        s["ha"] = {"events": bool(getattr(rt.integration.events, "token", None)),
                   "mqtt": bool(opts.mqtt.configured)}
        return s

    @app.get("/api/settings")
    def settings():
        return {
            "version": __version__, "currency": repo.CURRENCY, "domain": opts.domain,
            "sync_preset": opts.sync_preset, "recent_refresh_hours": opts.recent_refresh_hours,
            "backfill_until_year": opts.backfill_until_year, "return_thresholds": opts.return_thresholds,
            "warranty_thresholds": opts.warranty_thresholds,
            "default_warranty_months": opts.default_warranty_months,
            "mqtt_configured": opts.mqtt.configured, "log_level": opts.log_level,
            "calendar_path": "calendar.ics",
        }

    # ---- auth
    @app.get("/api/auth/status")
    def auth_status():
        st = dict(rt.auth.status())
        if rt.engine.status()["auth"]["state"] == "auth_required" and st.get("state") == "ok":
            st["state"] = "auth_required"
        return st

    @app.post("/api/auth/start")
    def auth_start():
        try:
            url = rt.auth.start()
        except AuthRequired as e:
            raise ApiError(501, "auth_unavailable", str(e) or "sign-in flow not available") from e
        rt.engine.clear_auth_required()
        return {"url": url}

    @app.post("/api/auth/logout")
    def auth_logout():
        rt.auth.logout()
        return {"ok": True}

    # ---- orders / items
    @app.get("/api/orders")
    def orders(f: F, c: Conn):
        return repo.list_orders(c, f)

    @app.get("/api/orders/{order_number}")
    def order(order_number: str, c: Conn):
        o = repo.get_order(c, order_number, today(), opts.default_warranty_months)
        if not o:
            raise ApiError(404, "not_found", "order not found")
        return o

    @app.get("/api/items")
    def items(f: F, c: Conn):
        return repo.list_items(c, f, today(), opts.default_warranty_months)

    @app.patch("/api/items/{item_id}/state")
    def patch_state(item_id: int, body: StatePatch, c: Conn):
        changes = {k: (v.isoformat() if isinstance(v, date) else v)
                   for k, v in body.model_dump(exclude_unset=True).items()}
        if changes.get("status") is None:
            changes.pop("status", None)
        if "note" in changes and changes["note"] is None:
            changes["note"] = ""
        if not repo.patch_item_state(c, item_id, changes, rt.now()):
            raise ApiError(404, "not_found", "item not found")
        return repo.get_item(c, item_id, today(), opts.default_warranty_months)

    @app.get("/api/deadlines")
    def deadlines(c: Conn, kind: Literal["return", "warranty", "all"] = "all",
                  within_days: Annotated[int | None, Query(ge=0)] = None, include_closed: bool = False):
        return repo.list_deadlines(c, today(), kind, within_days, include_closed, opts.default_warranty_months)

    # ---- stats
    @app.get("/api/stats/summary")
    def st_summary(c: Conn, year: int | None = None):
        return repo.stats_summary(c, year)

    @app.get("/api/stats/monthly")
    def st_monthly(c: Conn, from_: Annotated[str | None, Query(alias="from")] = None, to: str | None = None):
        return repo.stats_monthly(c, from_, to, today())

    @app.get("/api/stats/sellers")
    def st_sellers(c: Conn, year: int | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 10):
        return repo.stats_sellers(c, year, limit)

    @app.get("/api/stats/top-items")
    def st_top(c: Conn, year: int | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 10):
        return repo.stats_top_items(c, year, limit)

    @app.get("/api/stats/recurring")
    def st_recurring(c: Conn, limit: Annotated[int, Query(ge=1, le=200)] = 20):
        return repo.stats_recurring(c, limit)

    @app.get("/api/stats/returns")
    def st_returns(c: Conn, year: int | None = None):
        return repo.stats_returns(c, year)

    @app.get("/api/stats/weekday")
    def st_weekday(c: Conn):
        return repo.stats_weekday(c)

    @app.get("/api/export.csv")
    def export(f: F, c: Conn):
        text = repo.export_csv(c, f, today(), opts.domain, opts.default_warranty_months)
        return Response(text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="amazon-orders.csv"'})

    # ---- jobs
    @app.post("/api/sync/recent")
    def sync_recent():
        rt.engine.request_recent()
        if rt.runner:
            rt.runner.wake.set()
        return {"queued": True}

    @app.post("/api/sync/backfill")
    def sync_backfill(body: BackfillBody):
        st = rt.engine.backfill_control(body.action)
        if rt.runner:
            rt.runner.wake.set()
        return {"status": st["status"], "year": st["year"], "processed": st["processed"]}

    @app.post("/api/cache/purge")
    def cache_purge(body: PurgeBody, c: Conn):
        if body.scope.startswith("order:") and not repo.get_order_meta(c, body.scope[6:]):
            raise ApiError(404, "not_found", "order not found")
        n = rt.engine.purge(body.scope)
        if rt.runner:
            rt.runner.wake.set()
        return {"scope": body.scope, "purged": n}

    @app.get("/calendar.ics")
    def calendar(c: Conn):
        text = build_ics(c, today(), datetime.now(UTC), opts.default_warranty_months, opts.domain)
        return Response(text, media_type="text/calendar; charset=utf-8")

    @app.get("/api/{rest:path}")
    def api_404(rest: str):
        raise ApiError(404, "not_found", f"unknown endpoint api/{rest}")

    # ---- static frontend with SPA fallback (registered last)
    frontend = Path(rt.settings.frontend_dir)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        root = frontend.resolve()
        if path:
            cand = (root / path).resolve()
            if cand.is_file() and root in cand.parents:
                return FileResponse(cand)
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse({"name": "Amazon Orders API", "version": __version__,
                                 "note": "frontend build not found"}, status_code=200)
        html = index.read_text(encoding="utf-8")
        prefix = request.headers.get("x-ingress-path", "").rstrip("/")
        if prefix and not _INGRESS_RE.match(prefix):
            prefix = ""
        if "<base " not in html:
            html = html.replace("<head>", f'<head><base href="{prefix}/">', 1)
        return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})

    return app
