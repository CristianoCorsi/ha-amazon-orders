"""Home Assistant interface: Core events, MQTT discovery sensors (SPEC §8)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import httpx

from . import repo
from .config import MqttOptions, Options
from .deadlines import ITEM_QUERY, compute_deadlines, evaluate_events

log = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"


class HAEvents:
    """Fires events on HA Core through the Supervisor proxy. No-op without SUPERVISOR_TOKEN."""

    def __init__(self, token: str | None = None, base_url: str | None = None,
                 client: httpx.Client | None = None):
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
        self.base_url = (base_url or os.environ.get("SUPERVISOR_URL") or SUPERVISOR_URL).rstrip("/")
        self.client = client or httpx.Client(timeout=10)

    def __call__(self, event_type: str, data: dict[str, Any]) -> bool:
        return self.fire(event_type, data)

    def fire(self, event_type: str, data: dict[str, Any]) -> bool:
        if not self.token:
            log.debug("No SUPERVISOR_TOKEN: skipping event %s", event_type)
            return False
        try:
            r = self.client.post(
                f"{self.base_url}/core/api/events/{event_type}",
                json=data,
                headers={"Authorization": f"Bearer {self.token}"},
            )
            r.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("Cannot fire event %s: %s", event_type, exc)
            return False


# ----------------------------------------------------------------------------- sensor values


def compute_sensor_values(conn: sqlite3.Connection, today: date, options: Options,
                          status: dict[str, Any] | None = None) -> dict[str, Any]:
    open_returns, open_warr = [], []
    for r in conn.execute(ITEM_QUERY).fetchall():
        row = dict(r)
        dl = compute_deadlines(row, today, options.default_warranty_months)
        entry = {"item_id": row["id"], "title": row["title"], "order_number": row["order_number"]}
        if dl["return"]["state"] == "open":
            open_returns.append({**entry, "deadline": dl["return"]["deadline"], "days_left": dl["return"]["days_left"]})
        if dl["warranty"]["state"] == "open":
            open_warr.append({**entry, "deadline": dl["warranty"]["deadline"],
                              "days_left": dl["warranty"]["days_left"]})
    open_returns.sort(key=lambda x: x["deadline"])
    open_warr.sort(key=lambda x: x["deadline"])
    month = f"{today:%Y-%m}"
    spend_m = conn.execute(
        f"SELECT COALESCE(SUM({repo.cost_sql()} - COALESCE(o.refund_total,0)),0) s FROM orders o"
        " WHERE o.cancelled=0 AND strftime('%Y-%m',o.placed_date)=?",
        (month,)).fetchone()["s"]
    spend_y = conn.execute(
        f"SELECT COALESCE(SUM({repo.cost_sql()} - COALESCE(o.refund_total,0)),0) s FROM orders o"
        " WHERE o.cancelled=0 AND strftime('%Y',o.placed_date)=?",
        (f"{today.year}",)).fetchone()["s"]
    counts = repo.counts(conn)
    st = status or {}
    bf = st.get("backfill") or {}
    return {
        "returns_open": {"state": len(open_returns), "attributes": {"next": open_returns[:10]}},
        "next_return_deadline": open_returns[0]["deadline"] if open_returns else None,
        "warranties_expiring_90d": len([w for w in open_warr if w["days_left"] <= 90]),
        "next_warranty_deadline": open_warr[0]["deadline"] if open_warr else None,
        "spend_this_month": round(spend_m, 2),
        "spend_this_year": round(spend_y, 2),
        "sync_status": st.get("state", "idle"),
        "backfill_progress": {"state": counts["orders_detailed"],
                              "attributes": {"percent": bf.get("percent"), "status": bf.get("status"),
                                             "orders": counts["orders"], "stale": counts["orders_stale"]}},
        "auth_required": "ON" if (st.get("auth") or {}).get("state") == "auth_required" else "OFF",
    }


# ----------------------------------------------------------------------------- MQTT

PREFIX = "amazon_orders"
DEVICE = {"identifiers": ["amazon_orders_addon"], "name": "Amazon Orders",
          "manufacturer": "ha-amazon-orders", "model": "Order history"}

# key, component, name, extra discovery config
SENSORS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("returns_open", "sensor", "Returns open", {"icon": "mdi:package-return", "unit_of_measurement": "items"}),
    ("next_return_deadline", "sensor", "Next return deadline", {"device_class": "date"}),
    ("warranties_expiring_90d", "sensor", "Warranties expiring in 90 days",
     {"icon": "mdi:shield-alert", "unit_of_measurement": "items"}),
    ("next_warranty_deadline", "sensor", "Next warranty deadline", {"device_class": "date"}),
    ("spend_this_month", "sensor", "Spend this month",
     {"device_class": "monetary", "unit_of_measurement": "EUR", "state_class": "total"}),
    ("spend_this_year", "sensor", "Spend this year",
     {"device_class": "monetary", "unit_of_measurement": "EUR", "state_class": "total"}),
    ("sync_status", "sensor", "Sync status",
     {"device_class": "enum", "options": ["idle", "syncing", "backfilling", "cooldown", "auth_required", "error"]}),
    ("backfill_progress", "sensor", "Backfill progress", {"icon": "mdi:history", "unit_of_measurement": "orders"}),
    ("auth_required", "binary_sensor", "Auth required", {"device_class": "problem"}),
]


def discovery_messages(prefix: str = "homeassistant") -> list[tuple[str, dict[str, Any]]]:
    msgs = []
    for key, comp, name, extra in SENSORS:
        cfg: dict[str, Any] = {
            "name": name,
            "unique_id": f"{PREFIX}_{key}",
            "object_id": f"{PREFIX}_{key}",
            "state_topic": f"{PREFIX}/{key}/state",
            "availability_topic": f"{PREFIX}/availability",
            "device": DEVICE,
            **extra,
        }
        if key in ("returns_open", "backfill_progress"):
            cfg["json_attributes_topic"] = f"{PREFIX}/{key}/attributes"
        if comp == "binary_sensor":
            cfg["payload_on"], cfg["payload_off"] = "ON", "OFF"
        msgs.append((f"{prefix}/{comp}/{PREFIX}/{key}/config", cfg))
    return msgs


def resolve_mqtt(opts: MqttOptions, token: str | None = None, base_url: str | None = None) -> MqttOptions | None:
    """Manual options win; otherwise ask Supervisor service discovery."""
    if opts.configured:
        return opts
    token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    try:
        r = httpx.get(f"{(base_url or SUPERVISOR_URL).rstrip('/')}/services/mqtt",
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
        r.raise_for_status()
        d = r.json().get("data") or {}
        if d.get("host"):
            return MqttOptions(d["host"], int(d.get("port") or 1883), d.get("username"), d.get("password"))
    except (httpx.HTTPError, ValueError):
        log.info("MQTT service not available from Supervisor")
    return None


class MqttPublisher:
    """Publishes discovery + states. Silent no-op when MQTT is not configured."""

    def __init__(self, options: Options, client_factory: Callable[[MqttOptions], Any] | None = None,
                 resolver: Callable[[MqttOptions], MqttOptions | None] = resolve_mqtt):
        self.options = options
        self._factory = client_factory or self._paho
        self._resolver = resolver
        self._client: Any = None
        self._discovered = False

    @staticmethod
    def _paho(cfg: MqttOptions) -> Any:
        import paho.mqtt.client as mqtt

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="amazon_orders_addon")
        if cfg.username:
            c.username_pw_set(cfg.username, cfg.password)
        c.will_set(f"{PREFIX}/availability", "offline", retain=True)
        c.connect(cfg.host, cfg.port, keepalive=60)
        c.loop_start()
        return c

    def _connect(self) -> Any:
        if self._client is None:
            cfg = self._resolver(self.options.mqtt)
            if cfg is None:
                return None
            self._client = self._factory(cfg)
        return self._client

    def publish(self, values: dict[str, Any]) -> bool:
        try:
            c = self._connect()
            if c is None:
                return False
            if not self._discovered:
                for topic, cfg in discovery_messages():
                    c.publish(topic, json.dumps(cfg), retain=True)
                c.publish(f"{PREFIX}/availability", "online", retain=True)
                self._discovered = True
            for key, _c, _n, _e in SENSORS:
                v = values.get(key)
                attrs = None
                if isinstance(v, dict):
                    v, attrs = v["state"], v.get("attributes")
                c.publish(f"{PREFIX}/{key}/state", "" if v is None else str(v), retain=True)
                if attrs is not None:
                    c.publish(f"{PREFIX}/{key}/attributes", json.dumps(attrs), retain=True)
            return True
        except Exception as exc:  # network errors must not break syncing
            log.warning("MQTT publish failed: %s", exc)
            self._client = None
            self._discovered = False
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.publish(f"{PREFIX}/availability", "offline", retain=True)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


class HAIntegration:
    """Glue run after syncs and hourly: events + MQTT."""

    def __init__(self, db, options: Options, events: HAEvents, mqtt: MqttPublisher, status_fn):
        self.db, self.options, self.events, self.mqtt, self.status_fn = db, options, events, mqtt, status_fn

    def run(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now()
        conn = self.db.connect()
        try:
            fired = evaluate_events(
                conn, now.date(), now, self.options.return_thresholds, self.options.warranty_thresholds,
                self.events.fire, self.options.default_warranty_months, self.options.domain)
            self.mqtt.publish(compute_sensor_values(conn, now.date(), self.options, self.status_fn()))
            return fired
        finally:
            conn.close()
