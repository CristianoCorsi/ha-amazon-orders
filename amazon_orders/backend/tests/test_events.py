import json
from datetime import date, datetime

import httpx

from amazon_orders_ha import repo
from amazon_orders_ha.db import Database
from amazon_orders_ha.deadlines import evaluate_events
from amazon_orders_ha.ha import HAEvents
from amazon_orders_ha.mapping import map_order

from .conftest import fake_order

NOW = datetime(2026, 11, 15, 12, 0)
TODAY = NOW.date()


def _setup(tmp_path, return_date, placed=date(2026, 10, 20), delivered_status="Delivered 22 October"):
    db = Database(tmp_path / "e.db")
    conn = db.connect()
    o = fake_order("111-0000001-0000001", placed, ["Widget"], delivered_status, return_date=return_date)
    repo.upsert_order(conn, map_order(o, True, TODAY), NOW)
    return conn


def run(conn, sent, today=TODAY, now=NOW, ok=True):
    def send(t, d):
        sent.append((t, d))
        return ok

    return evaluate_events(conn, today, now, [7, 2, 0], [180, 90, 60, 30, 14, 5], send)


def test_fires_once_per_threshold_and_deadline(tmp_path):
    conn = _setup(tmp_path, date(2026, 11, 20))  # 5 days left -> crosses 7
    sent: list = []
    fired = run(conn, sent)
    ret = [d for _t, d in sent if d["kind"] == "return"]
    assert [d["threshold_days"] for d in ret] == [7]
    assert ret[0]["days_left"] == 5 and ret[0]["deadline"] == "2026-11-20"
    assert {"order_number", "item_id", "title", "asin", "price", "seller", "item_url", "order_url"} <= set(ret[0])
    assert fired
    sent.clear()
    assert [d for d in run(conn, sent) if d["kind"] == "return"] == []  # dedup


def test_tightest_threshold_only_and_loose_marked_handled(tmp_path):
    conn = _setup(tmp_path, date(2026, 11, 16))  # 1 day left: crosses 7 and 2 -> sends 2
    sent: list = []
    run(conn, sent)
    assert [d["threshold_days"] for _t, d in sent if d["kind"] == "return"] == [2]
    rows = conn.execute("SELECT threshold_days FROM fired_events WHERE kind='return' ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == [2, 7]
    # later (deadline day) fires threshold 0
    sent.clear()
    run(conn, sent, today=date(2026, 11, 16), now=datetime(2026, 11, 16, 8))
    assert [d["threshold_days"] for _t, d in sent if d["kind"] == "return"] == [0]


def test_failed_send_is_retried(tmp_path):
    conn = _setup(tmp_path, date(2026, 11, 16))
    sent: list = []
    run(conn, sent, ok=False)
    assert conn.execute("SELECT COUNT(*) FROM fired_events").fetchone()[0] == 0
    sent.clear()
    run(conn, sent, ok=True)
    assert any(d["kind"] == "return" for _t, d in sent)


def test_changed_deadline_refires(tmp_path):
    conn = _setup(tmp_path, date(2026, 11, 16))
    sent: list = []
    run(conn, sent)
    item_id = conn.execute("SELECT id FROM items").fetchone()[0]
    conn.execute("UPDATE items SET return_eligible_date='2026-11-17' WHERE id=?", (item_id,))
    sent.clear()
    run(conn, sent)
    assert [d["deadline"] for _t, d in sent if d["kind"] == "return"] == ["2026-11-17"]


def test_no_events_for_returned_closed_or_cancelled(tmp_path):
    conn = _setup(tmp_path, date(2026, 11, 16))
    item_id = conn.execute("SELECT id FROM items").fetchone()[0]
    repo.patch_item_state(conn, item_id, {"status": "returned"}, NOW)
    sent: list = []
    run(conn, sent)
    assert sent == []


def test_warranty_threshold(tmp_path):
    # delivered 2024-12-01 -> expires 2026-12-01 = 16 days -> crosses 30 (tightest >=14? no: 16>14) => 30
    conn = _setup(tmp_path, None, placed=date(2024, 11, 28), delivered_status="Delivered 1 December")
    sent: list = []
    run(conn, sent)
    war = [d for _t, d in sent if d["kind"] == "warranty"]
    assert [d["threshold_days"] for d in war] == [30] and war[0]["days_left"] == 16


def test_ha_events_noop_without_token(caplog):
    assert HAEvents(token="").fire("amazon_orders_deadline", {"a": 1}) is False


def test_ha_events_posts_to_supervisor_proxy():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json={"message": "ok"})

    ev = HAEvents(token="tkn", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert ev.fire("amazon_orders_deadline", {"kind": "return"}) is True
    assert seen["url"] == "http://supervisor/core/api/events/amazon_orders_deadline"
    assert seen["auth"] == "Bearer tkn" and seen["body"] == {"kind": "return"}


def test_ha_events_http_error_returns_false():
    ev = HAEvents(token="t", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert ev.fire("x", {}) is False
