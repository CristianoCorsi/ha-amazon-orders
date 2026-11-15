import json
from datetime import date, timedelta

import pytest
from amazonorders.exception import (
    AmazonOrdersAuthRedirectError,
    AmazonOrdersChallengeUnsolvedError,
    AmazonOrdersError,
    AmazonOrdersNotFoundError,
)

from amazon_orders_ha import repo
from amazon_orders_ha.config import Options
from amazon_orders_ha.sync import classify

from .conftest import FakeClock, fake_order

TODAY = date(2026, 11, 15)


def orders(n_recent=3):
    return {
        2026: [fake_order(f"111-000000{i}-0000000", TODAY - timedelta(days=5 + i * 7), [f"Thing {i}"])
               for i in range(n_recent)]
        + [fake_order("111-0000099-0000000", date(2026, 2, 3), ["Old thing"])],
        2025: [fake_order(f"222-000000{i}-0000000", date(2025, 3 + i, 10), [f"Y25 {i}"]) for i in range(3)],
        2024: [fake_order("333-0000001-0000000", date(2024, 5, 10), ["Y24"])],
    }


def count(env, sql="SELECT COUNT(*) FROM orders"):
    c = env.db.connect()
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


def test_recent_refresh_fetches_details_only_for_new(make_env):
    env = make_env(orders())
    r = env.engine.run_recent()
    assert r["new"] == 3 and r["details"] == 3 and r["errors"] == 0
    assert len(env.client.detail_calls) == 3
    assert env.client.page_calls[0]["time_filter"] == "months-3" and env.client.page_calls[0]["limit"] == 1
    assert count(env, "SELECT COUNT(*) FROM orders WHERE details_fetched_at IS NOT NULL") == 3
    # old order (>60 days) not touched
    assert count(env, "SELECT COUNT(*) FROM orders WHERE order_number='111-0000099-0000000'") == 0
    # second run: nothing changed -> no detail requests
    env.client.detail_calls.clear()
    r2 = env.engine.run_recent()
    assert r2["details"] == 0 and env.client.detail_calls == []


def test_fingerprint_change_triggers_detail_refetch(make_env):
    data = orders()
    env = make_env(data)
    env.engine.run_recent()
    env.client.detail_calls.clear()
    changed = data[2026][0]
    changed.shipments[0].delivery_status = "Delivered 20 November"
    env.engine.run_recent()
    assert env.client.detail_calls == [changed.order_number]


def test_requests_are_throttled_through_single_gate(make_env):
    env = make_env(orders())
    env.engine.run_recent()
    assert env.engine.gate.requests == len(env.client.page_calls) + len(env.client.detail_calls)
    gaps = [s for s in env.clock.slept]
    assert gaps and sum(gaps) >= 5 * (env.engine.gate.requests - 1)  # moderate: >= 5 s between requests


def test_detail_overlays_list_without_losing_data(make_env):
    env = make_env({2026: [fake_order("111-0000001-0000000", TODAY - timedelta(days=3), ["A"], total=30.0)]})
    env.engine.run_recent()
    c = env.db.connect()
    row = c.execute("SELECT * FROM orders").fetchone()
    assert row["subtotal"] == 28.0 and row["shipping_total"] == 2.0 and row["payment_method"] == "Visa"
    assert row["grand_total"] == 30.0
    raw = row["raw_json"]
    assert "Fake Person" not in raw and "1 Fake Street" not in raw and "1234" not in raw
    assert "recipient" not in json.loads(raw) and "payment_method_last_4" not in json.loads(raw)


def test_backfill_walks_years_backwards_and_stops_after_empty_years(make_env):
    env = make_env(orders(), options=Options(sync_preset="moderate"))
    env.clock._now = env.clock._now.replace(year=2026)
    r = env.engine.run_backfill()
    assert r["errors"] == 0
    years = [c["year"] for c in env.client.page_calls if c["year"]]
    assert years[0] == 2026 and 2025 in years and 2024 in years and 2023 in years and 2022 in years
    assert 2021 not in years  # two consecutive empty years (2023, 2022) end the walk
    assert count(env) == 4 + 3 + 1
    c = env.db.connect()
    st = repo.get_state(c, "backfill")
    assert st["status"] == "done" and st["history_done"]
    assert count(env, "SELECT COUNT(*) FROM orders WHERE details_fetched_at IS NULL") == 0


def test_backfill_until_year_option(make_env):
    env = make_env(orders(), options=Options(sync_preset="moderate", backfill_until_year=2025))
    env.engine.run_backfill()
    assert count(env) == 4 + 3  # 2024 never visited
    assert 2024 not in [c["year"] for c in env.client.page_calls]


