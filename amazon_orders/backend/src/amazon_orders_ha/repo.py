"""Repository layer: all SQL lives here."""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .deadlines import _abs_url, compute_deadlines
from .mapping import ItemRow, OrderRow, raw_dumps
from .util import iso, ts

CURRENCY = "EUR"
STATUSES = ("none", "keep", "to_return", "returned")
DEFAULT_STATE = {
    "status": "none",
    "note": "",
    "warranty_until_override": None,
    "warranty_months_override": None,
}


# --------------------------------------------------------------------------- sync_state


def get_state(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    if not row or row["value"] is None:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def set_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO sync_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


# --------------------------------------------------------------------------- upsert


def get_order_meta(conn: sqlite3.Connection, order_number: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT order_number, list_fingerprint, details_fetched_at, placed_date FROM orders WHERE order_number=?",
        (order_number,),
    ).fetchone()


def upsert_order(conn: sqlite3.Connection, o: OrderRow, now: datetime) -> bool:
    """Insert/update one order with its shipments and items. Returns True if the row is new.

    List-level data (``o.detailed`` False) never erases values found by a detail fetch.
    Local annotations (item_state) are never touched.
    """
    n = ts(now)
    old = conn.execute("SELECT * FROM orders WHERE order_number=?", (o.order_number,)).fetchone()
    cols = ["grand_total", "subtotal", "shipping_total", "estimated_tax", "refund_total", "gift_card",
            "coupon_savings", "payment_method"]
    raw = raw_dumps(o.raw)
    conn.execute("BEGIN")
    try:
        if old is None:
            conn.execute(
                "INSERT INTO orders(order_number, placed_date, grand_total, subtotal, shipping_total,"
                " estimated_tax, refund_total, gift_card, coupon_savings, cancelled, payment_method,"
                " details_link, list_fingerprint, details_fetched_at, first_seen_at, updated_at, raw_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (o.order_number, iso(o.placed_date), o.grand_total, o.subtotal, o.shipping_total,
                 o.estimated_tax, o.refund_total, o.gift_card, o.coupon_savings, int(o.cancelled),
                 o.payment_method, o.details_link, o.fingerprint, n if o.detailed else None, n, n, raw),
            )
        else:
            vals: dict[str, Any] = {}
            for c in cols:
                new = getattr(o, c)
                vals[c] = new if (o.detailed or new is not None) else old[c]
            vals["grand_total"] = o.grand_total if o.grand_total is not None else old["grand_total"]
            vals["placed_date"] = iso(o.placed_date) or old["placed_date"]
            vals["details_link"] = o.details_link or old["details_link"]
            vals["cancelled"] = int(o.cancelled or (old["cancelled"] and not o.detailed))
            vals["updated_at"] = n
            vals["raw_json"] = raw if (o.detailed or not old["raw_json"]) else old["raw_json"]
            if o.detailed:
                vals["details_fetched_at"] = n
            else:
                vals["list_fingerprint"] = o.fingerprint
            sets = ", ".join(f"{k}=?" for k in vals)
            conn.execute(f"UPDATE orders SET {sets} WHERE order_number=?", (*vals.values(), o.order_number))
        _upsert_shipments(conn, o)
        _upsert_items(conn, o)
        _reindex(conn, o.order_number)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return old is None


def _upsert_shipments(conn: sqlite3.Connection, o: OrderRow) -> None:
    keys = []
    for s in o.shipments:
        keys.append(s.shipment_key)
        conn.execute(
            "INSERT INTO shipments(order_number, shipment_key, status_text, delivered_date, tracking_link)"
            " VALUES (?,?,?,?,?) ON CONFLICT(order_number, shipment_key) DO UPDATE SET"
            " status_text=excluded.status_text,"
            " delivered_date=COALESCE(excluded.delivered_date, shipments.delivered_date),"
            " tracking_link=COALESCE(excluded.tracking_link, shipments.tracking_link)",
            (o.order_number, s.shipment_key, s.status_text, iso(s.delivered_date), s.tracking_link),
        )
    if keys:
        q = ",".join("?" * len(keys))
        conn.execute(
            f"DELETE FROM shipments WHERE order_number=? AND shipment_key NOT IN ({q})",
            (o.order_number, *keys),
        )


