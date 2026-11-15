# ha-amazon-orders

A read-only Home Assistant add-on for your Amazon order history. Search your orders, see when return windows and the 2-year legal warranty expire, compute spending statistics, and get reminders as Home Assistant notifications.

Built on top of [`amazon-orders`](https://github.com/alexdlaird/amazon-orders).

> **Status: early development.** The underlying library has been validated against amazon.it; the add-on itself is not usable yet.

## Features

Planned for the first release:

- **Order search**: full-text search over orders and items, with filters by date, seller and status.
- **Return deadlines**: the return window date reported by Amazon for each item.
- **Warranty deadlines**: the 2-year legal warranty end date, computed from the delivery date (or the order date when the delivery date is not available, so the deadline is never later than the real one).
- **Spending statistics**: totals by year, month and seller, plus CSV export.
- **Home Assistant entities**: sensors and a deadlines calendar published via MQTT discovery, ready for automations and reminders.
- **Web UI**: search and statistics in the Home Assistant sidebar via Ingress.
- **Read-only**: the add-on never places, changes or cancels orders.

## Compatibility

| Component | Last tested | Date |
|---|---|---|
| Amazon site | amazon.it (pages read in English) | 2026-11-15 |
| `amazon-orders` | 6.0.0 | 2026-11-15 |
| Sign-in | browser sign-in (`login --browser`, Playwright + Chromium) | 2026-11-15 |
| Target hardware | Raspberry Pi 5 (aarch64), Home Assistant OS | not tested yet |

Other Amazon sites that offer English pages should work through the library's `domain` option, but they are untested here.

## Setup

The add-on is not published yet. Once it is, installation will follow the usual flow:

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and add this repository URL.
2. Install **Amazon Orders** and start it.
3. Open the add-on page from the sidebar and sign in to Amazon.

Requirements:

- Home Assistant OS or Supervised (add-ons are not available on Container or Core installs).
- An MQTT broker (for example the Mosquitto add-on) for the Home Assistant entities.

### Development

To try the underlying library locally:

```bash
python3 -m venv .venv
.venv/bin/pip install "amazon-orders[browser]==6.0.*"
```

`~/.config/amazonorders/config.yml`:

```yaml
domain: amazon.it
browser: chromium
browser_executable_path: /usr/bin/chromium   # path of your Chromium binary
warn_on_missing_required_field: true         # needed to parse cancelled orders
```

```bash
.venv/bin/amazon-orders login --browser
.venv/bin/amazon-orders orders --last-30-days --full-details --output json
```

Session cookies are stored in `~/.config/amazonorders/`. Never commit them.

## Disclaimer

Amazon offers no public API for customers' orders. This project reads the same pages the Amazon website shows you when you are signed in, so it can break whenever Amazon changes its website, and automated access may be against Amazon's Conditions of Use. For personal use, at your own risk. Not affiliated with or endorsed by Amazon.
