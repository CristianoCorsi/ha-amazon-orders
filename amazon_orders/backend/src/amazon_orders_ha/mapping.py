"""Mapping from amazon-orders entities to database rows (SPEC §4, §6)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january", "gennaio", "gen"),
            ("feb", "february", "febbraio"),
            ("mar", "march", "marzo"),
            ("apr", "april", "aprile"),
            ("may", "maggio", "mag"),
            ("jun", "june", "giugno", "giu"),
            ("jul", "july", "luglio", "lug"),
            ("aug", "august", "agosto", "ago"),
            ("sep", "sept", "september", "settembre", "set"),
            ("oct", "october", "ottobre", "ott"),
            ("nov", "november", "novembre"),
            ("dec", "december", "dicembre", "dic"),
        ],
        start=1,
    )
    for m in names
}

_DAY_MONTH = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z\u00c0-\u017f]+)\.?(?:,?\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?")


def parse_delivery_status(
    text: str | None, placed: date | None, today: date | None = None
) -> tuple[str, date | None]:
    """Parse strings like ``Delivered 28 October``.

    Returns ``(kind, date)`` with kind in ``delivered`` | ``pending`` | ``unknown``.
    The year is inferred from the order placed date: the delivery is the first
    occurrence of that day/month on or after ``placed``. A date is only returned
    for delivered shipments.
    """
    if not text:
        return "unknown", None
    low = text.strip().lower()
    delivered = low.startswith("delivered") or "consegnat" in low
    kind = "delivered" if delivered else "pending"
    today = today or date.today()
    if delivered and "yesterday" in low:
        return kind, today - timedelta(days=1)
    if delivered and "today" in low:
        return kind, today
    d = _extract_date(text, placed)
    if d is None:
        return kind, None
    return kind, (d if delivered else None)


def _extract_date(text: str, placed: date | None) -> date | None:
    for rx, order in ((_DAY_MONTH, "dm"), (_MONTH_DAY, "md")):
        for m in rx.finditer(text):
            a, b, y = m.group(1), m.group(2), m.group(3)
            day_s, mon_s = (a, b) if order == "dm" else (b, a)
            mon = MONTHS.get(mon_s.lower())
            if not mon or not day_s.isdigit():
                continue
            day = int(day_s)
            if y:
                try:
                    return date(int(y), mon, day)
                except ValueError:
                    continue
            return _infer_year(day, mon, placed)
    return None


def _infer_year(day: int, mon: int, placed: date | None) -> date | None:
    base = placed.year if placed else date.today().year
    for year in (base, base + 1, base + 2):
        try:
            d = date(year, mon, day)
        except ValueError:  # 29 Feb in a non-leap year
            continue
        if placed is None or d >= placed:
            return d
    return None


def _plain(v: Any) -> Any:
    """Serialize an entity to JSON-able primitives, skipping parser internals."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if hasattr(v, "__dict__") and not isinstance(v, type):
        return {
            k: _plain(x)
            for k, x in vars(v).items()
            if k not in ("parsed", "config", "parse_failures") and not k.startswith("_") and x is not None
        }
    return v


_DROP_KEYS = {"recipient", "payment_method_last_4"}
_DIGITS = re.compile(r"\d{2,}")


def sanitize_raw(order: Any) -> dict[str, Any]:
    """Raw order data without recipient name/address and card digits."""
    data = _plain(order)

    def scrub(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: scrub(v) for k, v in o.items() if k not in _DROP_KEYS}
        if isinstance(o, list):
            return [scrub(x) for x in o]
        return o

    data = scrub(data)
    if isinstance(data.get("payment_method"), str):
        data["payment_method"] = _DIGITS.sub("", data["payment_method"]).strip(" *.-")
    return data


@dataclass
class ItemRow:
    item_key: str
    asin: str | None
    title: str
    price: float | None
    quantity: int | None
    seller: str | None
    image_link: str | None
    link: str | None
    return_eligible_date: date | None
    delivered_date: date | None
    shipment_key: str | None = None


@dataclass
class ShipmentRow:
    shipment_key: str
    status_text: str | None
    delivered_date: date | None
    tracking_link: str | None


