"""Developer tooling: ``python -m amazon_orders_ha.dev seed`` fills a DB with SYNTHETIC orders.

Everything generated here is made up (titles, sellers, ASINs, order numbers); no Amazon access.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import repo
from .config import load_settings
from .db import Database
from .mapping import ItemRow, OrderRow, ShipmentRow
from .util import ts

SELLERS = ["Nordlicht Haushalt", "ByteBarn Store", "Casa Verde Srl", "Orbita Elettronica", "Pixel & Pepe",
           "Tramonto Libri", "Fornace Utensili", "MegaMoka Italia", "Quercia Outdoor", "Lumen Works",
           "Amazon", "Amazon", "Amazon", "Amazon"]
# (title, base price, recurring weight)
CATALOG = [
    ("Caffè in grani Miscela Aurora 1 kg", 14.9, 9), ("Filtri acqua per caraffa Brina (3 pz)", 17.5, 6),
    ("Capsule lavastoviglie Splendi 60 pz", 11.2, 6), ("Lettiera agglomerante Soffio 10 L", 8.4, 5),
    ("Batterie AA Voltix (16 pz)", 12.0, 5), ("Carta igienica Morbida 32 rotoli", 16.8, 5),
    ("Cavo USB-C Linea 2 m", 9.9, 1), ("Auricolari Bluetooth Echo Mini", 39.0, 1),
    ("Monitor 27'' Panorama QHD", 229.0, 1), ("Tastiera meccanica Clack 75", 74.9, 1),
    ("Mouse ergonomico Delta", 34.5, 1), ("Webcam Full HD Occhio", 45.0, 1),
    ("SSD portatile Rapido 1 TB", 89.0, 1), ("Hub USB-C 7 porte Nodo", 29.9, 1),
    ("Robot aspirapolvere Zefiro S3", 279.0, 1), ("Bollitore elettrico Vulcano 1,7 L", 32.0, 1),
    ("Friggitrice ad aria Croccante 5 L", 99.0, 1), ("Set coltelli da cucina Fornace (6 pz)", 54.0, 1),
    ("Padella antiaderente Granito 28 cm", 27.9, 1), ("Lampada da scrivania Lumen LED", 36.0, 1),
    ("Zaino impermeabile Quercia 25 L", 62.0, 1), ("Scarpe da trekking Cima (paio)", 98.0, 1),
    ("Giacca antipioggia Nebbia", 79.0, 1), ("Tenda da campeggio Aurora 3 posti", 149.0, 1),
    ("Libro: Il giardino sospeso (romanzo)", 16.0, 1), ("Libro: Cucinare con poco", 21.0, 1),
    ("Libro: Manuale di elettronica pratica", 34.0, 1), ("Trapano avvitatore Forza 18 V", 89.0, 1),
    ("Set bit e punte Precisione (120 pz)", 19.5, 1), ("Multiprese con interruttore Sicura 6 vie", 13.9, 1),
    ("Smart plug Wi-Fi Presa+ (4 pz)", 28.0, 1), ("Sensore temperatura Zigbee Termo", 15.0, 1),
    ("Router Wi-Fi 6 Ponte AX", 119.0, 1), ("Tablet 10'' Lavagna", 189.0, 1),
    ("Custodia tablet Guscio", 17.9, 1), ("Power bank 20000 mAh Riserva", 31.0, 1),
    ("Aspirapolvere a mano Piuma", 59.0, 1), ("Ventilatore a torre Brezza", 64.0, 1),
    ("Termosifone elettrico Tepore 2000 W", 49.0, 1), ("Bilancia da cucina Grammo", 14.5, 1),
    ("Macinacaffè manuale Mulino", 42.0, 1), ("Set lenzuola matrimoniali Sogno", 38.0, 1),
    ("Cuscino memory Nuvola", 29.0, 1), ("Valigia rigida Viaggio 66 cm", 84.0, 1),
    ("Fotocamera istantanea Scatto Mini", 72.0, 1), ("Cuffie over-ear Studio Q", 129.0, 1),
    ("Altoparlante portatile Eco Go", 45.0, 1), ("Stampante laser Tipo 30", 139.0, 1),
    ("Toner compatibile Tipo 30 (nero)", 24.5, 2), ("Risma carta A4 Bianca 500 fogli", 5.9, 3),
]
RETURN_WINDOWS = [15, 30, 30, 30, 30, 45, 60, 85]


def _asin(i: int) -> str:
    return f"B0SEED{i:04d}"[:10]


def _icon(title: str, i: int) -> str:
    hue = (i * 47) % 360
    letter = next((c for c in title if c.isalpha()), "?").upper()
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><rect width='120' height='120' "
           f"rx='14' fill='hsl({hue},45%,78%)'/><text x='60' y='78' font-size='54' text-anchor='middle' "
           f"font-family='sans-serif' fill='hsl({hue},45%,28%)'>{letter}</text></svg>")
    return "data:image/svg+xml," + quote(svg)


def _order_number(rng: random.Random, n: int) -> str:
    return f"999-{n:07d}-{rng.randrange(10**7):07d}"


def _make_order(rng: random.Random, today: date, placed: date, number: str, picks: list[int],
                forced: dict | None = None) -> tuple[OrderRow, list[tuple[int, str]]]:
    """Return an OrderRow and a list of (item_index, status) hints for item_state."""
    forced = forced or {}
    cancelled = forced.get("cancelled", rng.random() < 0.04)
    age = (today - placed).days
    items: list[ItemRow] = []
    shipments: list[ShipmentRow] = []
    seller = rng.choice(SELLERS)
    in_transit = age < 4 and "delivered_days" not in forced
    missing_delivery = forced.get("missing_delivery", (age > 700 and rng.random() < 0.25) or rng.random() < 0.04)
    ddays = forced.get("delivered_days", rng.randint(1, 6))
    delivered = None if (cancelled or in_transit or missing_delivery) else placed + timedelta(days=ddays)
    if delivered and delivered > today:
        delivered = None
    window = forced.get("window", rng.choice(RETURN_WINDOWS))
    have_return = (not cancelled) and delivered is not None and age <= 150 and not forced.get("no_return_date")
    subtotal = 0.0
    for idx in picks:
        title, price, _w = CATALOG[idx]
        price = round(price * rng.uniform(0.9, 1.12), 2)
        qty = 1 if price > 30 else rng.choice([1, 1, 2])
        subtotal += price * qty
        items.append(ItemRow(
            item_key=f"{_asin(idx)}#0", asin=_asin(idx), title=title, price=price, quantity=qty,
            seller=seller if idx % 3 else rng.choice(SELLERS), image_link=_icon(title, idx),
            link=f"https://www.amazon.it/dp/{_asin(idx)}",
            return_eligible_date=(delivered + timedelta(days=window)) if have_return else None,
            delivered_date=delivered, shipment_key="s0"))
    if cancelled:
        status_text = None
    elif delivered:
        status_text = f"Delivered {delivered.day} {delivered:%B}"
    else:
        status_text = None if missing_delivery else "Arriving soon"
    shipments.append(ShipmentRow("s0", status_text, delivered, None if age > 200 else "https://www.amazon.it/track/seed"))
    shipping = 0.0 if subtotal > 29 else 4.9
    total = None if cancelled else round(subtotal + shipping, 2)
    gift = round(min(total, 10.0), 2) if (total and rng.random() < 0.05) else None
    coupon = round(rng.choice([1.0, 2.0, 5.0]), 2) if (total and rng.random() < 0.07) else None
    row = OrderRow(
        order_number=number, placed_date=placed, grand_total=total,
        subtotal=None if cancelled else round(subtotal, 2), shipping_total=None if cancelled else shipping,
        estimated_tax=None if cancelled else round((total or 0) * 0.22 / 1.22, 2),
        refund_total=None, gift_card=gift, coupon_savings=coupon, cancelled=cancelled,
        payment_method=None if cancelled else rng.choice(["Visa", "Mastercard", "PayPal"]),
        details_link=f"https://www.amazon.it/your-orders/order-details?orderID={number}",
        fingerprint=f"seed-{number}", detailed=True, raw={"seed": True}, shipments=shipments, items=items)
    return row, []


def seed_database(db: Database, today: date | None = None, orders: int = 300, years: int = 6,
                  rng_seed: int = 7) -> dict[str, int]:
    today = today or date.today()
    rng = random.Random(rng_seed)
    now = datetime.combine(today, datetime.min.time()).replace(hour=3)
    conn = db.connect()
    weights = [w for _t, _p, w in CATALOG]
    start = today - timedelta(days=365 * years)
    specs: list[tuple[date, dict | None]] = []
    for _ in range(orders - 12):
        d = start + timedelta(days=rng.randrange((today - start).days + 1))
        if d.month in (11, 12) and rng.random() < 0.5:
            pass
        elif rng.random() < 0.12:
            d = d.replace(day=min(d.day, 28), month=11 if d.month < 11 else d.month)
        specs.append((d, None))
    # scripted orders: edge cases for the UI (deadline today / soon / closed, warranty near expiry, ...)
    specs += [
        (today - timedelta(days=9), {"delivered_days": 2, "window": 30}),          # return in 19 d
        (today - timedelta(days=28), {"delivered_days": 3, "window": 30}),         # return in ~5 d
        (today - timedelta(days=33), {"delivered_days": 3, "window": 30}),         # return today
        (today - timedelta(days=45), {"delivered_days": 3, "window": 30}),         # closed yesterday
        (today - timedelta(days=20), {"delivered_days": 3, "window": 85}),
        (today - timedelta(days=35), {"delivered_days": 2, "window": 15}),         # closed
        (today - timedelta(days=60), {"missing_delivery": True, "no_return_date": True}),  # unknown
        (today - timedelta(days=2), {}),                                           # in transit
        (today - timedelta(days=730 - 20), {"delivered_days": 2, "no_return_date": True}),  # warranty ~ 18 d
        (today - timedelta(days=730 - 100), {"delivered_days": 2, "no_return_date": True}),  # warranty ~ 98 d
        (today - timedelta(days=200), {"cancelled": True}),
        (today - timedelta(days=15), {"delivered_days": 2, "window": 30}),
    ]
    specs.sort(key=lambda x: x[0])
    recurring_idx = [i for i, w in enumerate(weights) if w > 1]
    returned_candidates: list[str] = []
    n_orders = 0
    for seq, (placed, forced) in enumerate(specs, start=1):
        k = rng.choices([1, 2, 3, 4], weights=[60, 25, 10, 5])[0]
        picks: list[int] = []
        while len(picks) < k:
            idx = rng.choices(range(len(CATALOG)), weights=weights)[0]
            if idx not in picks:
                picks.append(idx)
        if rng.random() < 0.25 and not forced:
            picks[0] = rng.choice(recurring_idx)
        row, _ = _make_order(rng, today, placed, _order_number(rng, seq), picks, forced)
        repo.upsert_order(conn, row, now)
        n_orders += 1
        if not row.cancelled and rng.random() < 0.06:
            returned_candidates.append(row.order_number)
    # local annotations
    ids = [r["id"] for r in conn.execute(
        "SELECT i.id FROM items i JOIN orders o ON o.order_number=i.order_number WHERE o.cancelled=0"
        " ORDER BY i.id")]
    for order_number in sorted(set(returned_candidates)):
        item = conn.execute("SELECT id, price FROM items WHERE order_number=? ORDER BY id LIMIT 1",
                            (order_number,)).fetchone()
        repo.patch_item_state(conn, item["id"], {"status": "returned", "note": "Reso (dati di esempio)"}, now)
        conn.execute("UPDATE orders SET refund_total=? WHERE order_number=?", (item["price"], order_number))
    for iid in rng.sample(ids, 12):
        repo.patch_item_state(conn, iid, {"status": rng.choice(["keep", "to_return"])}, now)
    for iid in rng.sample(ids, 8):
        note = rng.choice(["Regalo", "Garanzia estesa 3 anni", "Da controllare"])
        repo.patch_item_state(conn, iid, {"note": note}, now)
    for iid in rng.sample(ids, 4):
        repo.patch_item_state(conn, iid, {"warranty_months_override": rng.choice([36, 60])}, now)
    for iid in rng.sample(ids, 3):
        until = (today + timedelta(days=rng.randint(10, 400))).isoformat()
        repo.patch_item_state(conn, iid, {"warranty_until_override": until}, now)
    repo.set_state(conn, "backfill", {"status": "done", "year": today.year - years, "start_year": today.year,
                                      "cursor": None, "empty_years": 2, "year_orders": 0,
                                      "processed": n_orders, "history_done": True})
    repo.set_state(conn, "last_recent", {"at": ts(now).replace(" ", "T"), "seen": 0, "new": 0, "details": 0,
                                         "errors": 0})
    counts = repo.counts(conn)
    conn.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m amazon_orders_ha.dev")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("seed", help="fill a DB with synthetic orders")
    sp.add_argument("--data-dir", default=None)
    sp.add_argument("--orders", type=int, default=300)
    sp.add_argument("--years", type=int, default=6)
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--reset", action="store_true", help="delete the existing DB first")
    a = ap.parse_args(argv)
    data = a.data_dir or os.environ.get("AMAZON_ORDERS_DATA_DIR") or "./dev-data"
    settings = load_settings(data)
    if a.reset and settings.db_path.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
    db = Database(settings.db_path)
    c = db.connect()
    existing = repo.counts(c)["orders"]
    c.close()
    if existing:
        raise SystemExit(f"{settings.db_path} already has {existing} orders; use --reset")
    counts = seed_database(db, orders=a.orders, years=a.years, rng_seed=a.seed)
    print(f"Seeded {settings.db_path}: {counts}")
    print(f"Run: AMAZON_ORDERS_DATA_DIR={data} AMAZON_ORDERS_NO_SYNC=1 AMAZON_ORDERS_DEV_AUTH=1 "
          "python -m amazon_orders_ha")


if __name__ == "__main__":
    main()
