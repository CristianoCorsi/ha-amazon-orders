"""Sync engine: recent refresh, resumable backfill, purge, backoff (SPEC §5).

The engine is synchronous and meant to run in one worker thread. Every Amazon request goes
through ``_request`` which passes the single ``RequestGate``.
"""

from __future__ import annotations

import logging
import random
import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from . import repo
from .auth import AuthProvider, AuthRequired, AuthTemporarilyUnavailable
from .config import Options
from .db import Database
from .mapping import map_order
from .throttle import (
    Clock,
    Cooldown,
    RequestGate,
    Stopped,
    SystemClock,
    backfill_window_open,
    get_preset,
    next_window_start,
)

log = logging.getLogger(__name__)

RECENT_DAYS = 60
MAX_CONSECUTIVE_PARSE_ERRORS = 3
MAX_DETAIL_FAILURES = 3
MIN_YEAR = 1995
EMPTY_YEARS_TO_STOP = 2

ClientFactory = Callable[[], Any]
Notifier = Callable[[str, dict[str, Any]], bool]


class SyncAbort(Exception):
    """The job must stop (cooldown or auth problem already recorded)."""


class ItemError(Exception):
    """One order could not be processed; continue with the next."""


def classify(exc: BaseException) -> str:
    """Map a library/network exception to ``auth|rate|gone|parse``."""
    try:
        from amazonorders.exception import (
            AmazonOrdersAuthRedirectError,
            AmazonOrdersChallengeUnsolvedError,
            AmazonOrdersEncryptedPageError,
            AmazonOrdersNotFoundError,
            AmazonOrdersUnavailableError,
            AmazonOrdersWafSolverError,
        )
    except ImportError:  # pragma: no cover
        return "parse"
    if isinstance(exc, AuthRequired | AmazonOrdersAuthRedirectError):
        return "auth"
    if isinstance(exc, AmazonOrdersChallengeUnsolvedError | AmazonOrdersWafSolverError |
                  AmazonOrdersEncryptedPageError):
        return "rate"
    if isinstance(exc, AmazonOrdersNotFoundError):
        return "gone"
    if isinstance(exc, AmazonOrdersUnavailableError):
        return "parse"
    m = re.search(r"returned (\d{3})", str(exc))
    if m and (m.group(1) == "429" or m.group(1).startswith("5")):
        return "rate"
    mod = type(exc).__module__
    if mod.startswith(("requests", "urllib3", "httpx")) or isinstance(exc, OSError):
        return "rate"  # network trouble: back off like a block
    return "parse"


