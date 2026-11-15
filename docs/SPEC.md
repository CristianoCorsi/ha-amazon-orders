# ha-amazon-orders — Technical Specification (v0.1)

Shared contract for everyone working on this repository. If an implementation needs to deviate,
update this file in the same change and explain why.

## 1. Goal

A read-only Home Assistant add-on for Amazon order history (amazon.it first):
search, return deadlines, 2-year warranty deadlines, spending statistics, and Home Assistant
entities/events/calendar so the user can write their own automations.

The add-on never places, changes or cancels anything on Amazon. Local annotations (item state,
notes, warranty overrides) live only in the add-on database.

## 2. Repository layout

```
repository.yaml                 # HA add-on repository manifest
amazon_orders/                  # the add-on (HA build context)
  config.yaml  build.yaml  Dockerfile  DOCS.md  CHANGELOG.md  translations/
  rootfs/                       # s6 services, run scripts
  backend/                      # Python package `amazon_orders_ha` (FastAPI)
    pyproject.toml
    src/amazon_orders_ha/
    tests/
  frontend/                     # SvelteKit app, built to static files served by the backend
docs/                           # SPEC.md, design notes
.github/workflows/              # CI: lint, tests, multi-arch image build to GHCR
```

## 3. Stack

- Backend: Python 3.12+, FastAPI, Uvicorn, SQLite (stdlib `sqlite3` or SQLAlchemy 2 core; keep it
  simple), APScheduler or an asyncio loop for jobs, `amazon-orders==6.0.*` (pin minor only),
  `paho-mqtt` for MQTT discovery, `httpx` for the HA Core API through the Supervisor proxy.
- Frontend: SvelteKit + `@sveltejs/adapter-static` (SPA, `fallback: index.html`), TypeScript,
  no heavy UI kit. Charts: a small library (e.g. `layercake` or hand-written SVG). pnpm.
- Data dir inside the add-on: `/data` (SQLite at `/data/amazon_orders.db`, Amazon session
  cookies at `/data/amazonorders/`). Never log cookies, passwords, OTPs, addresses or card digits.

## 4. Amazon access (library facts verified 2026-11-15)

- `amazon-orders` reads amazon.it in English with `domain: amazon.it`.
- Required config: `warn_on_missing_required_field: true` (cancelled orders have no grand total).
- Plain `login()` is blocked by a JS challenge; sessions come from a browser sign-in (see §9).
- Paging: `AmazonOrders.get_orders_page(year=..., cursor=..., limit=...)` returns one batch plus a
  cursor; use it for throttled backfill. Details: `AmazonOrders.get_order(order_id)` = 1 request.
- `Item.return_eligible_date` is only present on recent orders. Real return windows range from
  15 to 85 days, so never assume +30 when Amazon provides a date.
- `Shipment.delivery_status` looks like `"Delivered 28 October"` (no year) on recent orders and
  is often `None` on old ones. Infer the year from the order date (delivery >= placed date).

## 5. Sync engine

All Amazon requests go through ONE throttled request gate (a single worker, never parallel).

Presets (option `sync_preset`, default `careful`):

| preset | delay between requests | active hours | notes |
|---|---|---|---|
| careful | 20–40 s random jitter | 01:00–06:00 for backfill; recent refresh any time | default |
| moderate | 5–10 s random jitter | any time | |

Jobs:

1. **Recent refresh** every `recent_refresh_hours` (default 6): history pages for the last
   60 days (`time_filter`/year), upsert orders; fetch full details only for orders that are new,
   not yet detailed, or whose list-level fingerprint (status text, totals, item count) changed.
2. **Backfill** (backwards): from the current year down to `backfill_until_year` (option; empty =
   until Amazon returns no more orders). Persist a cursor (year + library cursor/start index) so it
   resumes after restarts. Each order: list entry, then a throttled `get_order` for full details.
   Can be paused/resumed from the UI.
3. **Cache purge** (manual, from the UI): scope `all` | `year:<YYYY>` | `order:<id>`. Purge marks
   rows stale (`details_fetched_at = NULL`, fingerprint cleared) so the next jobs refetch them.
   Local annotations (§7) are NEVER deleted by a purge.

Backoff: on HTTP 429/503, captcha/JS challenge, or parse errors on more than 3 consecutive
orders → stop the gate, record the error, exponential cooldown (15 min, doubled up to 12 h),
and expose it in `/api/status`. On an expired session → state `auth_required`, stop all jobs.