def _upsert_items(conn: sqlite3.Connection, o: OrderRow) -> None:
    keys = []
    for it in o.items:
        keys.append(it.item_key)
        _upsert_item(conn, o.order_number, it)
    if keys:
        q = ",".join("?" * len(keys))
        # Keep annotated items even if the parser no longer reports them.
        conn.execute(
            f"DELETE FROM items WHERE order_number=? AND item_key NOT IN ({q})"
            " AND id NOT IN (SELECT item_id FROM item_state)",
            (o.order_number, *keys),
        )


def _upsert_item(conn: sqlite3.Connection, order_number: str, it: ItemRow) -> None:
    conn.execute(
        "INSERT INTO items(order_number, item_key, asin, title, price, quantity, seller, image_link, link,"
        " return_eligible_date, delivered_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(order_number, item_key) DO UPDATE SET"
        " asin=COALESCE(excluded.asin, items.asin), title=excluded.title,"
        " price=COALESCE(excluded.price, items.price), quantity=COALESCE(excluded.quantity, items.quantity),"
        " seller=COALESCE(excluded.seller, items.seller),"
        " image_link=COALESCE(excluded.image_link, items.image_link), link=COALESCE(excluded.link, items.link),"
        " return_eligible_date=COALESCE(excluded.return_eligible_date, items.return_eligible_date),"
        " delivered_date=COALESCE(excluded.delivered_date, items.delivered_date)",
        (order_number, it.item_key, it.asin, it.title, it.price, it.quantity, it.seller, it.image_link,
         it.link, iso(it.return_eligible_date), iso(it.delivered_date)),
    )


def _reindex(conn: sqlite3.Connection, order_number: str) -> None:
    conn.execute("DELETE FROM search_fts WHERE order_number=?", (order_number,))
    rows = conn.execute("SELECT id, title, seller FROM items WHERE order_number=?", (order_number,)).fetchall()
    if not rows:
        conn.execute(
            "INSERT INTO search_fts(order_number, title, seller, item_id) VALUES (?,?,?,0)",
            (order_number, "", ""),
        )
    for r in rows:
        conn.execute(
            "INSERT INTO search_fts(order_number, title, seller, item_id) VALUES (?,?,?,?)",
            (order_number, r["title"], r["seller"] or "", r["id"]),
        )


# --------------------------------------------------------------------------- purge


def purge(conn: sqlite3.Connection, scope: str) -> int:
    """Mark rows stale so jobs refetch them. Never touches item_state/fired_events."""
    if scope == "all":
        where, args = "1=1", ()
    elif re.fullmatch(r"year:\d{4}", scope):
        where, args = "strftime('%Y', placed_date)=?", (scope[5:],)
    elif scope.startswith("order:") and len(scope) > 6:
        where, args = "order_number=?", (scope[6:],)
    else:
        raise ValueError(f"invalid scope: {scope}")
    cur = conn.execute(
        f"UPDATE orders SET details_fetched_at=NULL, list_fingerprint=NULL WHERE {where}", args
    )
    set_state(conn, "detail_failures", {})
    return cur.rowcount


# --------------------------------------------------------------------------- filters


def fts_query(q: str) -> str | None:
    toks = re.findall(r"\w+", q or "", flags=re.UNICODE)
    return " ".join(f'"{t}"*' for t in toks) if toks else None


@dataclass
class Filters:
    q: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    seller: str | None = None
    status: str | None = None
    min: float | None = None
    max: float | None = None
    sort: str = "date_desc"
    page: int = 1
    page_size: int = 50


