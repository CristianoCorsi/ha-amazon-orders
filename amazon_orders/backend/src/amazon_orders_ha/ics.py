"""ICS calendar feed of return and warranty deadlines (SPEC §8.3)."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

from .deadlines import ITEM_QUERY, _abs_url, compute_deadlines


def _esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r", "").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    b = line.encode()
    if len(b) <= 75:
        return [line]
    out, cur = [], ""
    for ch in line:
        limit = 75 if not out else 74
        if len((cur + ch).encode()) > limit:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return [out[0]] + [" " + p for p in out[1:]]


def build_ics(conn, today: date, now: datetime | None = None, months: int = 24, domain: str = "amazon.it",
              closed_grace_days: int = 30) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ha-amazon-orders//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Amazon Orders", "REFRESH-INTERVAL;VALUE=DURATION:PT6H"]
    for r in conn.execute(ITEM_QUERY + " ORDER BY i.id").fetchall():
        row = dict(r)
        dls = compute_deadlines(row, today, months)
        for kind, dl in dls.items():
            if not dl["deadline"] or dl["state"] in ("none", "unknown"):
                continue
            if dl["days_left"] < -closed_grace_days:
                continue
            d = date.fromisoformat(dl["deadline"])
            label = "Return deadline" if kind == "return" else "Warranty expires"
            title = row["title"]
            desc = [title, f"Order {row['order_number']}"]
            for u in (_abs_url(domain, row["details_link"]), _abs_url(domain, row["link"])):
                if u:
                    desc.append(u)
            uid = hashlib.sha1(f"{row['id']}-{kind}".encode()).hexdigest()[:20]
            ev = [
                "BEGIN:VEVENT",
                f"UID:{uid}-{kind}@amazon-orders",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                "SUMMARY:" + _esc(f"{label}: {title}"),
                "DESCRIPTION:" + _esc("\n".join(desc)),
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
            for e in ev:
                lines.extend(_fold(e))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