## 6. Data model (SQLite)

```
orders(order_number PK, placed_date DATE, grand_total REAL NULL, subtotal REAL NULL,
       shipping_total REAL NULL, estimated_tax REAL NULL, refund_total REAL NULL,
       gift_card REAL NULL, coupon_savings REAL NULL, cancelled BOOL, payment_method TEXT NULL,
       details_link TEXT, list_fingerprint TEXT, details_fetched_at TIMESTAMP NULL,
       first_seen_at TIMESTAMP, updated_at TIMESTAMP, raw_json TEXT)
shipments(id PK, order_number FK, shipment_key TEXT, status_text TEXT NULL,
          delivered_date DATE NULL, tracking_link TEXT NULL)
items(id PK, order_number FK, asin TEXT NULL, title TEXT, price REAL NULL, quantity INT NULL,
      seller TEXT NULL, image_link TEXT NULL, link TEXT NULL,
      return_eligible_date DATE NULL, delivered_date DATE NULL)   -- denormalised from shipment
item_state(item_id PK FK, status TEXT CHECK(status IN ('none','keep','to_return','returned')),
           note TEXT, warranty_until_override DATE NULL, warranty_months_override INT NULL,
           updated_at TIMESTAMP)
fired_events(item_id, kind TEXT ('return'|'warranty'), threshold_days INT, deadline DATE,
             fired_at TIMESTAMP, PRIMARY KEY(item_id, kind, threshold_days, deadline))
sync_state(key PK, value JSON)   -- backfill cursor, last runs, cooldown, last error
```

Do not store recipient name/address or card last 4 digits (drop them before `raw_json`).
FTS5 virtual table over `items.title`, `items.seller`, `orders.order_number` for search.

## 7. Deadlines

- `return_deadline` = `items.return_eligible_date`; NULL if Amazon gave none (UI shows "unknown"
  for recent orders, "closed" when the order is older than 90 days).
- `warranty_start` = `delivered_date` if known, else `placed_date` (earlier → safe side).
- `warranty_deadline` = `warranty_until_override` if set, else `warranty_start +
  (warranty_months_override or 24) months`.
- Items with status `returned`, or in cancelled orders, have no active deadlines.
- Thresholds (options): `return_thresholds: [7, 2, 0]`, `warranty_thresholds: [180, 90, 60, 30, 14, 5]`.

## 8. Home Assistant interface

The user writes their own automations; the add-on only exposes data.

1. **Events** via the Supervisor Core API (`homeassistant_api: true`,
   `POST http://supervisor/core/api/events/amazon_orders_deadline`), fired once per
   `(item, kind, threshold, deadline)` (dedup through `fired_events`), checked at least hourly:
   `{kind, threshold_days, days_left, deadline, order_number, item_id, title, asin, price,
   seller, item_url, order_url}`.
   Also `amazon_orders_auth_required` and `amazon_orders_sync_error`.
2. **Sensors** via MQTT discovery (broker from `services: mqtt:need` → Supervisor service
   discovery; fallback to manual options): device "Amazon Orders" with
   - `sensor.amazon_orders_returns_open` (count; attributes: list of next 10 with deadline)
   - `sensor.amazon_orders_next_return_deadline` (timestamp/date)
   - `sensor.amazon_orders_warranties_expiring_90d` (count)
   - `sensor.amazon_orders_next_warranty_deadline` (date)
   - `sensor.amazon_orders_spend_this_month`, `sensor.amazon_orders_spend_this_year` (EUR)
   - `sensor.amazon_orders_sync_status` (idle/syncing/backfilling/cooldown/auth_required/error)
   - `sensor.amazon_orders_backfill_progress` (% or orders count)
   - `binary_sensor.amazon_orders_auth_required`
3. **Calendar**: ICS feed at `GET /calendar.ics` (all-day events: return and warranty deadlines;
   description with order and item link). Users add it with HA's Remote Calendar integration
   using the add-on's internal hostname. Document the exact URL in DOCS.md.

## 9. Authentication (prototype in progress, see docs/auth-design.md when it exists)