def _item_where(f: Filters) -> tuple[str, list[Any]]:
    w, a = ["1=1"], []
    fq = fts_query(f.q) if f.q else None
    if f.q and not fq:
        w.append("0")
    if fq:
        w.append("i.id IN (SELECT item_id FROM search_fts WHERE search_fts MATCH ?)")
        a.append(fq)
    if f.date_from:
        w.append("o.placed_date >= ?")
        a.append(f.date_from)
    if f.date_to:
        w.append("o.placed_date <= ?")
        a.append(f.date_to)
    if f.seller:
        w.append("LOWER(i.seller) = LOWER(?)")
        a.append(f.seller)
    if f.status:
        if f.status == "cancelled":
            w.append("o.cancelled = 1")
        else:
            w.append("COALESCE(s.status,'none') = ?")
            a.append(f.status)
    if f.min is not None:
        w.append("i.price >= ?")
        a.append(f.min)
    if f.max is not None:
        w.append("i.price <= ?")
        a.append(f.max)
    return " AND ".join(w), a


_ITEM_SORT = {
    "date_desc": "o.placed_date DESC, i.id DESC",
    "date_asc": "o.placed_date ASC, i.id ASC",
    "total_desc": "i.price DESC, i.id DESC",
    "total_asc": "i.price ASC, i.id ASC",
    "price_desc": "i.price DESC, i.id DESC",
    "price_asc": "i.price ASC, i.id ASC",
    "title_asc": "LOWER(i.title) ASC, i.id ASC",
}
_ORDER_SORT = {
    "date_desc": "o.placed_date DESC, o.order_number DESC",
    "date_asc": "o.placed_date ASC, o.order_number ASC",
    "total_desc": "o.grand_total DESC, o.order_number DESC",
    "total_asc": "o.grand_total ASC, o.order_number ASC",
    "price_desc": "o.grand_total DESC, o.order_number DESC",
    "price_asc": "o.grand_total ASC, o.order_number ASC",
}


def _item_json(r: sqlite3.Row | dict, today: date, months: int) -> dict[str, Any]:
    r = dict(r)
    return {
        "id": r["id"],
        "order_number": r["order_number"],
        "asin": r["asin"],
        "title": r["title"],
        "price": r["price"],
        "quantity": r["quantity"],
        "seller": r["seller"],
        "image_link": r["image_link"],
        "link": r["link"],
        "return_eligible_date": r["return_eligible_date"],
        "delivered_date": r["delivered_date"],
        "state": {
            "status": r["status"],
            "note": r["note"] or "",
            "warranty_until_override": r["warranty_until_override"],
            "warranty_months_override": r["warranty_months_override"],
        },
        "deadlines": compute_deadlines(r, today, months),
        "order": {
            "order_number": r["order_number"],
            "placed_date": r["placed_date"],
            "cancelled": bool(r["cancelled"]),
            "details_link": r["details_link"],
        },
    }


_ITEM_SELECT = (
    "SELECT i.*, o.placed_date, o.cancelled, o.details_link, COALESCE(s.status,'none') AS status,"
    " s.note, s.warranty_until_override, s.warranty_months_override"
    " FROM items i JOIN orders o ON o.order_number=i.order_number"
    " LEFT JOIN item_state s ON s.item_id=i.id"
)


def list_items(conn, f: Filters, today: date, months: int = 24) -> dict[str, Any]:
    where, args = _item_where(f)
    total = conn.execute(
        f"SELECT COUNT(*) c FROM items i JOIN orders o ON o.order_number=i.order_number"
        f" LEFT JOIN item_state s ON s.item_id=i.id WHERE {where}", args).fetchone()["c"]
    order = _ITEM_SORT.get(f.sort, _ITEM_SORT["date_desc"])
    rows = conn.execute(
        f"{_ITEM_SELECT} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*args, f.page_size, (f.page - 1) * f.page_size),
    ).fetchall()
    return {
        "items": [_item_json(r, today, months) for r in rows],
        "total": total,
        "page": f.page,
        "page_size": f.page_size,
        "currency": CURRENCY,
    }


