import csv
import io
from datetime import date, timedelta

import pytest

from .conftest import TODAY


def get(client, url, **kw):
    r = client.get(url, **kw)
    assert r.status_code == 200, r.text
    return r


def test_status(client):
    s = get(client, "/api/status").json()
    assert s["state"] == "idle" and s["currency"] == "EUR"
    assert s["counts"]["orders"] == 300 and s["counts"]["items"] > 300
    assert {"auth", "backfill", "cooldown", "last_error", "preset"} <= set(s)
    assert s["backfill"]["status"] == "done" and s["backfill"]["percent"] == 100.0


def test_settings_readonly_view(client):
    s = get(client, "/api/settings").json()
    assert s["return_thresholds"] == [7, 2, 0] and s["default_warranty_months"] == 24
    assert "password" not in str(s)


def test_orders_list_paging_sorting(client):
    r = get(client, "/api/orders?page_size=10&sort=date_asc").json()
    assert r["total"] == 300 and len(r["orders"]) == 10 and r["currency"] == "EUR"
    dates = [o["placed_date"] for o in r["orders"]]
    assert dates == sorted(dates)
    o = r["orders"][0]
    assert {"order_number", "placed_date", "grand_total", "cancelled", "status", "items", "item_count"} <= set(o)
    p2 = get(client, "/api/orders?page_size=10&sort=date_asc&page=2").json()
    assert p2["orders"][0]["order_number"] != o["order_number"]
    desc = get(client, "/api/orders?page_size=5").json()["orders"]
    assert [x["placed_date"] for x in desc] == sorted((x["placed_date"] for x in desc), reverse=True)
    tot = get(client, "/api/orders?sort=total_desc&page_size=5").json()["orders"]
    assert tot[0]["grand_total"] >= tot[-1]["grand_total"]


def test_orders_filters(client):
    all_ = get(client, "/api/orders?page_size=200").json()
    y = get(client, "/api/orders?from=2025-01-01&to=2025-12-31&page_size=200").json()
    assert 0 < y["total"] < 300 and all(o["placed_date"].startswith("2025") for o in y["orders"])
    c = get(client, "/api/orders?status=cancelled&page_size=200").json()
    assert c["total"] > 0 and all(o["cancelled"] for o in c["orders"])
    m = get(client, "/api/orders?min=100&max=300&page_size=200").json()
    assert m["total"] > 0 and all(100 <= o["grand_total"] <= 300 for o in m["orders"])
    s = get(client, "/api/orders?seller=amazon&page_size=200").json()
    assert 0 < s["total"] < all_["total"] + 1
    assert get(client, "/api/orders?status=returned").json()["total"] > 0


def test_search_fts_by_title_seller_and_order_number(client):
    r = get(client, "/api/items?q=caff%C3%A8").json()  # accent-insensitive: caffè / caffe
    assert r["total"] > 0 and all("caff" in i["title"].lower() for i in r["items"])
    assert get(client, "/api/items?q=caffe").json()["total"] == r["total"]
    assert get(client, "/api/items?q=monit").json()["total"] > 0  # prefix match
    first = get(client, "/api/orders?page_size=1").json()["orders"][0]["order_number"]
    by_no = get(client, f"/api/orders?q={first}").json()
    assert by_no["total"] == 1 and by_no["orders"][0]["order_number"] == first
    assert get(client, "/api/orders?q=zzzzqqqq").json()["total"] == 0
    assert get(client, "/api/orders?q=%22%27--").json()["total"] == 0  # punctuation-only never errors