Primary: **login proxy** reachable from the HA UI. The user opens a link from the add-on page,
signs in on Amazon's own pages relayed through the add-on (password + OTP typed by the user in
their browser), and the proxy captures the session cookies (pattern of `authcaptureproxy` used
by Alexa Media Player). Bonus if feasible: register a virtual device (like the Amazon mobile apps)
to get a refresh token that renews web cookies without user interaction.

Fallback: **remote browser** (Chromium + noVNC) shown inside the Ingress page.

The backend exposes:
`GET /api/auth/status` → `{state: 'ok'|'auth_required'|'in_progress', method, expires_hint}`,
`POST /api/auth/start` → `{url}` (where to send the user), `POST /api/auth/logout`.

## 10. HTTP API (backend → frontend)

All paths are relative (Ingress serves the app under a dynamic prefix); the frontend must call
`api/...` relative to the document base, never `/api/...`.

```
GET   api/status                     auth state, job states, backfill progress, cooldown, last error, counts
GET   api/orders?q&from&to&seller&status&min&max&sort&page&page_size
GET   api/orders/{order_number}      order + shipments + items + item_state + deadlines
GET   api/items?q&...same filters    item-level search (each item with order summary and deadlines)
PATCH api/items/{id}/state           {status?, note?, warranty_until_override?, warranty_months_override?}
GET   api/deadlines?kind=return|warranty|all&within_days=N&include_closed=false
GET   api/stats/summary?year         totals: spend, orders, items, avg order, shipping paid, refunds,
                                     cancelled, gift card used, coupon savings
GET   api/stats/monthly?from&to      spend + orders per month (for charts, year-over-year)
GET   api/stats/sellers?year&limit   spend and count per seller
GET   api/stats/top-items?year&limit most expensive items
GET   api/stats/recurring?limit      ASINs bought more than once: count, first/last date, price min/max/last
GET   api/stats/returns?year         returns/refunds count and amount, return rate
GET   api/stats/weekday              orders per weekday and hour-free month heatmap data
GET   api/export.csv?...filters      items joined with orders
POST  api/sync/recent                trigger now
POST  api/sync/backfill              {action: 'start'|'pause'}
POST  api/cache/purge                {scope: 'all'|'year:YYYY'|'order:ID'}
GET   api/settings                   read-only view of add-on options relevant to the UI
GET   calendar.ics
```

Money is returned as numbers in the order currency plus a top-level `currency` (EUR for .it).
Dates are ISO `YYYY-MM-DD`. Errors: `{error: {code, message}}`.

### 10.1 Response shapes (added by the backend implementation; additive, no path changes)

- Errors: `{error: {code, message}}`; codes `not_found` (404), `validation_error` (422),
  `auth_unavailable` (501), `internal_error` (500). Unknown `api/...` paths return the same JSON 404.
- List filters (`api/orders`, `api/items`, `api/export.csv`): `q` (FTS, accent-insensitive, prefix match, over title,
  seller, order number), `from`/`to` (placed date, ISO), `seller` (exact, case-insensitive),
  `status` (`none|keep|to_return|returned|cancelled`), `min`/`max` (order grand total for orders, item price for
  items), `sort` (`date_desc` default, `date_asc`, `total_desc|total_asc` = `price_*`, `title_asc` items only),
  `page` (>=1), `page_size` (1..200, default 50).
- `api/orders` → `{orders: [{order_number, placed_date, grand_total, refund_total, cancelled,
  status: delivered|in_progress|cancelled|unknown, details_link, has_details, item_count,
  items: [{id, title, asin, price, image_link, seller, status}]}], total, page, page_size, currency}`.
- `api/items` → `{items: [Item], total, page, page_size, currency}` where
  `Item = {id, order_number, asin, title, price, quantity, seller, image_link, link, return_eligible_date,
  delivered_date, state: {status, note, warranty_until_override, warranty_months_override},
  deadlines: {return: Deadline, warranty: Deadline}, order: {order_number, placed_date, cancelled, details_link}}`.
- `Deadline = {kind, deadline|null, days_left|null, state: open|closed|unknown|none, source: amazon|override|computed|null}`.
  `unknown` = no Amazon return date on a recent order; `none` = returned/cancelled (or return `keep`).
- `api/orders/{n}` → `{order: {...columns, status}, shipments: [{shipment_key, status_text, delivered_date,
  tracking_link}], items: [Item], currency}`.