def _order_where(f: Filters) -> tuple[str, list[Any]]:
    w, a = ["1=1"], []
    fq = fts_query(f.q) if f.q else None
    if f.q and not fq:
        w.append("0")
    if fq:
        w.append("o.order_number IN (SELECT order_number FROM search_fts WHERE search_fts MATCH ?)")
        a.append(fq)
    if f.date_from:
        w.append("o.placed_date >= ?")
        a.append(f.date_from)
    if f.date_to:
        w.append("o.placed_date <= ?")
        a.append(f.date_to)
    if f.seller:
        w.append("EXISTS (SELECT 1 FROM items x WHERE x.order_number=o.order_number AND LOWER(x.seller)=LOWER(?))")
        a.append(f.seller)
    if f.status:
        if f.status == "cancelled":
            w.append("o.cancelled = 1")
        else:
            w.append(
                "EXISTS (SELECT 1 FROM items x LEFT JOIN item_state st ON st.item_id=x.id"
                " WHERE x.order_number=o.order_number AND COALESCE(st.status,'none')=?)"
            )
            a.append(f.status)
    if f.min is not None:
        w.append("o.grand_total >= ?")
        a.append(f.min)
    if f.max is not None:
        w.append("o.grand_total <= ?")
        a.append(f.max)
    return " AND ".join(w), a


def order_status(cancelled: bool, shipments: list[sqlite3.Row | dict]) -> str:
    if cancelled:
        return "cancelled"
    if shipments and all(s["delivered_date"] for s in shipments):
        return "delivered"
    if shipments:
        return "in_progress"
    return "unknown"


def list_orders(conn, f: Filters) -> dict[str, Any]:
    where, args = _order_where(f)
    total = conn.execute(f"SELECT COUNT(*) c FROM orders o WHERE {where}", args).fetchone()["c"]
    order = _ORDER_SORT.get(f.sort, _ORDER_SORT["date_desc"])
    rows = conn.execute(
        f"SELECT o.order_number, o.placed_date, o.grand_total, o.cancelled, o.refund_total, o.details_link,"
        f" o.details_fetched_at FROM orders o WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*args, f.page_size, (f.page - 1) * f.page_size),
    ).fetchall()
    out = []
    for r in rows:
        items = conn.execute(
            "SELECT i.id, i.title, i.asin, i.price, i.image_link, i.seller, COALESCE(s.status,'none') AS status"
            " FROM items i LEFT JOIN item_state s ON s.item_id=i.id WHERE i.order_number=? ORDER BY i.id",
            (r["order_number"],),
        ).fetchall()
        ships = conn.execute(
            "SELECT delivered_date FROM shipments WHERE order_number=?", (r["order_number"],)
        ).fetchall()
        out.append({
            "order_number": r["order_number"],
            "placed_date": r["placed_date"],
            "grand_total": r["grand_total"],
            "refund_total": r["refund_total"],
            "cancelled": bool(r["cancelled"]),
            "status": order_status(bool(r["cancelled"]), ships),
            "details_link": r["details_link"],
            "has_details": r["details_fetched_at"] is not None,
            "item_count": len(items),
            "items": [dict(i) for i in items],
        })
    return {"orders": out, "total": total, "page": f.page, "page_size": f.page_size, "currency": CURRENCY}


def get_order(conn, order_number: str, today: date, months: int = 24) -> dict[str, Any] | None:
    o = conn.execute("SELECT * FROM orders WHERE order_number=?", (order_number,)).fetchone()
    if not o:
        return None
    ships = conn.execute(
        "SELECT shipment_key, status_text, delivered_date, tracking_link FROM shipments WHERE order_number=?"
        " ORDER BY id", (order_number,)).fetchall()
    items = conn.execute(f"{_ITEM_SELECT} WHERE i.order_number=? ORDER BY i.id", (order_number,)).fetchall()
    d = {k: o[k] for k in o.keys() if k != "raw_json"}
    d["cancelled"] = bool(d["cancelled"])
    d["status"] = order_status(d["cancelled"], ships)
    return {
        "order": d,
        "shipments": [dict(s) for s in ships],
        "items": [_item_json(i, today, months) for i in items],
        "currency": CURRENCY,
    }


def get_item(conn, item_id: int, today: date, months: int = 24) -> dict[str, Any] | None:
    r = conn.execute(f"{_ITEM_SELECT} WHERE i.id=?", (item_id,)).fetchone()
    return _item_json(r, today, months) if r else None


