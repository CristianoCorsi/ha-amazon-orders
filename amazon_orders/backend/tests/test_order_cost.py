"""Order cost: Amazon's grand total excludes the Amazon/gift-card balance used; spend must count the full cost."""

from datetime import date, datetime

import pytest

from amazon_orders_ha import repo
from amazon_orders_ha.db import Database
from amazon_orders_ha.mapping import map_order

from .conftest import fake_order

NOW = datetime(2026, 11, 15, 12)


@pytest.fixture
def conn(tmp_path):
    c = Database(tmp_path / "cost.db").connect()

    def add(number, placed, total, gift_card=None, refund=None, subtotal: float | str = "auto"):
        o = fake_order(number, placed, ["Gadget"], total=total, detailed=True)
        o.gift_card = -gift_card if gift_card else None  # the library returns negatives
        o.refund_total = -refund if refund else None
        if subtotal != "auto":
            o.subtotal = subtotal
        repo.upsert_order(c, map_order(o, True, NOW.date()), NOW)

    add("111-0000001-0000001", date(2026, 3, 2), 0.0, gift_card=40.0)            # fully paid with balance
    add("111-0000002-0000002", date(2026, 3, 9), 10.0, gift_card=15.0)           # partly paid with balance
    add("111-0000003-0000003", date(2026, 4, 1), 50.0, refund=50.0)              # refunded later
    add("111-0000004-0000004", date(2026, 4, 5), 0.0, subtotal=18.0)             # balance not parsed
    return c


def total_of(conn, number):
    return repo.order_total(conn.execute("SELECT * FROM orders WHERE order_number=?", (number,)).fetchone())


def test_order_total_adds_back_balance(conn):
    assert total_of(conn, "111-0000001-0000001") == 40.0
    assert total_of(conn, "111-0000002-0000002") == 25.0
    assert total_of(conn, "111-0000003-0000003") == 50.0
    # Grand total 0 and no balance line: items (18) + shipping (2) instead of 0.
    assert total_of(conn, "111-0000004-0000004") == 20.0


def test_spend_is_gross_and_net_subtracts_refunds(conn):
    s = repo.stats_summary(conn, 2026)
    assert s["spend"] == 135.0
    assert s["refunds"] == 50.0 and s["net_spend"] == 85.0
    assert s["gift_card_used"] == 55.0


def test_monthly_and_list_use_full_cost(conn):
    months = {m["month"]: m for m in repo.stats_monthly(conn, "2026-03-01", "2026-04-30", NOW.date())["months"]}
    assert months["2026-03"]["spend"] == 65.0 and months["2026-03"]["net_spend"] == 65.0
    assert months["2026-04"]["spend"] == 70.0 and months["2026-04"]["net_spend"] == 20.0
    orders = repo.list_orders(conn, repo.Filters(min=30))["orders"]
    assert {o["order_number"] for o in orders} == {"111-0000001-0000001", "111-0000003-0000003"}
    first = next(o for o in orders if o["order_number"] == "111-0000001-0000001")
    assert first["grand_total"] == 0.0 and first["order_total"] == 40.0 and first["paid_with_balance"] == 40.0