def test_backfill_pause_resume_and_cursor_persists_across_engines(make_env):
    env = make_env(orders())
    env.engine.run_backfill(max_requests=3)  # stops mid-way
    c = env.db.connect()
    st = repo.get_state(c, "backfill")
    assert st["status"] == "running" and not st["history_done"] and st["processed"] > 0
    partial = count(env)
    # pause
    env.engine.backfill_control("pause")
    env.client.page_calls.clear()
    assert env.engine.run_backfill() == {"seen": 0, "new": 0, "details": 0, "errors": 0}
    assert env.client.page_calls == []
    # "restart": new engine over the same DB resumes from the stored cursor/year
    env.engine.backfill_control("start")
    from amazon_orders_ha.sync import SyncEngine

    eng2 = SyncEngine(env.db, env.settings.options, env.auth, client_factory=lambda: env.client, clock=env.clock)
    eng2.run_backfill()
    first = env.client.page_calls[0]
    assert first["cursor"] is not None or first["year"] in (2026, 2025, 2024)
    assert count(env) == 8 and count(env) >= partial


def test_backfill_respects_active_hours_for_careful_preset(make_env):
    clock = FakeClock()
    clock._now = clock._now.replace(hour=14)
    env = make_env(orders(), options=Options(sync_preset="careful"), clock=clock)
    r = env.engine.run_backfill()
    assert r.get("waiting") == "window" and env.client.page_calls == []
    clock._now = clock._now.replace(hour=2)
    env.engine.run_backfill(max_requests=2)
    assert env.client.page_calls
    st = env.engine.status()
    assert st["backfill"]["window_open"] is True


def test_recent_refresh_ignores_active_hours(make_env):
    clock = FakeClock()
    clock._now = clock._now.replace(hour=15)
    env = make_env(orders(), options=Options(sync_preset="careful"), clock=clock)
    assert env.engine.run_recent()["new"] == 3
    # careful preset: 20-40 s between consecutive requests
    gaps = env.engine.gate.requests - 1
    assert 20 * gaps <= sum(clock.slept) <= 40 * gaps


def test_auth_redirect_sets_auth_required_and_stops(make_env):
    env = make_env(orders())
    env.client.fail_page = AmazonOrdersAuthRedirectError("Amazon redirected to login")
    r = env.engine.run_recent()
    assert r["aborted"] == "auth"
    st = env.engine.status()
    assert st["state"] == "auth_required" and st["auth"]["state"] == "auth_required"
    assert [t for t, _ in env.sent] == ["amazon_orders_auth_required"]
    # all jobs are skipped while auth_required; event not repeated
    env.client.page_calls.clear()
    assert env.engine.run_recent() == {"skipped": "auth_required"}
    assert env.engine.run_backfill() == {"skipped": "auth_required"}
    assert env.client.page_calls == []
    # a manual trigger clears the flag
    env.client.fail_page = None
    env.engine.request_recent()
    assert env.engine.run_recent()["new"] == 3


def test_tick_marks_auth_required_when_provider_has_no_session(make_env):
    env = make_env(orders())
    env.auth.ok = False
    assert env.engine.tick() is None
    assert env.engine.status()["state"] == "auth_required"


def test_rate_limit_trips_cooldown_with_event_and_doubles(make_env):
    env = make_env(orders())
    env.client.fail_page = AmazonOrdersError("The page https://www.amazon.it/x returned 503. Wait a bit")
    assert env.engine.run_recent()["aborted"] == "rate"
    st = env.engine.status()
    assert st["state"] == "cooldown" and st["cooldown"]["level"] == 1
    assert env.sent[-1][0] == "amazon_orders_sync_error"
    assert env.engine.run_recent() == {"skipped": "cooldown"}
    env.clock.advance(minutes=16)
    assert env.engine.run_recent()["aborted"] == "rate"
    assert env.engine.status()["cooldown"]["level"] == 2
    until = env.engine.status()["cooldown"]["until"]
    assert until.startswith("2026-11-15T")
    env.clock.advance(minutes=31)
    env.client.fail_page = None
    assert env.engine.run_recent()["errors"] == 0
    assert env.engine.status()["cooldown"] is None


def test_more_than_three_consecutive_parse_errors_trip_cooldown(make_env):
    data = {2026: [fake_order(f"111-000000{i}-0000000", TODAY - timedelta(days=2 + i), [f"T{i}"]) for i in range(6)]}
    env = make_env(data)
    for o in data[2026]:
        env.client.fail_detail[o.order_number] = AmazonOrdersError("Could not parse details")
    r = env.engine.run_recent()
    assert r["aborted"] == "parse"
    assert len(env.client.detail_calls) == 4  # 3 tolerated, the 4th trips
    assert env.engine.status()["state"] == "cooldown"