def patch_item_state(conn, item_id: int, changes: dict[str, Any], now: datetime) -> bool:
    if not conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
        return False
    cur = conn.execute("SELECT * FROM item_state WHERE item_id=?", (item_id,)).fetchone()
    state = dict(DEFAULT_STATE)
    if cur:
        state.update({k: cur[k] for k in DEFAULT_STATE})
    state.update(changes)
    conn.execute(
        "INSERT INTO item_state(item_id, status, note, warranty_until_override, warranty_months_override,"
        " updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET status=excluded.status,"
        " note=excluded.note, warranty_until_override=excluded.warranty_until_override,"
        " warranty_months_override=excluded.warranty_months_override, updated_at=excluded.updated_at",
        (item_id, state["status"], state["note"], state["warranty_until_override"],
         state["warranty_months_override"], ts(now)),
    )
    return True


# --------------------------------------------------------------------------- deadlines


def list_deadlines(
    conn, today: date, kind: str = "all", within_days: int | None = None,
    include_closed: bool = False, months: int = 24,
) -> dict[str, Any]:
    out = []
    for r in conn.execute(f"{_ITEM_SELECT} ORDER BY i.id").fetchall():
        item = _item_json(r, today, months)
        for k, dl in item["deadlines"].items():
            if kind != "all" and k != kind:
                continue
            if dl["deadline"] is None or dl["state"] in ("none", "unknown"):
                continue
            if dl["state"] == "closed" and not include_closed:
                continue
            if within_days is not None and dl["state"] == "open" and dl["days_left"] > within_days:
                continue
            out.append({**dl, "item": {k2: item[k2] for k2 in
                        ("id", "title", "asin", "price", "seller", "image_link", "link", "order_number")},
                        "order": item["order"], "status": item["state"]["status"]})
    out.sort(key=lambda x: (x["deadline"], x["item"]["id"]))
    return {"deadlines": out, "total": len(out), "today": today.isoformat()}


# --------------------------------------------------------------------------- stats


def _year_clause(year: int | None, col: str = "o.placed_date") -> tuple[str, list[Any]]:
    return (f" AND strftime('%Y', {col}) = ?", [f"{year:04d}"]) if year else ("", [])


def stats_summary(conn, year: int | None) -> dict[str, Any]:
    yc, ya = _year_clause(year)
    r = conn.execute(
        "SELECT COUNT(*) AS orders, COALESCE(SUM(grand_total),0) AS spend,"
        " COALESCE(SUM(shipping_total),0) AS shipping, COALESCE(SUM(refund_total),0) AS refunds,"
        " COALESCE(SUM(gift_card),0) AS gift_card, COALESCE(SUM(coupon_savings),0) AS coupons"
        f" FROM orders o WHERE o.cancelled=0{yc}", ya).fetchone()
    cancelled = conn.execute(f"SELECT COUNT(*) c FROM orders o WHERE o.cancelled=1{yc}", ya).fetchone()["c"]
    items = conn.execute(
        f"SELECT COUNT(*) c FROM items i JOIN orders o ON o.order_number=i.order_number"
        f" WHERE o.cancelled=0{yc}", ya).fetchone()["c"]
    priced = conn.execute(
        f"SELECT COUNT(*) c FROM orders o WHERE o.cancelled=0 AND o.grand_total IS NOT NULL{yc}", ya
    ).fetchone()["c"]
    return {
        "year": year, "currency": CURRENCY,
        "spend": round(r["spend"], 2), "orders": r["orders"], "items": items,
        "avg_order": round(r["spend"] / priced, 2) if priced else 0,
        "shipping_paid": round(r["shipping"], 2), "refunds": round(r["refunds"], 2),
        "cancelled": cancelled, "gift_card_used": round(r["gift_card"], 2),
        "coupon_savings": round(r["coupons"], 2),
    }


def _month_of(s: str | None) -> str | None:
    return s[:7] if s else None


