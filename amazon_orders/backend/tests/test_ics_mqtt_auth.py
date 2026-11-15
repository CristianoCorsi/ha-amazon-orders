import json
from datetime import datetime

from amazon_orders_ha import repo
from amazon_orders_ha.auth import AuthProvider, AuthRequired, CookieFileAuthProvider, DeviceAuthProvider
from amazon_orders_ha.config import MqttOptions, Options
from amazon_orders_ha.db import Database
from amazon_orders_ha.ha import (
    SENSORS,
    HAEvents,
    HAIntegration,
    MqttPublisher,
    compute_sensor_values,
    discovery_messages,
)
from amazon_orders_ha.ics import _fold, build_ics
from amazon_orders_ha.mapping import map_order

from .conftest import TODAY, FakeAuth, fake_order

NOW = datetime(2026, 11, 15, 12)


def _db_with_order(tmp_path, **kw):
    db = Database(tmp_path / "i.db")
    c = db.connect()
    o = fake_order("111-0000001-0000001", TODAY.replace(day=1), ["Cavo, USB; \"C\""], "Delivered 3 November",
                   return_date=kw.get("return_date", TODAY.replace(day=20)), detailed=True)
    repo.upsert_order(c, map_order(o, True, TODAY), NOW)
    return db, c


def test_ics_content(tmp_path):
    db, c = _db_with_order(tmp_path)
    text = build_ics(c, TODAY, NOW)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 2 == text.count("END:VEVENT")
    assert "DTSTART;VALUE=DATE:20261120" in text and "DTEND;VALUE=DATE:20261121" in text
    assert "DTSTART;VALUE=DATE:20281103" in text  # warranty: delivered 3 Nov + 24 months
    assert "SUMMARY:Return deadline: Cavo\\, USB\\; \"C\"" in text
    assert "SUMMARY:Warranty expires:" in text
    assert "orderID=111-0000001-0000001" in text.replace("\r\n ", "")
    assert len({ln for ln in text.splitlines() if ln.startswith("UID:")}) == 2
    assert all(len(ln.encode()) <= 75 for ln in text.split("\r\n"))


def test_ics_skips_returned_and_cancelled(tmp_path):
    db, c = _db_with_order(tmp_path)
    iid = c.execute("SELECT id FROM items").fetchone()[0]
    repo.patch_item_state(c, iid, {"status": "returned"}, NOW)
    assert "BEGIN:VEVENT" not in build_ics(c, TODAY, NOW)


def test_ics_fold_utf8_safe():
    lines = _fold("DESCRIPTION:" + "è" * 100)
    assert all(len(ln.encode()) <= 75 for ln in lines)
    assert "".join(ln.lstrip(" ") if i else ln for i, ln in enumerate(lines)) == "DESCRIPTION:" + "è" * 100


class FakeMqtt:
    def __init__(self):
        self.msgs: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload, retain=False):
        self.msgs.append((topic, payload, retain))


def test_discovery_payloads():
    msgs = dict(discovery_messages())
    assert len(msgs) == len(SENSORS) == 9
    cfg = msgs["homeassistant/sensor/amazon_orders/returns_open/config"]
    assert cfg["unique_id"] == "amazon_orders_returns_open" and cfg["device"]["name"] == "Amazon Orders"
    assert cfg["json_attributes_topic"] == "amazon_orders/returns_open/attributes"
    assert msgs["homeassistant/binary_sensor/amazon_orders/auth_required/config"]["payload_on"] == "ON"
    assert msgs["homeassistant/sensor/amazon_orders/spend_this_year/config"]["unit_of_measurement"] == "EUR"
    assert {c["object_id"] for c in msgs.values()} == {f"amazon_orders_{k}" for k, *_ in SENSORS}


