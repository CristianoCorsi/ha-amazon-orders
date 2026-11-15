from datetime import date

from amazon_orders_ha.deadlines import compute_deadlines

TODAY = date(2026, 11, 15)


def row(**kw):
    base = dict(return_eligible_date=None, delivered_date=None, placed_date="2026-10-01", cancelled=0,
                status="none", warranty_until_override=None, warranty_months_override=None)
    base.update(kw)
    return base


def test_return_uses_amazon_date_never_plus_30():
    d = compute_deadlines(row(return_eligible_date="2026-12-24", delivered_date="2026-10-05"), TODAY)
    assert d["return"] == {"kind": "return", "deadline": "2026-12-24", "days_left": 39, "state": "open",
                           "source": "amazon"}


def test_return_closed_when_past():
    d = compute_deadlines(row(return_eligible_date="2026-11-14"), TODAY)
    assert d["return"]["state"] == "closed" and d["return"]["days_left"] == -1


def test_return_deadline_today_is_open():
    d = compute_deadlines(row(return_eligible_date="2026-11-15"), TODAY)
    assert d["return"]["state"] == "open" and d["return"]["days_left"] == 0


def test_return_unknown_for_recent_closed_for_old():
    assert compute_deadlines(row(placed_date="2026-10-20"), TODAY)["return"]["state"] == "unknown"
    assert compute_deadlines(row(placed_date="2026-08-01"), TODAY)["return"]["state"] == "closed"
    assert compute_deadlines(row(placed_date="2026-08-01"), TODAY)["return"]["deadline"] is None


def test_warranty_from_delivery_else_placed():
    d = compute_deadlines(row(delivered_date="2026-10-05"), TODAY)
    assert d["warranty"]["deadline"] == "2028-10-05" and d["warranty"]["source"] == "computed"
    d = compute_deadlines(row(), TODAY)
    assert d["warranty"]["deadline"] == "2028-10-01"


def test_warranty_month_end_clamps():
    d = compute_deadlines(row(delivered_date="2024-02-29", placed_date="2024-02-20"), TODAY)
    assert d["warranty"]["deadline"] == "2026-02-28" and d["warranty"]["state"] == "closed"


def test_overrides():
    d = compute_deadlines(row(delivered_date="2026-10-05", warranty_months_override=36), TODAY)
    assert d["warranty"]["deadline"] == "2029-10-05"
    d = compute_deadlines(row(delivered_date="2026-10-05", warranty_months_override=36,
                              warranty_until_override="2027-01-31"), TODAY)
    assert d["warranty"]["deadline"] == "2027-01-31" and d["warranty"]["source"] == "override"


def test_default_months_option():
    d = compute_deadlines(row(delivered_date="2026-10-05"), TODAY, default_warranty_months=12)
    assert d["warranty"]["deadline"] == "2027-10-05"


def test_returned_and_cancelled_have_no_deadlines():
    for kw in ({"status": "returned"}, {"cancelled": 1}):
        d = compute_deadlines(row(return_eligible_date="2026-12-01", delivered_date="2026-10-05", **kw), TODAY)
        assert d["return"]["state"] == d["warranty"]["state"] == "none"
        assert d["return"]["deadline"] is None and d["warranty"]["deadline"] is None


def test_keep_disables_return_only():
    d = compute_deadlines(row(return_eligible_date="2026-12-01", delivered_date="2026-10-05", status="keep"), TODAY)
    assert d["return"]["state"] == "none" and d["warranty"]["state"] == "open"
