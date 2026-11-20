"""amazon-orders returns each product twice on detail pages (shipment copy + order.items copy): store it once."""

import copy
from datetime import date, datetime

from amazon_orders_ha import repo
from amazon_orders_ha.db import Database, connect, migrate
from amazon_orders_ha.mapping import map_order

from .conftest import fake_order

NOW = datetime(2026, 11, 15, 12)


def twin_order(number="111-0000009-0000009"):
    o = fake_order(number, date(2026, 10, 20), ["Lamp", "Cable"], detailed=True, return_date=date(2026, 11, 20))
    shipment_copies = []
    for it in o.items:
        twin = copy.copy(it)  # distinct object, as the library builds it
        twin.price = None
        twin.seller = None
        twin.return_eligible_date = None
        shipment_copies.append(twin)
    o.shipments[0].items = shipment_copies
    return o


def test_mapping_merges_shipment_and_order_copies():
    row = map_order(twin_order(), True, NOW.date())
    assert len(row.items) == 2
    for it in row.items:
        assert it.price is not None and it.return_eligible_date == date(2026, 11, 20)
        assert it.delivered_date is not None and it.item_key.endswith("#0")


def test_one_warranty_deadline_per_item(tmp_path):
    c = Database(tmp_path / "t.db").connect()
    repo.upsert_order(c, map_order(twin_order(), True, NOW.date()), NOW)
    warranties = repo.list_deadlines(c, NOW.date(), kind="warranty")["deadlines"]
    assert len(warranties) == 2
    assert len({d["item"]["id"] for d in warranties}) == 2


def test_migration_v2_merges_existing_duplicates_and_keeps_annotations(tmp_path):
    path = tmp_path / "old.db"
    c = connect(path)
    # Build a v1 database containing the duplicated rows written by earlier versions.
    from amazon_orders_ha import db as dbmod

    c.executescript(f"BEGIN;\n{dbmod.SCHEMA_V1}\nCOMMIT;")
    c.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
    c.execute("INSERT INTO schema_version(version) VALUES (1)")
    c.execute("INSERT INTO orders(order_number, placed_date, cancelled, first_seen_at, updated_at)"
              " VALUES ('X-1', '2026-10-20', 0, '2026-10-20', '2026-10-20')")
    c.execute("INSERT INTO items(order_number, item_key, asin, title, price, delivered_date)"
              " VALUES ('X-1', 'B0AAA#0', 'B0AAA', 'Lamp', NULL, '2026-10-22')")
    c.execute("INSERT INTO items(order_number, item_key, asin, title, price, seller, return_eligible_date)"
              " VALUES ('X-1', 'B0AAA#1', 'B0AAA', 'Lamp', 19.9, 'Shop', '2026-11-20')")
    drop_id = c.execute("SELECT id FROM items WHERE item_key='B0AAA#1'").fetchone()[0]
    c.execute("INSERT INTO item_state(item_id, status, note) VALUES (?, 'keep', 'mine')", (drop_id,))
    migrate(c)
    rows = c.execute("SELECT * FROM items WHERE order_number='X-1'").fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert (r["item_key"], r["price"], r["seller"]) == ("B0AAA#0", 19.9, "Shop")
    assert (r["return_eligible_date"], r["delivered_date"]) == ("2026-11-20", "2026-10-22")
    state = c.execute("SELECT status, note FROM item_state WHERE item_id=?", (r["id"],)).fetchone()
    assert tuple(state) == ("keep", "mine")