def test_isolated_parse_errors_do_not_stop_job(make_env):
    data = {2026: [fake_order(f"111-000000{i}-0000000", TODAY - timedelta(days=2 + i), [f"T{i}"]) for i in range(4)]}
    env = make_env(data)
    env.client.fail_detail["111-0000001-0000000"] = AmazonOrdersError("bad")
    r = env.engine.run_recent()
    assert r["errors"] == 1 and r["details"] == 3 and "aborted" not in r


def test_not_found_is_skipped_without_cooldown(make_env):
    data = {2026: [fake_order("111-0000001-0000000", TODAY - timedelta(days=2), ["T"])]}
    env = make_env(data)
    env.client.fail_detail["111-0000001-0000000"] = AmazonOrdersNotFoundError("gone")
    r = env.engine.run_recent()
    assert r["errors"] == 1 and env.engine.status()["cooldown"] is None


def test_classification():
    assert classify(AmazonOrdersAuthRedirectError("x")) == "auth"
    assert classify(AmazonOrdersChallengeUnsolvedError("captcha")) == "rate"
    assert classify(AmazonOrdersError("The page u returned 429.")) == "rate"
    assert classify(AmazonOrdersError("The page u returned 503.")) == "rate"
    assert classify(AmazonOrdersError("The page u returned 404.")) == "parse"
    assert classify(AmazonOrdersNotFoundError("x")) == "gone"
    assert classify(ConnectionError("down")) == "rate"
    assert classify(ValueError("boom")) == "parse"


def test_failing_detail_is_not_retried_forever(make_env):
    data = {2026: [fake_order("111-0000001-0000000", date(2026, 3, 1), ["T"])]}
    env = make_env(data)
    env.client.fail_detail["111-0000001-0000000"] = AmazonOrdersError("bad")
    env.engine.run_backfill()
    assert len(env.client.detail_calls) <= 1 + 3  # list pass + capped retries from the stale queue
    c = env.db.connect()
    assert repo.get_state(c, "backfill")["status"] == "done"


@pytest.mark.parametrize("action", ["start", "pause"])
def test_backfill_control_idempotent(make_env, action):
    env = make_env(orders())
    assert env.engine.backfill_control(action)["status"] in ("running", "paused")
    with pytest.raises(ValueError):
        env.engine.backfill_control("bogus")


def test_auth_rejection_triggers_one_renewal_and_retry(make_env):
    env = make_env(orders())
    env.client.fail_page = AmazonOrdersAuthRedirectError("Amazon redirected to login")
    renewals = []

    def renew():
        renewals.append(1)
        env.client.fail_page = None  # fresh cookies: the retried request succeeds
        return True

    env.auth.renew_session = renew
    assert env.engine.run_recent()["new"] == 3
    assert renewals == [1] and env.sent == []
    assert env.engine.status()["state"] != "auth_required"


def test_auth_rejection_after_renewal_still_requires_login(make_env):
    env = make_env(orders())
    env.client.fail_page = AmazonOrdersAuthRedirectError("Amazon redirected to login")
    calls = []
    env.auth.renew_session = lambda: calls.append(1) or True  # renewed, but Amazon still refuses
    assert env.engine.run_recent()["aborted"] == "auth"
    assert calls == [1]  # exactly one renewal per request
    assert [t for t, _ in env.sent] == ["amazon_orders_auth_required"]


def test_failed_renewal_requires_login(make_env):
    env = make_env(orders())
    env.client.fail_page = AmazonOrdersAuthRedirectError("Amazon redirected to login")
    env.auth.renew_session = lambda: False
    assert env.engine.run_recent()["aborted"] == "auth"


def test_transient_renewal_failure_backs_off_without_auth_required(make_env):
    from amazon_orders_ha.auth import AuthTemporarilyUnavailable

    env = make_env(orders())

    def factory():
        raise AuthTemporarilyUnavailable("cookie renewal failed; will retry later")

    env.engine.client_factory = factory
    assert env.engine.run_recent()["aborted"] == "auth_unavailable"
    st = env.engine.status()
    assert st["state"] == "cooldown" and st["auth"]["state"] == "ok"
    assert [t for t, _ in env.sent] == ["amazon_orders_sync_error"]


def test_tick_skips_while_login_in_progress_and_resumes_after(make_env):
    env = make_env(orders())
    env.auth.ok = False
    env.engine.tick()  # no session -> auth_required flag set
    assert env.engine.status()["state"] == "auth_required"
    env.sent.clear()
    env.auth.ok = False
    env.auth.status = lambda: {"state": "in_progress", "method": None, "expires_hint": None, "login_url": "x"}
    assert env.engine.tick() is None and env.sent == []
    # login finished: provider reports it once, the engine clears the stop and refreshes
    env.auth.ok = True
    env.auth.status = lambda: {"state": "ok", "method": "device", "expires_hint": None}
    env.auth.pop_login_completed = iter([True, False]).__next__
    assert env.engine.tick() == "recent"
    assert env.engine.status()["auth"]["state"] == "ok"