class SyncEngine:
    def __init__(
        self,
        db: Database,
        options: Options,
        auth: AuthProvider,
        client_factory: ClientFactory | None = None,
        clock: Clock | None = None,
        notify: Notifier | None = None,
        on_synced: Callable[[], None] | None = None,
        rng: random.Random | None = None,
        stop: threading.Event | None = None,
    ):
        self.db = db
        self.options = options
        self.auth = auth
        self.stop = stop or threading.Event()
        self.clock = clock or SystemClock(self.stop)
        self.rng = rng or random.Random()
        self.preset = get_preset(options.sync_preset)
        self.gate = RequestGate(self.clock, self.preset, self.rng, self.stop)
        self.client_factory = client_factory or self._default_client
        self.notify = notify or (lambda _t, _d: False)
        self.on_synced = on_synced
        self.current_job: str | None = None
        self._consecutive_parse = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing

    def _default_client(self) -> Any:
        from amazonorders.orders import AmazonOrders

        session = self.auth.get_session()
        return AmazonOrders(session, config=session.config)

    def _conn(self) -> sqlite3.Connection:
        return self.db.connect()

    def _now(self):
        return self.clock.now()

    def _set_error(self, conn, code: str, message: str) -> None:
        repo.set_state(conn, "last_error", {"at": self._now().isoformat(timespec="seconds"),
                                            "code": code, "message": message[:300]})

    def _trip(self, conn, reason: str) -> None:
        cd = Cooldown(repo.get_state(conn, "cooldown"))
        dur = cd.trip(self._now(), reason)
        repo.set_state(conn, "cooldown", cd.data)
        self._set_error(conn, "cooldown", reason)
        log.warning("Cooldown %s: %s", dur, reason)
        self.notify("amazon_orders_sync_error", {"reason": reason, "cooldown_until": cd.data["until"],
                                                   "cooldown_minutes": int(dur.total_seconds() // 60)})

    def _require_auth(self, conn, message: str = "session expired") -> None:
        already = repo.get_state(conn, "auth_required")
        repo.set_state(conn, "auth_required", True)
        self._set_error(conn, "auth_required", message)
        if not already:
            self.notify("amazon_orders_auth_required", {"reason": message})

    def clear_auth_required(self, conn=None) -> None:
        c = conn or self._conn()
        try:
            repo.set_state(c, "auth_required", False)
        finally:
            if conn is None:
                c.close()

    def _renew_after_rejection(self) -> bool:
        """Amazon rejected our cookies: ask the provider for ONE renewal (in place). False if not possible."""
        renew = getattr(self.auth, "renew_session", None)
        if renew is None:
            return False
        try:
            return bool(renew())
        except Exception:
            log.exception("session renewal failed")
            return False

    def _request(self, conn, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run one Amazon request through the gate, translating errors (one renewal retry on auth rejection)."""
        renewed = False
        while True:
            self.gate.wait()
            try:
                return fn(*args, **kwargs)
            except Stopped:
                raise
            except Exception as exc:
                kind = classify(exc)
                if kind == "auth":
                    if not renewed and self._renew_after_rejection():
                        renewed = True
                        continue
                    self._require_auth(conn)
                    raise SyncAbort("auth") from exc
                if kind == "rate":
                    self._trip(conn, f"{type(exc).__name__}: {exc}"[:200])
                    raise SyncAbort("rate") from exc
                if kind == "gone":
                    raise ItemError("not found") from exc
                self._consecutive_parse += 1
                self._set_error(conn, "parse_error", f"{type(exc).__name__}: {exc}")
                if self._consecutive_parse > MAX_CONSECUTIVE_PARSE_ERRORS:
                    self._trip(conn, "parse errors on more than 3 consecutive requests")
                    raise SyncAbort("parse") from exc
                raise ItemError(str(exc)) from exc

    def _get_client(self, conn) -> Any:
        try:
            return self.client_factory()
        except AuthRequired as exc:
            self._require_auth(conn, str(exc) or "no session")
            raise SyncAbort("auth") from exc
        except AuthTemporarilyUnavailable as exc:
            # Renewal could not reach Amazon: not an auth failure, back off instead of asking the user to sign in.
            self._trip(conn, str(exc) or "cookie renewal unavailable")
            raise SyncAbort("auth_unavailable") from exc

    def can_run(self, conn) -> str | None:
        """Return a reason string if jobs must not run now."""
        if repo.get_state(conn, "auth_required"):
            return "auth_required"
        if Cooldown(repo.get_state(conn, "cooldown")).active(self._now()):
            return "cooldown"
        return None

    # ------------------------------------------------------------------ ingestion

    def _detail_failures(self, conn) -> dict[str, int]:
        return repo.get_state(conn, "detail_failures", {}) or {}

    def _fetch_detail(self, conn, client, order_number: str, stats: dict[str, int]) -> None:
        try:
            detail = self._request(conn, client.get_order, order_number)
            repo.upsert_order(conn, map_order(detail, True, self._now().date()), self._now())
            stats["details"] += 1
            self._consecutive_parse = 0
        except ItemError:
            fails = self._detail_failures(conn)
            fails[order_number] = fails.get(order_number, 0) + 1
            repo.set_state(conn, "detail_failures", fails)
            stats["errors"] += 1
        except ValueError:  # unusable entity (e.g. no order number)
            stats["errors"] += 1

    def _ingest(self, conn, client, listed: Any, stats: dict[str, int]) -> None:
        try:
            row = map_order(listed, False, self._now().date())
        except ValueError:
            stats["errors"] += 1
            return
        meta = repo.get_order_meta(conn, row.order_number)
        stats["seen"] += 1
        changed = meta is None or meta["list_fingerprint"] != row.fingerprint
        if changed or meta["details_fetched_at"] is None:
            if meta is None:
                stats["new"] += 1
            repo.upsert_order(conn, row, self._now())
        need = meta is None or meta["details_fetched_at"] is None or changed
        if need and self._detail_failures(conn).get(row.order_number, 0) < MAX_DETAIL_FAILURES:
            self._fetch_detail(conn, client, row.order_number, stats)

    # ------------------------------------------------------------------ jobs

    def run_recent(self) -> dict[str, Any]:
        """History pages for the last 60 days; details only for new/changed orders."""
        stats = {"seen": 0, "new": 0, "details": 0, "errors": 0}
        conn = self._conn()
        try:
            reason = self.can_run(conn)
            if reason:
                return {"skipped": reason}
            self.current_job = "recent"
            cutoff = self._now().date() - timedelta(days=RECENT_DAYS)
            client = self._get_client(conn)
            cursor: dict | None = None
            while True:
                kw: dict[str, Any] = {"limit": 1}
                if cursor:
                    kw["cursor"] = cursor
                else:
                    kw["time_filter"] = "months-3"
                try:
                    page = self._request(conn, client.get_orders_page, **kw)
                except ItemError:
                    stats["errors"] += 1
                    break
                reached_old = False
                for order in page.items:
                    placed = getattr(order, "order_placed_date", None)
                    if placed and placed < cutoff:
                        reached_old = True
                        continue
                    self._ingest(conn, client, order, stats)
                cursor = page.cursor
                if reached_old or not cursor or not page.items:
                    break
            repo.set_state(conn, "last_recent", {"at": self._now().isoformat(timespec="seconds"), **stats})
            if stats["errors"] == 0:
                repo.set_state(conn, "cooldown", {})
                repo.set_state(conn, "last_error", None)
            return stats
        except SyncAbort as e:
            return {**stats, "aborted": str(e)}
        except Stopped:
            return {**stats, "aborted": "stopped"}
        finally:
            self.current_job = None
            conn.close()
            self._after()

    def _after(self) -> None:
        if self.on_synced:
            try:
                self.on_synced()
            except Exception:
                log.exception("post-sync hook failed")

    # --- backfill ---

    def _bf_default(self) -> dict[str, Any]:
        return {"status": "running", "year": self._now().year, "start_year": self._now().year,
                "cursor": None, "empty_years": 0, "year_orders": 0, "processed": 0,
                "history_done": False}

    def backfill_state(self, conn) -> dict[str, Any]:
        st = repo.get_state(conn, "backfill")
        if not st:
            st = self._bf_default()
            repo.set_state(conn, "backfill", st)
        return st

    def backfill_control(self, action: str) -> dict[str, Any]:
        conn = self._conn()
        try:
            st = self.backfill_state(conn)
            if action == "pause":
                st["status"] = "paused" if st["status"] != "done" else "done"
            elif action == "start":
                if st["status"] == "done":
                    st = self._bf_default()
                else:
                    st["status"] = "running"
            else:
                raise ValueError("action must be 'start' or 'pause'")
            repo.set_state(conn, "backfill", st)
            return st
        finally:
            conn.close()

    def _until_year(self) -> int:
        return self.options.backfill_until_year or MIN_YEAR

    def _finish_year(self, st: dict[str, Any]) -> None:
        st["empty_years"] = 0 if st["year_orders"] else st["empty_years"] + 1
        nxt = st["year"] - 1
        st.update(cursor=None, year_orders=0)
        if nxt < self._until_year() or st["empty_years"] >= EMPTY_YEARS_TO_STOP:
            st["history_done"] = True
        else:
            st["year"] = nxt

    def run_backfill(self, max_requests: int | None = None) -> dict[str, Any]:
        """Advance the backfill while allowed (running, window open, no cooldown)."""
        stats = {"seen": 0, "new": 0, "details": 0, "errors": 0}
        conn = self._conn()
        try:
            reason = self.can_run(conn)
            if reason:
                return {"skipped": reason}
            st = self.backfill_state(conn)
            client = None
            self.current_job = "backfill"
            while True:
                if self.stop.is_set():
                    break
                st = self.backfill_state(conn)  # picks up pause requests
                if st["status"] != "running":
                    break
                if not backfill_window_open(self.preset, self._now()):
                    stats["waiting"] = "window"
                    break
                if max_requests is not None and self.gate.requests >= max_requests:
                    break
                if client is None:
                    client = self._get_client(conn)
                if not st["history_done"]:
                    if not self._backfill_page(conn, client, st, stats):
                        break
                else:
                    ids = repo.stale_orders(conn, 1, {k for k, v in self._detail_failures(conn).items()
                                                      if v >= MAX_DETAIL_FAILURES})
                    if not ids:
                        st["status"] = "done"
                        repo.set_state(conn, "backfill", st)
                        repo.set_state(conn, "last_backfill_done", self._now().isoformat(timespec="seconds"))
                        break
                    self._fetch_detail(conn, client, ids[0], stats)
            return stats
        except SyncAbort as e:
            return {**stats, "aborted": str(e)}
        except Stopped:
            return {**stats, "aborted": "stopped"}
        finally:
            self.current_job = None
            conn.close()
            self._after()

    def _backfill_page(self, conn, client, st: dict[str, Any], stats: dict[str, int]) -> bool:
        kw: dict[str, Any] = {"limit": 1}
        if st["cursor"]:
            kw["cursor"] = st["cursor"]
        else:
            kw["year"] = st["year"]
        try:
            page = self._request(conn, client.get_orders_page, **kw)
        except ItemError:
            stats["errors"] += 1
            return False
        for order in page.items:
            if self.stop.is_set() or not backfill_window_open(self.preset, self._now()):
                return False  # page is reprocessed next time (idempotent)
            if repo.get_state(conn, "backfill", {}).get("status") != "running":
                return False
            self._ingest(conn, client, order, stats)
        st["processed"] += len(page.items)
        st["year_orders"] += len(page.items)
        if page.cursor and page.items:
            st["cursor"] = page.cursor
        else:
            self._finish_year(st)
        repo.set_state(conn, "backfill", st)
        return True

    # --- purge ---

    def purge(self, scope: str) -> int:
        conn = self._conn()
        try:
            n = repo.purge(conn, scope)
            st = self.backfill_state(conn)
            if st["status"] == "done" and n:
                st["status"] = "running"  # stale-detail phase picks the rows up again
                st["history_done"] = True
                repo.set_state(conn, "backfill", st)
            return n
        finally:
            conn.close()

    # --- scheduling ---

    def request_recent(self) -> None:
        conn = self._conn()
        try:
            repo.set_state(conn, "recent_requested", True)
            repo.set_state(conn, "auth_required", False)
        finally:
            conn.close()

    def recent_due(self, conn) -> bool:
        if repo.get_state(conn, "recent_requested"):
            return True
        last = repo.get_state(conn, "last_recent")
        if not last:
            return True
        return self._now() >= datetime.fromisoformat(last["at"]) + timedelta(hours=self.options.recent_refresh_hours)

    def tick(self) -> str | None:
        """One scheduler decision. Returns the job that ran, if any."""
        with self._lock:
            conn = self._conn()
            try:
                popped = getattr(self.auth, "pop_login_completed", None)
                if popped is not None and popped():
                    # A sign-in just finished: lift the auth_required stop and refresh now.
                    repo.set_state(conn, "auth_required", False)
                    repo.set_state(conn, "recent_requested", True)
                if self.auth.status().get("state") == "in_progress":
                    return None
                if self.can_run(conn):
                    return None
                try:
                    self.auth.get_session()
                except AuthRequired:
                    self._require_auth(conn, "no valid session")
                    return None
                except AuthTemporarilyUnavailable:
                    log.warning("cookie renewal unavailable; will retry")
                    return None
                except Exception:
                    log.exception("auth provider failed")
                    return None
                if self.recent_due(conn):
                    repo.set_state(conn, "recent_requested", False)
                    conn.close()
                    self.run_recent()
                    return "recent"
                bf = self.backfill_state(conn)
                if bf["status"] == "running" and backfill_window_open(self.preset, self._now()):
                    conn.close()
                    self.run_backfill()
                    return "backfill"
                return None
            finally:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # ------------------------------------------------------------------ status

    def status(self) -> dict[str, Any]:
        conn = self._conn()
        try:
            now = self._now()
            auth_flag = bool(repo.get_state(conn, "auth_required"))
            auth = dict(self.auth.status())
            if auth_flag and auth.get("state") == "ok":
                auth["state"] = "auth_required"
            cd = Cooldown(repo.get_state(conn, "cooldown"))
            bf = self.backfill_state(conn)
            counts = repo.counts(conn)
            window = backfill_window_open(self.preset, now)
            nxt = next_window_start(self.preset, now)
            last_recent = repo.get_state(conn, "last_recent")
            last_error = repo.get_state(conn, "last_error")
            if auth["state"] == "auth_required":
                state = "auth_required"
            elif cd.active(now):
                state = "cooldown"
            elif self.current_job == "recent":
                state = "syncing"
            elif self.current_job == "backfill":
                state = "backfilling"
            elif last_error and last_error.get("code") not in ("cooldown", "auth_required") and \
                    repo.get_state(conn, "last_recent") is None:
                state = "error"
            else:
                state = "idle"
            until = self.options.backfill_until_year
            if bf["status"] == "done":
                pct: float | None = 100.0
            elif until:
                span = bf["start_year"] - until + 1
                pct = round(min(100.0, max(0.0, (bf["start_year"] - bf["year"]) / span * 100)), 1) \
                    if not bf["history_done"] else None
            else:
                pct = None
            return {
                "state": state,
                "auth": auth,
                "job": self.current_job,
                "preset": self.preset.name,
                "backfill": {
                    "status": bf["status"], "year": bf["year"], "processed": bf["processed"],
                    "history_done": bf["history_done"], "percent": pct,
                    "window_open": window, "next_window": nxt.isoformat(timespec="minutes") if nxt else None,
                    "until_year": until,
                    "orders_detailed": counts["orders_detailed"], "orders_stale": counts["orders_stale"],
                },
                "cooldown": {**cd.data} if cd.active(now) else None,
                "last_error": last_error,
                "last_recent": last_recent,
                "next_recent_at": None if not last_recent else (
                    datetime.fromisoformat(last_recent["at"])
                    + timedelta(hours=self.options.recent_refresh_hours)).isoformat(timespec="seconds"),
                "counts": counts,
                "today": date.today().isoformat(),
            }
        finally:
            conn.close()