def test_mqtt_publish_values(tmp_path):
    db, c = _db_with_order(tmp_path)
    fake = FakeMqtt()
    pub = MqttPublisher(Options(mqtt=MqttOptions(host="broker.test")), client_factory=lambda cfg: fake)
    vals = compute_sensor_values(c, TODAY, Options(), {"state": "idle", "auth": {"state": "ok"}, "backfill": {}})
    assert pub.publish(vals) is True
    topics = {t: p for t, p, _ in fake.msgs}
    assert topics["amazon_orders/returns_open/state"] == "1"
    assert json.loads(topics["amazon_orders/returns_open/attributes"])["next"][0]["deadline"] == "2026-11-20"
    assert topics["amazon_orders/next_return_deadline/state"] == "2026-11-20"
    assert topics["amazon_orders/next_warranty_deadline/state"] == "2028-11-03"
    assert topics["amazon_orders/warranties_expiring_90d/state"] == "0"
    assert topics["amazon_orders/sync_status/state"] == "idle"
    assert topics["amazon_orders/auth_required/state"] == "OFF"
    assert float(topics["amazon_orders/spend_this_month/state"]) == 25.0
    assert topics["amazon_orders/availability"] == "online"
    assert all(r for _t, _p, r in fake.msgs)  # retained
    n = len(fake.msgs)
    pub.publish(vals)
    assert sum(1 for t, _p, _r in fake.msgs[n:] if t.startswith("homeassistant/")) == 0  # discovery sent once


def test_mqtt_noop_when_not_configured(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    pub = MqttPublisher(Options())
    assert pub.publish({"sync_status": "idle"}) is False


def test_mqtt_connection_failure_does_not_raise():
    def boom(cfg):
        raise OSError("refused")

    pub = MqttPublisher(Options(mqtt=MqttOptions(host="x")), client_factory=boom)
    assert pub.publish({}) is False


def test_integration_fires_and_publishes(tmp_path):
    db, c = _db_with_order(tmp_path, return_date=TODAY.replace(day=16))
    sent = []

    class Ev(HAEvents):
        def fire(self, t, d):
            sent.append((t, d))
            return True

    fake = FakeMqtt()
    opts = Options(mqtt=MqttOptions(host="b"))
    integ = HAIntegration(db, opts, Ev(token="t"), MqttPublisher(opts, client_factory=lambda cfg: fake),
                          lambda: {"state": "idle", "auth": {"state": "ok"}, "backfill": {}})
    integ.run(NOW)
    assert any(d["kind"] == "return" and d["threshold_days"] == 2 for _t, d in sent)
    assert fake.msgs
    sent.clear()
    integ.run(NOW)
    assert sent == []


def test_cookie_provider_without_cookies(tmp_path):
    p = CookieFileAuthProvider(tmp_path, "amazon.it")
    assert isinstance(p, AuthProvider) and isinstance(FakeAuth(), AuthProvider)
    assert p.status()["state"] == "auth_required"
    import pytest

    with pytest.raises(AuthRequired):
        p.get_session()
    assert p.cookie_path == tmp_path / "amazonorders" / "cookies.amazon.it.json"


def test_cookie_provider_with_synthetic_jar(tmp_path):
    jar = tmp_path / "amazonorders" / "cookies.amazon.it.json"
    jar.parent.mkdir(parents=True)
    jar.write_text(json.dumps([
        {"name": "x-acbit", "value": "fake-not-a-secret", "domain": ".amazon.it", "path": "/", "secure": True,
         "expires": 2000000000},
    ]))
    p = CookieFileAuthProvider(tmp_path, "amazon.it")
    st = p.status()
    assert st["state"] == "ok" and st["expires_hint"] == "2033-05-18"
    s = p.get_session()
    assert s.is_authenticated and s.config.site == "amazon.it"
    assert str(tmp_path) in s.config.cookie_jar_path
    assert s.config.warn_on_missing_required_field is True
    p.logout()
    assert not jar.exists() and p.status()["state"] == "auth_required"


def test_dev_auth_provider_env(settings, monkeypatch):
    from amazon_orders_ha.service import make_auth_provider

    monkeypatch.setenv("AMAZON_ORDERS_DEV_AUTH", "1")
    p = make_auth_provider(settings)
    assert p.status()["state"] == "ok" and isinstance(p, AuthProvider)
    monkeypatch.delenv("AMAZON_ORDERS_DEV_AUTH")
    p = make_auth_provider(settings)
    assert isinstance(p, DeviceAuthProvider) and isinstance(p, AuthProvider)
    assert p.login_port == 8098 and p.store.directory == settings.data_dir / "auth"
    monkeypatch.setenv("AMAZON_ORDERS_AUTH", "cookie_file")
    assert isinstance(make_auth_provider(settings), CookieFileAuthProvider)