- `PATCH api/items/{id}/state` → the updated `Item`. Omitted fields are unchanged; explicit `null` clears an override.
- `api/deadlines` → `{deadlines: [Deadline & {item: {id,title,asin,price,seller,image_link,link,order_number},
  order: {...}, status}], total, today}` sorted by deadline; `unknown`/`none` entries are never listed;
  `include_closed=true` adds `closed` ones. `within_days` filters open ones by `days_left`.
- `api/stats/*`: `summary` → `{year, currency, spend, orders, items, avg_order, shipping_paid, refunds, cancelled,
  gift_card_used, coupon_savings}`; `monthly` → `{months: [{month: 'YYYY-MM', spend, orders}]}` (zero-filled, default
  last 36 months); `sellers` → `{sellers: [{seller, spend, items, orders}]}`; `top-items` → `{items: [...]}`;
  `recurring` → `{recurring: [{asin, title, count, first_date, last_date, price_min, price_max, price_last,
  total_spent, image_link}]}`; `returns` → `{returned_items, returned_amount, refund_orders, refund_amount,
  to_return_items, items, return_rate}`; `weekday` → `{weekdays: [{weekday 0=Mon, orders}], months: [{month, orders}],
  heatmap: [{weekday, month, orders}]}`. Cancelled orders are excluded from spend/orders/items.
- `POST api/sync/recent` → `{queued: true}`; `POST api/sync/backfill` → `{status: running|paused|done, year, processed}`;
  `POST api/cache/purge` → `{scope, purged}`.
- `api/status` → `{state: idle|syncing|backfilling|cooldown|auth_required|error, auth, job, preset, backfill: {status,
  year, processed, history_done, percent|null, window_open, next_window, until_year, orders_detailed, orders_stale},
  cooldown|null, last_error|null, last_recent, next_recent_at, counts, currency, version, ha}`.
- The server injects `<base href="{X-Ingress-Path}/">` into `index.html` so relative URLs work under Ingress.
- Item `status = keep` means "decided to keep": it suppresses return deadlines/events (warranty is unaffected).
- Money fields `gift_card`, `coupon_savings`, `refund_total` are stored as positive magnitudes.

## 11. Add-on options (config.yaml)

```
sync_preset: careful            # careful | moderate
recent_refresh_hours: 6
backfill_until_year: ""         # empty = everything
return_thresholds: [7, 2, 0]
warranty_thresholds: [180, 90, 60, 30, 14, 5]
default_warranty_months: 24
mqtt: {host, port, username, password}   # optional; default from Supervisor discovery
advanced:
  domain: amazon.it             # hidden in UI as advanced; only amazon.it is tested
log_level: info
```

Arch: `aarch64`, `amd64`. Ingress enabled, panel icon `mdi:package-variant-closed`.
Base image: Debian-based (Playwright/Chromium do not run on Alpine/musl).

## 12. Frontend

- Look: integrated with Home Assistant, "Material 3 revisited": HA's own colors and light/dark mode,
  but more refined (spacing, typography, motion, empty states). Must look excellent on a phone in
  the HA Companion app and on desktop.
- Theme: the Ingress iframe is same-origin with HA. Read HA CSS variables from
  `window.parent.document.documentElement` / `home-assistant` element (`--primary-color`,
  `--primary-background-color`, `--card-background-color`, `--primary-text-color`, ...), and the
  dark mode flag; fall back to `prefers-color-scheme`. Re-read on theme change.
- Language: English + Italian (i18n). Default from HA (`hass.language` from the parent
  `home-assistant` element), fallback `navigator.language`, then English. User override stored locally.
- Screens: Overview (deadlines that need attention, spend this month/year, sync status),
  Orders (search + filters + infinite list, product images), Order/item detail (deadlines, local
  state, note, warranty override), Deadlines (returns / warranties timeline), Statistics
  (charts from §10), Settings/Sync (auth, sync status, backfill progress, cache purge with
  confirmation, export CSV, ICS URL).
- Routing must work under an unknown path prefix (hash routing or relative base).
- Accessibility: keyboard navigation, focus rings, contrast AA, `prefers-reduced-motion`.

## 13. Quality

- Backend: `ruff`, `pytest`; no test may hit Amazon. Use synthetic fixtures (fake orders with
  made-up names/IDs), never real personal data in the repo.
- Frontend: `svelte-check`, `vitest` for logic (theme, i18n, formatting), Playwright smoke test
  optional.
- Commit messages in English, small commits.
