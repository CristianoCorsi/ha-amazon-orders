"""SQLite schema, migrations-lite and connection helpers (SPEC §6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE orders(
  order_number TEXT PRIMARY KEY,
  placed_date TEXT,
  grand_total REAL, subtotal REAL, shipping_total REAL, estimated_tax REAL,
  refund_total REAL, gift_card REAL, coupon_savings REAL,
  cancelled INTEGER NOT NULL DEFAULT 0,
  payment_method TEXT,
  details_link TEXT,
  list_fingerprint TEXT,
  details_fetched_at TEXT,
  first_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  raw_json TEXT
);
CREATE INDEX idx_orders_placed ON orders(placed_date);

CREATE TABLE shipments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_number TEXT NOT NULL REFERENCES orders(order_number) ON DELETE CASCADE,
  shipment_key TEXT NOT NULL,
  status_text TEXT,
  delivered_date TEXT,
  tracking_link TEXT,
  UNIQUE(order_number, shipment_key)
);

CREATE TABLE items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_number TEXT NOT NULL REFERENCES orders(order_number) ON DELETE CASCADE,
  item_key TEXT NOT NULL,
  asin TEXT, title TEXT NOT NULL, price REAL, quantity INTEGER, seller TEXT,
  image_link TEXT, link TEXT,
  return_eligible_date TEXT, delivered_date TEXT,
  UNIQUE(order_number, item_key)
);
CREATE INDEX idx_items_asin ON items(asin);
CREATE INDEX idx_items_order ON items(order_number);

CREATE TABLE item_state(
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'none' CHECK(status IN ('none','keep','to_return','returned')),
  note TEXT NOT NULL DEFAULT '',
  warranty_until_override TEXT,
  warranty_months_override INTEGER,
  updated_at TEXT
);

CREATE TABLE fired_events(
  item_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('return','warranty')),
  threshold_days INTEGER NOT NULL,
  deadline TEXT NOT NULL,
  fired_at TEXT NOT NULL,
  PRIMARY KEY(item_id, kind, threshold_days, deadline)
);

CREATE TABLE sync_state(key TEXT PRIMARY KEY, value TEXT);

CREATE VIRTUAL TABLE search_fts USING fts5(
  order_number, title, seller, item_id UNINDEXED, tokenize='unicode61 remove_diacritics 2'
);
"""

# Each migration is an SQL script upgrading from version i to i+1 (applied in one transaction).
# v2: merge the duplicated item rows created by parsing a product both in its shipment and in order.items
# (keys "<base>#0" = shipment copy, "<base>#1" = order copy, no "#2"). Annotations and fired events are kept.
SCHEMA_V2 = """
CREATE TEMP TABLE dup AS
SELECT a.id AS keep_id, b.id AS drop_id FROM items a
JOIN items b ON b.order_number = a.order_number
 AND b.item_key = substr(a.item_key, 1, length(a.item_key) - 1) || '1'
WHERE a.item_key LIKE '%#0'
  AND NOT EXISTS (SELECT 1 FROM items c WHERE c.order_number = a.order_number
                  AND c.item_key = substr(a.item_key, 1, length(a.item_key) - 1) || '2')
  AND COALESCE(a.asin, '') = COALESCE(b.asin, '') AND a.title = b.title;

UPDATE items SET
  price = COALESCE(price, (SELECT b.price FROM items b JOIN dup d ON d.drop_id = b.id WHERE d.keep_id = items.id)),
  quantity = COALESCE(quantity, (SELECT b.quantity FROM items b JOIN dup d ON d.drop_id = b.id
                                 WHERE d.keep_id = items.id)),
  seller = COALESCE(seller, (SELECT b.seller FROM items b JOIN dup d ON d.drop_id = b.id WHERE d.keep_id = items.id)),
  image_link = COALESCE(image_link, (SELECT b.image_link FROM items b JOIN dup d ON d.drop_id = b.id
                                     WHERE d.keep_id = items.id)),
  link = COALESCE(link, (SELECT b.link FROM items b JOIN dup d ON d.drop_id = b.id WHERE d.keep_id = items.id)),
  return_eligible_date = COALESCE(return_eligible_date, (SELECT b.return_eligible_date FROM items b
                                  JOIN dup d ON d.drop_id = b.id WHERE d.keep_id = items.id)),
  delivered_date = COALESCE(delivered_date, (SELECT b.delivered_date FROM items b JOIN dup d ON d.drop_id = b.id
                                             WHERE d.keep_id = items.id))
WHERE id IN (SELECT keep_id FROM dup);

INSERT OR IGNORE INTO item_state(item_id, status, note, warranty_until_override, warranty_months_override, updated_at)
SELECT d.keep_id, s.status, s.note, s.warranty_until_override, s.warranty_months_override, s.updated_at
FROM item_state s JOIN dup d ON d.drop_id = s.item_id;
UPDATE OR IGNORE fired_events SET item_id = (SELECT keep_id FROM dup WHERE drop_id = fired_events.item_id)
WHERE item_id IN (SELECT drop_id FROM dup);
DELETE FROM fired_events WHERE item_id IN (SELECT drop_id FROM dup);
DELETE FROM search_fts WHERE item_id IN (SELECT drop_id FROM dup);
DELETE FROM items WHERE id IN (SELECT drop_id FROM dup);
DROP TABLE dup;
"""

MIGRATIONS: list[str] = [SCHEMA_V1, SCHEMA_V2]


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def migrate(conn: sqlite3.Connection) -> int:
    current = schema_version(conn)
    for i in range(current, len(MIGRATIONS)):
        try:
            conn.executescript(
                f"BEGIN;\n{MIGRATIONS[i]}\nINSERT INTO schema_version(version) VALUES ({i + 1});\nCOMMIT;"
            )
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return len(MIGRATIONS)


class Database:
    """Opens short-lived connections to one SQLite file (WAL), migrating on init."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(self.path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            migrate(conn)
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        return connect(self.path)
