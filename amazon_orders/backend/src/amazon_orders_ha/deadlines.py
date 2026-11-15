"""Deadline computation (SPEC §7) and threshold event evaluation with dedup."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from .util import add_months, parse_iso, ts

UNKNOWN_CLOSED_AFTER_DAYS = 90


def _deadline(kind: str, d: date | None, today: date, state: str, source: str | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "deadline": d.isoformat() if d else None,
        "days_left": (d - today).days if d else None,
        "state": state,  # open | closed | unknown | none
        "source": source,  # amazon | override | computed | None
    }


def compute_deadlines(
    row: Mapping[str, Any], today: date, default_warranty_months: int = 24
) -> dict[str, dict[str, Any]]:
    """Return ``{"return": {...}, "warranty": {...}}`` for an item row.

    ``row`` needs: return_eligible_date, delivered_date, placed_date, cancelled,
    status (item_state), warranty_until_override, warranty_months_override.
    Dates may be ISO strings or ``date``.
    """

    row = dict(row)

    def d(key: str) -> date | None:
        v = row.get(key)
        return v if isinstance(v, date) else parse_iso(v)

    status = row.get("status") or "none"
    placed = d("placed_date")
    inactive = bool(row.get("cancelled")) or status == "returned"
    if inactive:
        return {
            "return": _deadline("return", None, today, "none", None),
            "warranty": _deadline("warranty", None, today, "none", None),
        }

    # Return deadline: Amazon's date only. status 'keep' = user decided to keep it.
    ret_date = d("return_eligible_date")
    if status == "keep":
        ret = _deadline("return", ret_date, today, "none", "amazon" if ret_date else None)
    elif ret_date:
        ret = _deadline("return", ret_date, today, "open" if ret_date >= today else "closed", "amazon")
    else:
        old = placed is not None and (today - placed).days > UNKNOWN_CLOSED_AFTER_DAYS
        ret = _deadline("return", None, today, "closed" if old else "unknown", None)

    # Warranty deadline
    override = d("warranty_until_override")
    if override:
        w_date, src = override, "override"
    else:
        start = d("delivered_date") or placed
        months = row.get("warranty_months_override") or default_warranty_months
        w_date = add_months(start, int(months)) if start else None
        src = "computed" if w_date else None
    if w_date:
        war = _deadline("warranty", w_date, today, "open" if w_date >= today else "closed", src)
    else:
        war = _deadline("warranty", None, today, "unknown", None)
    return {"return": ret, "warranty": war}


EventSender = Callable[[str, dict[str, Any]], bool]

ITEM_QUERY = """
SELECT i.*, o.placed_date, o.cancelled, o.details_link,
       COALESCE(s.status,'none') AS status, s.warranty_until_override, s.warranty_months_override
FROM items i JOIN orders o ON o.order_number = i.order_number
LEFT JOIN item_state s ON s.item_id = i.id
"""


def _abs_url(domain: str, link: str | None) -> str | None:
    if not link:
        return None
    return link if link.startswith("http") else f"https://www.{domain}{link if link.startswith('/') else '/' + link}"


def event_payload(row: Mapping[str, Any], dl: Mapping[str, Any], threshold: int, domain: str) -> dict[str, Any]:
    return {
        "kind": dl["kind"],
        "threshold_days": threshold,
        "days_left": dl["days_left"],
        "deadline": dl["deadline"],
        "order_number": row["order_number"],
        "item_id": row["id"],
        "title": row["title"],
        "asin": row["asin"],
        "price": row["price"],
        "seller": row["seller"],
        "item_url": _abs_url(domain, row["link"]),
        "order_url": _abs_url(domain, row["details_link"]),
    }


def evaluate_events(
    conn: sqlite3.Connection,
    today: date,
    now: datetime,
    return_thresholds: list[int],
    warranty_thresholds: list[int],
    send: EventSender,
    default_warranty_months: int = 24,
    domain: str = "amazon.it",
) -> list[dict[str, Any]]:
    """Fire ``amazon_orders_deadline`` once per (item, kind, threshold, deadline).

    For each open deadline the tightest crossed threshold (``days_left <= t``)
    is sent; larger crossed thresholds are recorded as already handled so a late
    discovery (e.g. after backfill) does not produce a burst of stale events.
    Rows are recorded only when ``send`` returns True, so failures are retried.
    """
    fired: list[dict[str, Any]] = []
    cfg = {"return": sorted(return_thresholds), "warranty": sorted(warranty_thresholds)}
    for r in conn.execute(ITEM_QUERY).fetchall():
        row = dict(r)
        dls = compute_deadlines(row, today, default_warranty_months)
        for kind, dl in dls.items():
            if dl["state"] != "open":
                continue
            crossed = [t for t in cfg[kind] if dl["days_left"] <= t]
            if not crossed:
                continue
            tight = crossed[0]  # ascending -> smallest crossed
            already = {
                r["threshold_days"]
                for r in conn.execute(
                    "SELECT threshold_days FROM fired_events WHERE item_id=? AND kind=? AND deadline=?",
                    (row["id"], kind, dl["deadline"]),
                )
            }
            if tight in already:
                continue
            payload = event_payload(row, dl, tight, domain)
            if not send("amazon_orders_deadline", payload):
                continue
            for t in crossed:  # mark the tight one and all looser ones as handled
                conn.execute(
                    "INSERT OR IGNORE INTO fired_events(item_id, kind, threshold_days, deadline, fired_at)"
                    " VALUES (?,?,?,?,?)",
                    (row["id"], kind, t, dl["deadline"], ts(now)),
                )
            fired.append(payload)
    return fired
