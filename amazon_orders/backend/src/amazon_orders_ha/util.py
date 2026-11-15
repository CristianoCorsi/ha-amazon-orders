"""Small shared helpers."""

from __future__ import annotations

from datetime import date, datetime

from dateutil.relativedelta import relativedelta


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def parse_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def add_months(d: date, months: int) -> date:
    return d + relativedelta(months=months)


def ts(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(sep=" ")
