from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from amazon_orders_ha.auth_provider import AuthRequired
from amazon_orders_ha.config import Options, Settings
from amazon_orders_ha.db import Database
from amazon_orders_ha.dev import seed_database
from amazon_orders_ha.ha import HAEvents, MqttPublisher
from amazon_orders_ha.service import Runtime, build_runtime
from amazon_orders_ha.sync import SyncEngine

TODAY = date(2026, 11, 15)


class FakeClock:
    """Deterministic clock: sleep() just advances time."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 11, 15, 3, 0, 0)
        self._mono = 1000.0
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self._mono += seconds
        self._now += timedelta(seconds=seconds)

    def advance(self, **kw: float) -> None:
        d = timedelta(**kw)
        self._now += d
        self._mono += d.total_seconds()


class FakeAuth:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.logged_out = False

    def status(self) -> dict[str, Any]:
        return {"state": "ok" if self.ok else "auth_required", "method": "fake", "expires_hint": None}

    def start(self) -> str:
        return "https://login.example.test/start"

    def logout(self) -> None:
        self.logged_out = True
        self.ok = False

    def get_session(self) -> Any:
        if not self.ok:
            raise AuthRequired("no session")
        return SimpleNamespace(config=None)


# ---- fake amazon-orders entities (synthetic data only)


def fake_item(title: str, asin: str | None = None, price: float | None = 10.0, seller: str | None = "Seller A",
              return_date: date | None = None) -> SimpleNamespace:
    return SimpleNamespace(title=title, asin=asin or f"B0FAKE{abs(hash(title)) % 10**4:04d}", price=price,
                           quantity=1, seller=SimpleNamespace(name=seller) if seller else None,
                           image_link=None, link=f"/dp/{asin or 'X'}", return_eligible_date=return_date)


def fake_order(number: str, placed: date, titles: list[str] | None = None, status: str | None = "Delivered 3 November",
               total: float | None = 25.0, detailed: bool = False, cancelled: bool = False,
               return_date: date | None = None) -> SimpleNamespace:
    items = [fake_item(t, f"B0{i:03d}{number[-4:]}", return_date=return_date)
             for i, t in enumerate(titles or ["Widget"])]
    ship = SimpleNamespace(items=items, delivery_status=status, tracking_link=None, shipment_id=None)
    o = SimpleNamespace(
        order_number=number, order_placed_date=placed, grand_total=None if cancelled else total,
        cancelled=cancelled, order_details_link=f"/your-orders/order-details?orderID={number}",
        shipments=[ship], items=items,
        recipient=SimpleNamespace(name="Fake Person", address="1 Fake Street"),
        payment_method="Visa" if detailed else None, payment_method_last_4="1234" if detailed else None,
        subtotal=(total - 2) if detailed and total else None, shipping_total=2.0 if detailed else None,
        estimated_tax=None, refund_total=None, gift_card=None, coupon_savings=None,
        parse_failures=[],
    )
    return o


class FakeClient:
    """Fake of AmazonOrders: get_orders_page + get_order. No network, counts calls."""

    def __init__(self, by_year: dict[int, list[SimpleNamespace]], page_size: int = 2):
        self.by_year = by_year
        self.page_size = page_size
        self.page_calls: list[dict[str, Any]] = []
        self.detail_calls: list[str] = []
        self.fail_detail: dict[str, Exception] = {}
        self.fail_page: Exception | None = None
        self.detail_override: dict[str, SimpleNamespace] = {}

    def _all(self) -> list[SimpleNamespace]:
        return sorted((o for v in self.by_year.values() for o in v), key=lambda o: o.order_placed_date, reverse=True)

    def get_orders_page(self, year=None, cursor=None, limit=None, time_filter=None, **_kw):
        self.page_calls.append({"year": year, "cursor": cursor, "time_filter": time_filter, "limit": limit})
        if self.fail_page:
            raise self.fail_page
        if cursor:
            pool = cursor["pool"]
            start = cursor["start"]
        elif time_filter:
            pool, start = "recent", 0
        else:
            pool, start = int(year), 0
        orders = self._all() if pool == "recent" else sorted(
            self.by_year.get(pool, []), key=lambda o: o.order_placed_date, reverse=True)
        chunk = orders[start:start + self.page_size]
        nxt = {"pool": pool, "start": start + self.page_size} if start + self.page_size < len(orders) else None
        return SimpleNamespace(items=chunk, cursor=nxt)

    def get_order(self, order_id: str, clone=None):
        self.detail_calls.append(order_id)
        if order_id in self.fail_detail:
            raise self.fail_detail[order_id]
        if order_id in self.detail_override:
            return self.detail_override[order_id]
        for o in self._all():
            if o.order_number == order_id:
                return fake_order(order_id, o.order_placed_date, [i.title for i in o.items],
                                  o.shipments[0].delivery_status, o.grand_total, detailed=True,
                                  cancelled=o.cancelled)
        raise KeyError(order_id)


@dataclass
class Env:
    settings: Settings
    db: Database
    clock: FakeClock
    auth: FakeAuth
    engine: SyncEngine
    client: FakeClient
    sent: list[tuple[str, dict]]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, options=Options(sync_preset="moderate"), frontend_dir=tmp_path / "fe")


@pytest.fixture
def make_env(settings):
    def _make(by_year=None, options: Options | None = None, clock: FakeClock | None = None) -> Env:
        if options:
            settings.options = options
        db = Database(settings.db_path)
        clock = clock or FakeClock()
        auth = FakeAuth()
        client = FakeClient(by_year or {})
        sent: list[tuple[str, dict]] = []
        engine = SyncEngine(db, settings.options, auth, client_factory=lambda: client, clock=clock,
                            notify=lambda t, d: sent.append((t, d)) or True, rng=random.Random(1))
        return Env(settings, db, clock, auth, engine, client, sent)

    return _make


@pytest.fixture(scope="session")
def seed_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("seed") / "amazon_orders.db"
    db = Database(path)
    seed_database(db, today=TODAY)
    conn = db.connect()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture
def seeded_rt(settings, seed_template) -> Runtime:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(seed_template, settings.db_path)
    rt = build_runtime(settings, auth=FakeAuth(), events=HAEvents(token=""), mqtt=MqttPublisher(settings.options))
    rt.now = lambda: datetime.combine(TODAY, datetime.min.time()).replace(hour=12)
    return rt


@pytest.fixture
def client(seeded_rt):
    from fastapi.testclient import TestClient

    from amazon_orders_ha.api import create_app

    return TestClient(create_app(seeded_rt))
