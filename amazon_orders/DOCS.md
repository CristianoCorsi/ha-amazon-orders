# Amazon Orders add-on — Documentation

Read-only view of your Amazon order history inside Home Assistant: search, return
deadlines, 2-year warranty deadlines, spending statistics, sensors, events and a
calendar feed. The add-on never places, changes or cancels anything on Amazon.

> **Status: early development.** Only amazon.it is tested.

## Installation

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add
   `https://github.com/CristianoCorsi/ha-amazon-orders`.
2. Install **Amazon Orders**, then **Start**. Enable **Show in sidebar** if you want the panel.
3. For the sensors, install an MQTT broker (for example the Mosquitto add-on). Without MQTT
   the UI, events and calendar still work.

Images are pre-built for aarch64 and amd64 and pulled from GHCR.

## First sign-in

Amazon has no public API for orders, so the add-on signs in as you, on your behalf.
The sign-in page is served by the add-on itself on a separate **login port** (default `8098`)
and relays Amazon's own sign-in pages. You type your password and one-time code in your
own browser; the add-on keeps only the resulting session cookies in its private `/data` folder.

1. Open the add-on panel and go to **Settings / Sync → Sign in**.
2. Open the link shown there **from a device on your home network** (`http://<home-assistant-ip>:8098/...`).
3. Complete the Amazon sign-in (password, OTP, captcha if asked).
4. The panel shows the account as signed in and the first sync starts.

Why a separate port on the LAN? The sign-in must run on a page whose address Amazon's
cookies and redirects can follow; the Home Assistant Ingress iframe cannot do that reliably.
Treat the port as temporary: open the link only while signing in, and do not forward it
through your router. If the link shows a wrong host name (for example behind a reverse
proxy), set **Sign-in host** in the configuration to the name or IP your browser uses.
If the session expires, the add-on fires `amazon_orders_auth_required` and the
`binary_sensor.amazon_orders_auth_required` turns on; sign in again the same way.

## Configuration

| Option | Default | Notes |
| --- | --- | --- |
| `sync_preset` | `careful` | `careful`: slow, long random pauses, protects your account. `moderate`: faster. |
| `recent_refresh_hours` | `6` | How often recent orders are re-read. |
| `backfill_until_year` | empty | Oldest year to import; empty imports everything. |
| `return_thresholds` | `[7, 2, 0]` | Days before a return deadline at which an event fires. |
| `warranty_thresholds` | `[180, 90, 60, 30, 14, 5]` | Same, for warranties. |
| `default_warranty_months` | `24` | Overridable per item in the UI. |
| `mqtt` | empty | Only if the Mosquitto add-on is not used: `host`, `port`, `username`, `password`. |
| `domain` | `amazon.it` | Optional, advanced. Only amazon.it is tested. |
| `log_level` | `info` | Cookies, passwords and codes are never logged. |
| `login_port` | `8098` | Port used in the sign-in link. Keep it equal to the host port of `8098/tcp` in the **Network** section; change both together. |
| `login_host` | empty | Host name/IP used in the sign-in link; empty = auto. |

### Sync presets, backfill and cache

- Recent orders are refreshed every `recent_refresh_hours`. Older orders are imported by a
  **backfill** that works one year at a time, newest first, with pauses between requests; on
  Amazon errors or captchas it backs off (status `cooldown`) and resumes later. Progress is
  shown in the panel and in `sensor.amazon_orders_backfill_progress`.
- **Purge cache** (Settings / Sync, with confirmation; scope: everything, one year or one
  order) marks the stored order data as stale so it is fetched again from Amazon at the next
  sync. Your local item states, notes, warranty overrides and already-fired reminders are
  never touched, and nothing on Amazon changes.

## Home Assistant entities

With MQTT, a device **Amazon Orders** is created:

| Entity | Meaning |
| --- | --- |
| `sensor.amazon_orders_returns_open` | Items still returnable (attribute: next 10 with deadline) |
| `sensor.amazon_orders_next_return_deadline` | Nearest return deadline |
| `sensor.amazon_orders_warranties_expiring_90d` | Warranties ending within 90 days |
| `sensor.amazon_orders_next_warranty_deadline` | Nearest warranty deadline |
| `sensor.amazon_orders_spend_this_month` / `_this_year` | Spending in EUR |
| `sensor.amazon_orders_sync_status` | idle, syncing, backfilling, cooldown, auth_required, error |
| `sensor.amazon_orders_backfill_progress` | Backfill progress |
| `binary_sensor.amazon_orders_auth_required` | On when you must sign in again |

### Events

The add-on fires `amazon_orders_deadline` once per item, kind and threshold, with this data:

```json
{
  "kind": "return",
  "threshold_days": 2,
  "days_left": 2,
  "deadline": "2026-12-01",
  "order_number": "123-1234567-1234567",
  "item_id": "42",
  "title": "Example product",
  "asin": "B000000000",
  "price": 19.99,
  "seller": "Example seller",
  "item_url": "https://www.amazon.it/dp/B000000000",
  "order_url": "https://www.amazon.it/gp/your-account/order-details?orderID=123-1234567-1234567"
}
```

`kind` is `return` or `warranty`. The add-on also fires `amazon_orders_auth_required` and
`amazon_orders_sync_error`.

Example automation:

```yaml
alias: Amazon return deadline reminder
triggers:
  - trigger: event
    event_type: amazon_orders_deadline
    event_data:
      kind: return
actions:
  - action: notify.notify
    data:
      title: "Return window closing ({{ trigger.event.data.days_left }} days)"
      message: >-
        {{ trigger.event.data.title }} ({{ trigger.event.data.seller }}),
        last day {{ trigger.event.data.deadline }}.
      data:
        url: "{{ trigger.event.data.order_url }}"
```

## Calendar (ICS)

The add-on serves an all-day-event calendar with return and warranty deadlines at
`/calendar.ics` on its internal port `8099`. Add it with **Settings → Devices & services →
Add integration → Remote Calendar**, using:

```
http://<addon-hostname>:8099/calendar.ics
```

The add-on hostname is `<repository-hash>-amazon-orders` (the slug with `_` turned into `-`):

- installed from the GitHub repository: **`1f24758f-amazon-orders`**, i.e.
  `http://1f24758f-amazon-orders:8099/calendar.ics`. The hash is the first 8 hex digits of the
  SHA-1 of the lowercase repository URL, and is also visible on the add-on **Info** page
  (the "Hostname" field) and in the add-on URL (`/hassio/addon/1f24758f_amazon_orders`);
- installed as a local add-on (copied into `/addons`): `local-amazon-orders`.

Use the hostname, not `localhost`: Home Assistant Core runs in a different container.
The feed is only reachable on the internal Docker network; it is not exposed on your LAN.

## Privacy

- Everything stays on your Home Assistant: orders in a SQLite database and Amazon session
  cookies in the add-on's `/data` folder (included in add-on backups, so protect your backups).
- Passwords and one-time codes are typed into Amazon's page and are never stored or logged.
- Product images are fetched from Amazon's servers and cached locally.
- No telemetry; the only outgoing connections are to Amazon and to your Home Assistant.
- Remove the stored session at any time with **Sign out** (Settings / Sync), or by uninstalling the add-on.

## Disclaimer

Amazon offers no public API for order history. The add-on reads the pages you can see when
signed in, so it can break when Amazon changes its website, and automated access may be
against Amazon's Conditions of Use. Use at your own risk. Not affiliated with or endorsed by Amazon.