def stats_monthly(conn, date_from: str | None, date_to: str | None, today: date) -> dict[str, Any]:
    end = _month_of(date_to) or today.strftime("%Y-%m")
    if date_from:
        start = _month_of(date_from)
    else:
        y, m = int(end[:4]), int(end[5:7])
        total = y * 12 + (m - 1) - 35
        start = f"{total // 12:04d}-{total % 12 + 1:02d}"
    rows = {
        r["m"]: r
        for r in conn.execute(
            "SELECT strftime('%Y-%m', placed_date) AS m, COALESCE(SUM(grand_total),0) AS spend, COUNT(*) AS n"
            " FROM orders WHERE cancelled=0 AND placed_date IS NOT NULL GROUP BY m")
    }
    months, (y, m) = [], (int(start[:4]), int(start[5:7]))
    while f"{y:04d}-{m:02d}" <= end:
        key = f"{y:04d}-{m:02d}"
        r = rows.get(key)
        months.append({"month": key, "spend": round(r["spend"], 2) if r else 0, "orders": r["n"] if r else 0})
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return {"months": months, "currency": CURRENCY}


def stats_sellers(conn, year: int | None, limit: int) -> dict[str, Any]:
    yc, ya = _year_clause(year)
    rows = conn.execute(
        "SELECT COALESCE(i.seller,'(unknown)') AS seller, ROUND(COALESCE(SUM(i.price),0),2) AS spend,"
        " COUNT(*) AS items, COUNT(DISTINCT i.order_number) AS orders"
        f" FROM items i JOIN orders o ON o.order_number=i.order_number WHERE o.cancelled=0{yc}"
        " GROUP BY 1 ORDER BY spend DESC, items DESC LIMIT ?", (*ya, limit)).fetchall()
    return {"sellers": [dict(r) for r in rows], "currency": CURRENCY, "year": year}


def stats_top_items(conn, year: int | None, limit: int) -> dict[str, Any]:
    yc, ya = _year_clause(year)
    rows = conn.execute(
        "SELECT i.id, i.title, i.asin, i.price, i.seller, i.image_link, i.order_number, o.placed_date"
        f" FROM items i JOIN orders o ON o.order_number=i.order_number WHERE o.cancelled=0"
        f" AND i.price IS NOT NULL{yc} ORDER BY i.price DESC, i.id LIMIT ?", (*ya, limit)).fetchall()
    return {"items": [dict(r) for r in rows], "currency": CURRENCY, "year": year}


def stats_recurring(conn, limit: int) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT i.asin, COUNT(*) AS count, MIN(o.placed_date) AS first_date, MAX(o.placed_date) AS last_date,"
        " MIN(i.price) AS price_min, MAX(i.price) AS price_max,"
        " ROUND(SUM(COALESCE(i.price,0)),2) AS total_spent"
        " FROM items i JOIN orders o ON o.order_number=i.order_number"
        " WHERE o.cancelled=0 AND i.asin IS NOT NULL GROUP BY i.asin HAVING COUNT(*) > 1"
        " ORDER BY count DESC, last_date DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        last = conn.execute(
            "SELECT i.title, i.price, i.image_link FROM items i JOIN orders o ON o.order_number=i.order_number"
            " WHERE i.asin=? AND o.cancelled=0 ORDER BY o.placed_date DESC, i.id DESC LIMIT 1",
            (r["asin"],)).fetchone()
        out.append({**dict(r), "title": last["title"], "price_last": last["price"],
                    "image_link": last["image_link"]})
    return {"recurring": out, "currency": CURRENCY}