def test_order_detail(client):
    first = get(client, "/api/orders?page_size=1").json()["orders"][0]["order_number"]
    d = get(client, f"/api/orders/{first}").json()
    assert d["order"]["order_number"] == first and "raw_json" not in d["order"]
    assert d["items"] and {"state", "deadlines", "title"} <= set(d["items"][0])
    assert set(d["items"][0]["deadlines"]) == {"return", "warranty"}
    assert isinstance(d["shipments"], list)
    r = client.get("/api/orders/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_items_list_filters(client):
    r = get(client, "/api/items?page_size=20&sort=price_desc&min=50").json()
    assert all(i["price"] >= 50 for i in r["items"])
    assert r["items"][0]["order"]["order_number"] and "deadlines" in r["items"][0]
    keep = get(client, "/api/items?status=keep&page_size=200").json()
    assert keep["total"] > 0 and all(i["state"]["status"] == "keep" for i in keep["items"])


def test_patch_item_state_roundtrip(client):
    item = get(client, "/api/items?page_size=1&status=none").json()["items"][0]
    iid = item["id"]
    r = client.patch(f"/api/items/{iid}/state", json={"status": "to_return", "note": "ciao",
                                                        "warranty_months_override": 36})
    assert r.status_code == 200
    st = r.json()["state"]
    assert st == {"status": "to_return", "note": "ciao", "warranty_until_override": None,
                  "warranty_months_override": 36}
    # partial patch keeps other fields; explicit null clears
    r = client.patch(f"/api/items/{iid}/state", json={"warranty_until_override": "2031-01-02"}).json()
    assert r["state"]["status"] == "to_return" and r["state"]["warranty_until_override"] == "2031-01-02"
    assert r["deadlines"]["warranty"]["deadline"] == "2031-01-02"
    r = client.patch(f"/api/items/{iid}/state", json={"warranty_until_override": None,
                                                        "warranty_months_override": None}).json()
    assert r["state"]["warranty_until_override"] is None and r["state"]["warranty_months_override"] is None
    # visible through the order endpoint
    d = get(client, f"/api/orders/{item['order_number']}").json()
    assert [i for i in d["items"] if i["id"] == iid][0]["state"]["note"] == "ciao"


def test_patch_validation_and_404(client):
    iid = get(client, "/api/items?page_size=1").json()["items"][0]["id"]
    r = client.patch(f"/api/items/{iid}/state", json={"status": "bogus"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert client.patch(f"/api/items/{iid}/state", json={"warranty_months_override": 0}).status_code == 422
    assert client.patch(f"/api/items/{iid}/state", json={"warranty_until_override": "31/12/2030"}).status_code == 422
    r = client.patch("/api/items/99999999/state", json={"status": "keep"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_marking_returned_removes_deadlines_and_stats(client):
    dl = get(client, "/api/deadlines?kind=return&within_days=400").json()["deadlines"]
    assert dl
    iid = dl[0]["item"]["id"]
    before = get(client, "/api/stats/returns").json()["returned_items"]
    client.patch(f"/api/items/{iid}/state", json={"status": "returned"})
    after = get(client, "/api/deadlines?kind=all&within_days=4000&include_closed=true").json()["deadlines"]
    assert all(d["item"]["id"] != iid for d in after)
    assert get(client, "/api/stats/returns").json()["returned_items"] == before + 1


def test_deadlines(client):
    d = get(client, "/api/deadlines").json()
    assert d["today"] == TODAY.isoformat()
    ret = get(client, "/api/deadlines?kind=return").json()["deadlines"]
    assert ret and all(x["kind"] == "return" and x["state"] == "open" for x in ret)
    assert [x["deadline"] for x in ret] == sorted(x["deadline"] for x in ret)
    soon = get(client, "/api/deadlines?kind=return&within_days=7").json()["deadlines"]
    assert 0 < len(soon) < len(ret) and all(x["days_left"] <= 7 for x in soon)
    with_closed = get(client, "/api/deadlines?kind=return&include_closed=true").json()["deadlines"]
    assert any(x["state"] == "closed" for x in with_closed) and len(with_closed) > len(ret)
    war = get(client, "/api/deadlines?kind=warranty&within_days=120").json()["deadlines"]
    assert war and all(x["kind"] == "warranty" for x in war)
    assert client.get("/api/deadlines?kind=nope").status_code == 422


def test_stats_summary(client):
    s = get(client, "/api/stats/summary").json()
    assert s["orders"] > 250 and s["spend"] > 5000 and s["cancelled"] > 0 and s["currency"] == "EUR"
    assert s["avg_order"] == pytest.approx(s["spend"] / s["orders"], rel=0.05)
    assert {"items", "shipping_paid", "refunds", "gift_card_used", "coupon_savings"} <= set(s)
    y = get(client, "/api/stats/summary?year=2025").json()
    assert y["year"] == 2025 and 0 < y["orders"] < s["orders"]


def test_stats_monthly(client):
    m = get(client, "/api/stats/monthly?from=2025-01-01&to=2025-12-31").json()["months"]
    assert [x["month"] for x in m] == [f"2025-{i:02d}" for i in range(1, 13)]
    assert sum(x["orders"] for x in m) == get(client, "/api/stats/summary?year=2025").json()["orders"]
    default = get(client, "/api/stats/monthly").json()["months"]
    assert len(default) == 36 and default[-1]["month"] == "2026-11"


def test_stats_sellers_topitems_recurring_returns_weekday(client):
    s = get(client, "/api/stats/sellers?limit=3").json()["sellers"]
    assert len(s) == 3 and s[0]["spend"] >= s[1]["spend"] >= s[2]["spend"]
    t = get(client, "/api/stats/top-items?limit=5").json()["items"]
    assert len(t) == 5 and t[0]["price"] >= t[-1]["price"]
    rec = get(client, "/api/stats/recurring?limit=5").json()["recurring"]
    assert rec and rec[0]["count"] >= 2 and rec[0]["first_date"] <= rec[0]["last_date"]
    assert {"asin", "price_min", "price_max", "price_last", "title"} <= set(rec[0])
    rt = get(client, "/api/stats/returns").json()
    assert rt["returned_items"] > 0 and 0 < rt["return_rate"] < 0.2
    wd = get(client, "/api/stats/weekday").json()
    assert len(wd["weekdays"]) == 7 and len(wd["months"]) == 12
    assert sum(x["orders"] for x in wd["weekdays"]) == sum(x["orders"] for x in wd["months"])
    assert wd["heatmap"]


def test_export_csv_with_filters(client):
    r = get(client, "/api/export.csv?from=2025-01-01&to=2025-12-31&sort=date_asc")
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows and all(x["placed_date"].startswith("2025") for x in rows)
    assert {"order_number", "title", "price", "return_deadline", "warranty_deadline", "status"} <= set(rows[0])
    total = get(client, "/api/items?from=2025-01-01&to=2025-12-31&page_size=1").json()["total"]
    assert len(rows) == total


def test_csv_formula_injection_neutralised(client, seeded_rt):
    c = seeded_rt.db.connect()
    c.execute("UPDATE items SET title='=HYPERLINK(\"x\")' WHERE id=(SELECT MIN(id) FROM items)")
    text = get(client, "/api/export.csv").text
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


def test_sync_endpoints(client, seeded_rt):
    r = client.post("/api/sync/recent")
    assert r.status_code == 200 and r.json() == {"queued": True}
    c = seeded_rt.db.connect()
    from amazon_orders_ha import repo

    assert repo.get_state(c, "recent_requested") is True
    r = client.post("/api/sync/backfill", json={"action": "pause"})
    assert r.json()["status"] == "done"  # seeded backfill already finished: pause is a no-op
    r = client.post("/api/sync/backfill", json={"action": "start"})
    assert r.status_code == 200 and r.json()["status"] == "running"  # restarts the history walk
    assert client.post("/api/sync/backfill", json={"action": "x"}).status_code == 422
    assert client.post("/api/sync/backfill", json={"action": "pause"}).json()["status"] == "paused"


def test_cache_purge_endpoint_keeps_annotations(client, seeded_rt):
    notes_before = get(client, "/api/items?status=keep&page_size=1").json()["total"]
    r = client.post("/api/cache/purge", json={"scope": "year:2025"})
    assert r.status_code == 200 and r.json()["purged"] > 0
    assert get(client, "/api/status").json()["counts"]["orders_stale"] == r.json()["purged"]
    assert client.post("/api/cache/purge", json={"scope": "all"}).json()["purged"] == 300
    assert get(client, "/api/items?status=keep&page_size=1").json()["total"] == notes_before
    first = get(client, "/api/orders?page_size=1").json()["orders"][0]["order_number"]
    assert client.post("/api/cache/purge", json={"scope": f"order:{first}"}).json()["purged"] == 1
    assert client.post("/api/cache/purge", json={"scope": "order:0-0-0"}).status_code == 404
    for bad in ("everything", "year:99", ""):
        r = client.post("/api/cache/purge", json={"scope": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_auth_endpoints(client, seeded_rt):
    assert get(client, "/api/auth/status").json()["state"] == "ok"
    assert client.post("/api/auth/start").json() == {"url": "https://login.example.test/start"}
    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert seeded_rt.auth.logged_out
    assert get(client, "/api/auth/status").json()["state"] == "auth_required"


def test_auth_start_passes_browser_host_through_ingress(client, seeded_rt):
    """Under Ingress the Supervisor sets X-Forwarded-Host to the host the browser used; Host is internal."""
    ingress = {"X-Forwarded-Host": "homeassistant.local:8123", "X-Ingress-Path": "/api/hassio_ingress/tok",
               "Origin": "http://homeassistant.local:8123"}
    assert client.post("/api/auth/start", headers=ingress).status_code == 200
    assert client.post("/api/auth/start", headers={"Host": "192.168.1.5:8099"}).status_code == 200
    assert seeded_rt.auth.start_hosts == ["homeassistant.local:8123", "192.168.1.5:8099"]


def test_auth_post_rejects_cross_origin(client, seeded_rt):
    for path in ("/api/auth/start", "/api/auth/logout"):
        r = client.post(path, headers={"Origin": "https://evil.example", "X-Forwarded-Host": "homeassistant.local"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert seeded_rt.auth.start_hosts == [] and not seeded_rt.auth.logged_out


def test_auth_start_unavailable_is_501(client, seeded_rt):
    from amazon_orders_ha.auth import AuthRequired

    def boom(host=None):
        raise AuthRequired("LAN only")

    seeded_rt.auth.start = boom
    r = client.post("/api/auth/start")
    assert r.status_code == 501 and r.json()["error"] == {"code": "auth_unavailable", "message": "LAN only"}


def test_auth_status_hides_login_url_unless_in_progress(client, seeded_rt):
    seeded_rt.auth.status = lambda: {"state": "ok", "method": "device", "expires_hint": None, "login_url": "x"}
    assert "login_url" not in get(client, "/api/auth/status").json()
    seeded_rt.auth.status = lambda: {"state": "in_progress", "method": None, "expires_hint": None,
                                     "login_url": "http://h:8098/auth/proxy/t/"}
    assert get(client, "/api/auth/status").json()["login_url"] == "http://h:8098/auth/proxy/t/"


def test_calendar_ics_endpoint(client):
    r = get(client, "/calendar.ics")
    assert r.headers["content-type"].startswith("text/calendar")
    assert r.text.startswith("BEGIN:VCALENDAR") and r.text.count("BEGIN:VEVENT") > 5


def test_unknown_api_path_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_bad_params(client):
    assert client.get("/api/orders?page=0").status_code == 422
    assert client.get("/api/orders?from=yesterday").json()["error"]["code"] == "validation_error"
    assert client.get("/api/orders?page_size=9999").status_code == 422
    assert client.get("/api/orders?sort=drop_table").status_code == 422


def test_frontend_static_spa_fallback_and_ingress_base(client, seeded_rt):
    fe = seeded_rt.settings.frontend_dir
    (fe / "_app").mkdir(parents=True)
    (fe / "index.html").write_text("<!doctype html><html><head><title>x</title></head><body>app</body></html>")
    (fe / "_app" / "a.js").write_text("console.log(1)")
    r = get(client, "/")
    assert "<base href=\"/\">" in r.text
    r = get(client, "/orders/123", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
    assert 'base href="/api/hassio_ingress/abc123/"' in r.text and "app</body>" in r.text
    r = get(client, "/", headers={"X-Ingress-Path": '/x"><script>'})
    assert "<script>" not in r.text
    assert get(client, "/_app/a.js").text == "console.log(1)"
    assert get(client, "/../../etc/passwd").text.startswith("<!doctype")  # no traversal: SPA fallback
    assert client.get("/api/orders", headers={"X-Ingress-Path": "/p"}).status_code == 200


def test_json_endpoints_work_with_ingress_header(client):
    for u in ("/api/status", "/api/deadlines", "/api/stats/summary"):
        assert client.get(u, headers={"X-Ingress-Path": "/api/hassio_ingress/tok"}).status_code == 200


def test_today_helper_consistency(seeded_rt):
    assert seeded_rt.today() == TODAY and TODAY - timedelta(days=1) < date(2026, 11, 15)
