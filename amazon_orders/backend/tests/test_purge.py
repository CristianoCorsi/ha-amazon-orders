from datetime import date, datetime, timedelta

import pytest

from amazon_orders_ha import repo
from amazon_orders_ha.db import Database
from amazon_orders_ha.mapping import map_order

from .conftest import fake_order

NOW = datetime(2026, 11, 15, 12)


@pytest.fixture
def conn(tmp_path):
    c = Database(tmp_path / "p.db").connect()
    for number, placed in (("111-0000001-0000001", date(2026, 10, 1)), ("111-0000002-0000002", date(2025, 6, 1)),
                           ("111-0000003-0000003", date(2025, 7, 1))):
        repo.upsert_order(c, map_order(fake_order(number, placed, ["Gadget"], detailed=True), True, NOW.date()), NOW)
        c.execute("UPDATE orders SET list_fingerprint='fp' WHERE order_number=?", (number,))
    repo.patch_item_state(c, c.execute("SELECT MIN(id) FROM items").fetchone()[0],
                          {"status": "keep", "note": "mine", "warranty_months_override": 36}, NOW)
    return c


def stale(conn):
    return {r[0] for r in conn.execute("SELECT order_number FROM orders WHERE details_fetched_at IS NULL")}


def test_purge_all_marks_stale_and_keeps_annotations(conn):
    n = repo.purge(conn, "all")
    assert n == 3 and len(stale(conn)) == 3
    assert conn.execute("SELECT COUNT(*) FROM orders WHERE list_fingerprint IS NOT NULL").fetchone()[0] == 0
    st = conn.execute("SELECT * FROM item_state").fetchall()
    assert len(st) == 1 and st[0]["note"] == "mine" and st[0]["warranty_months_override"] == 36
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3  # rows kept


def test_purge_year_and_order_scopes(conn):
    assert repo.purge(conn, "year:2025") == 2
    assert stale(conn) == {"111-0000002-0000002", "111-0000003-0000003"}
    conn.execute("UPDATE orders SET details_fetched_at='x'")
    assert repo.purge(conn, "order:111-0000001-0000001") == 1
    assert stale(conn) == {"111-0000001-0000001"}
    assert repo.purge(conn, "order:does-not-exist") == 0


@pytest.mark.parametrize("scope", ["", "year:25", "everything", "order:", "year:20x5"])
def test_invalid_scopes(conn, scope):
    with pytest.raises(ValueError):
        repo.purge(conn, scope)


def test_refetch_after_purge_keeps_item_ids_and_state(make_env):
    data = {2026: [fake_order("111-0000001-0000000", date.today() - timedelta(days=2), ["A", "B"])]}
    env = make_env(data)
    env.clock._now = datetime.combine(date.today(), datetime.min.time()).replace(hour=3)
    env.engine.run_recent()
    c = env.db.connect()
    ids = [r[0] for r in c.execute("SELECT id FROM items ORDER BY id")]
    repo.patch_item_state(c, ids[0], {"status": "to_return", "note": "keep me"}, NOW)
    assert env.engine.purge("all") == 1
    env.client.detail_calls.clear()
    env.engine.run_recent()  # fingerprint cleared -> refetch details
    assert env.client.detail_calls == ["111-0000001-0000000"]
    assert [r[0] for r in c.execute("SELECT id FROM items ORDER BY id")] == ids
    s = c.execute("SELECT status, note FROM item_state WHERE item_id=?", (ids[0],)).fetchone()
    assert (s["status"], s["note"]) == ("to_return", "keep me")
    assert c.execute("SELECT COUNT(*) FROM orders WHERE details_fetched_at IS NULL").fetchone()[0] == 0


def test_purge_reopens_finished_backfill_for_stale_details(make_env):
    data = {2026: [fake_order("111-0000001-0000000", date(2026, 3, 1), ["A"])]}
    env = make_env(data)
    env.engine.run_backfill()
    assert repo.get_state(env.db.connect(), "backfill")["status"] == "done"
    env.engine.purge("order:111-0000001-0000000")
    assert repo.get_state(env.db.connect(), "backfill")["status"] == "running"
    env.client.detail_calls.clear()
    env.engine.run_backfill()
    assert env.client.detail_calls == ["111-0000001-0000000"]