@dataclass
class OrderRow:
    order_number: str
    placed_date: date | None
    grand_total: float | None
    subtotal: float | None
    shipping_total: float | None
    estimated_tax: float | None
    refund_total: float | None
    gift_card: float | None
    coupon_savings: float | None
    cancelled: bool
    payment_method: str | None
    details_link: str | None
    fingerprint: str
    detailed: bool
    raw: dict[str, Any]
    shipments: list[ShipmentRow] = field(default_factory=list)
    items: list[ItemRow] = field(default_factory=list)


def _abs(v: Any) -> float | None:
    return abs(float(v)) if isinstance(v, (int, float)) else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _seller_name(s: Any) -> str | None:
    if s is None:
        return None
    name = getattr(s, "name", s)
    return str(name).strip() or None if name is not None else None


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def fingerprint(order: Any) -> str:
    """List-level fingerprint: status text, totals, item count (SPEC §5)."""
    statuses = [
        getattr(s, "delivery_status", None) or "" for s in (getattr(order, "shipments", None) or [])
    ]
    parts = [
        "|".join(statuses),
        str(getattr(order, "grand_total", None)),
        str(len(getattr(order, "items", None) or [])),
        str(bool(getattr(order, "cancelled", False))),
    ]
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]


def map_order(order: Any, detailed: bool, today: date | None = None) -> OrderRow:
    placed = _as_date(getattr(order, "order_placed_date", None))
    number = getattr(order, "order_number", None)
    if not number:
        raise ValueError("order without order_number")
    row = OrderRow(
        order_number=str(number),
        placed_date=placed,
        grand_total=_num(getattr(order, "grand_total", None)),
        subtotal=_num(getattr(order, "subtotal", None)),
        shipping_total=_num(getattr(order, "shipping_total", None)),
        estimated_tax=_num(getattr(order, "estimated_tax", None)),
        refund_total=_abs(getattr(order, "refund_total", None)),
        gift_card=_abs(getattr(order, "gift_card", None)),
        coupon_savings=_abs(getattr(order, "coupon_savings", None)),
        cancelled=bool(getattr(order, "cancelled", False)),
        payment_method=None,
        details_link=getattr(order, "order_details_link", None),
        fingerprint=fingerprint(order),
        detailed=detailed,
        raw=sanitize_raw(order),
    )
    pm = getattr(order, "payment_method", None)
    if isinstance(pm, str):
        row.payment_method = _DIGITS.sub("", pm).strip(" *.-") or None

    seen: set[int] = set()
    counts: dict[str, int] = {}

    def add_item(it: Any, ship_key: str | None, delivered: date | None) -> None:
        if id(it) in seen:
            return
        seen.add(id(it))
        title = getattr(it, "title", None) or "(untitled)"
        asin = getattr(it, "asin", None)
        base = asin or title
        n = counts.get(base, 0)
        counts[base] = n + 1
        row.items.append(
            ItemRow(
                item_key=f"{base}#{n}",
                asin=asin,
                title=str(title),
                price=_num(getattr(it, "price", None)),
                quantity=getattr(it, "quantity", None),
                seller=_seller_name(getattr(it, "seller", None)),
                image_link=getattr(it, "image_link", None),
                link=getattr(it, "link", None),
                return_eligible_date=_as_date(getattr(it, "return_eligible_date", None)),
                delivered_date=delivered,
                shipment_key=ship_key,
            )
        )

    for idx, sh in enumerate(getattr(order, "shipments", None) or []):
        key = getattr(sh, "shipment_id", None) or f"s{idx}"
        text = getattr(sh, "delivery_status", None)
        kind, ddate = parse_delivery_status(text, placed, today)
        row.shipments.append(ShipmentRow(str(key), text, ddate, getattr(sh, "tracking_link", None)))
        for it in getattr(sh, "items", None) or []:
            add_item(it, str(key), ddate)
    for it in getattr(order, "items", None) or []:
        add_item(it, None, None)
    return row


def raw_dumps(raw: dict[str, Any]) -> str:
    return json.dumps(raw, ensure_ascii=False, default=str)
