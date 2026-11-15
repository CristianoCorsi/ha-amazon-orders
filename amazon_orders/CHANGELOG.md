# Changelog

## 0.1.5

- Fix sign-in failing with `DuplicateDeviceName`: each registration now uses a unique device name, shown in Amazon's device list as `Home Assistant Amazon Orders XXXX`.

## 0.1.4

- Log Amazon's own error code and message when the device registration is refused.

## 0.1.3

- Sign-in failures are now logged with the step that failed (relay, device registration, session activation), without codes, cookies or tokens.

## 0.1.2

- Sign-in works over Tailscale: `100.64.0.0/10` addresses and `*.ts.net` MagicDNS names are used directly for the login link (tailnet traffic is encrypted end to end).

## 0.1.1

- Sign-in link works when Home Assistant is opened through a public name (DuckDNS, Nabu Casa, reverse proxy): the add-on now uses Home Assistant's LAN address for the login page, or a local DNS name that resolves to the LAN.
- The sign-in panel shows the reason when sign-in cannot start, and the log records it.

## 0.1.0

- First release (early development).
- Read-only import of Amazon order history (amazon.it), with careful sync presets and year-by-year backfill.
- Return and 2-year warranty deadlines, spending statistics, CSV export.
- Sign-in through a login page served by the add-on (port 8098).
- Home Assistant sensors (MQTT discovery), `amazon_orders_deadline` events and an ICS calendar feed.
- Web UI in the sidebar via Ingress (English and Italian).