def stats_returns(conn, year: int | None) -> dict[str, Any]:
    yc, ya = _year_clause(year)
    r = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(i.price),0) AS amount FROM items i"
        " JOIN orders o ON o.order_number=i.order_number JOIN item_state s ON s.item_id=i.id"
        f" WHERE s.status='returned'{yc}", ya).fetchone()
    refunds = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(refund_total),0) amount FROM orders o WHERE refund_total > 0{yc}", ya
    ).fetchone()
    total_items = conn.execute(
        f"SELECT COUNT(*) c FROM items i JOIN orders o ON o.order_number=i.order_number"
        f" WHERE o.cancelled=0{yc}", ya).fetchone()["c"]
    to_return = conn.execute(
        "SELECT COUNT(*) c FROM items i JOIN orders o ON o.order_number=i.order_number"
        f" JOIN item_state s ON s.item_id=i.id WHERE s.status='to_return'{yc}", ya).fetchone()["c"]
    return {
        "year": year, "currency": CURRENCY,
        "returned_items": r["n"], "returned_amount": round(r["amount"], 2),
        "refund_orders": refunds["n"], "refund_amount": round(refunds["amount"], 2),
        "to_return_items": to_return, "items": total_items,
        "return_rate": round(r["n"] / total_items, 4) if total_items else 0,
    }


def stats_weekday(conn) -> dict[str, Any]:
    cells = conn.execute(
        "SELECT CAST(strftime('%w', placed_date) AS INT) AS dow, CAST(strftime('%m', placed_date) AS INT) AS month,"
        " COUNT(*) AS orders FROM orders WHERE cancelled=0 AND placed_date IS NOT NULL GROUP BY 1,2").fetchall()
    weekdays = [0] * 7  # Monday=0
    months = [0] * 12
    heat = []
    for c in cells:
        wd = (c["dow"] + 6) % 7
        weekdays[wd] += c["orders"]
        months[c["month"] - 1] += c["orders"]
        heat.append({"weekday": wd, "month": c["month"], "orders": c["orders"]})
    return {
        "weekdays": [{"weekday": i, "orders": n} for i, n in enumerate(weekdays)],
        "months": [{"month": i + 1, "orders": n} for i, n in enumerate(months)],
        "heatmap": sorted(heat, key=lambda x: (x["weekday"], x["month"])),
    }


# --------------------------------------------------------------------------- counts / export


def counts(conn) -> dict[str, Any]:
    r = conn.execute(
        "SELECT COUNT(*) AS orders, SUM(details_fetched_at IS NOT NULL) AS detailed,"
        " MIN(placed_date) AS oldest, MAX(placed_date) AS newest FROM orders").fetchone()
    items = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
    return {
        "orders": r["orders"], "orders_detailed": r["detailed"] or 0,
        "orders_stale": r["orders"] - (r["detailed"] or 0), "items": items,
        "oldest_order": r["oldest"], "newest_order": r["newest"],
    }


EXPORT_COLUMNS = [
    "order_number", "placed_date", "order_total", "cancelled", "item_id", "asin", "title", "quantity", "price",
    "seller", "delivered_date", "return_eligible_date", "return_deadline", "warranty_deadline", "status",
    "note", "item_url", "order_url",
]


def export_csv(conn, f: Filters, today: date, domain: str, months: int = 24) -> str:
    f = Filters(**{**f.__dict__, "page": 1, "page_size": 10**9})
    data = list_items(conn, f, today, months)["items"]
    totals = {r["order_number"]: r["grand_total"] for r in conn.execute("SELECT order_number, grand_total FROM orders")}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLUMNS)

    def safe(v: Any) -> Any:  # neutralise spreadsheet formula injection
        return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v

    for it in data:
        o = it["order"]
        w.writerow([safe(x) for x in [
            it["order_number"], o["placed_date"], totals.get(it["order_number"]), int(o["cancelled"]), it["id"],
            it["asin"], it["title"], it["quantity"], it["price"], it["seller"], it["delivered_date"],
            it["return_eligible_date"], it["deadlines"]["return"]["deadline"],
            it["deadlines"]["warranty"]["deadline"], it["state"]["status"], it["state"]["note"],
            _abs_url(domain, it["link"]), _abs_url(domain, o["details_link"]),
        ]])
    return buf.getvalue()


def stale_orders(conn, limit: int, skip: set[str]) -> list[str]:
    rows = conn.execute(
        "SELECT order_number FROM orders WHERE details_fetched_at IS NULL ORDER BY placed_date DESC LIMIT ?",
        (limit + len(skip),)).fetchall()
    return [r["order_number"] for r in rows if r["order_number"] not in skip][:limit]

