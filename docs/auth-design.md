# Amazon authentication design

Date: 2026-11-15. Status: local research prototype; human sign-in and HA Ingress validation pending.

## Decision

Keep the `AuthProvider` boundary independent of the interactive transport. Trial an `authcaptureproxy` login relay first, with the human entering their password and OTP. Keep a real Chromium session behind noVNC as the fallback when Amazon's JavaScript challenge cannot run through the relay. Do not promise that proxy login will fix this account's existing JavaScript blocker.

For production, serve the **trusted noVNC client and WebSocket under Ingress**, without exposing VNC or another host port. Do **not** serve unsandboxed Amazon HTML/JavaScript on Home Assistant's origin. The proxy experiment runs on its own loopback origin. A production relay needs either an isolated HTTPS origin with its own short-lived authorization or an opaque-origin sandbox that passes the phone/CAPTCHA tests below. Until that isolation works, choose the remote browser from the Ingress UI. This is a security gate, not a completed deployment feature.

Device registration is plausible enough for an explicit `--register-device` experiment. It is not the default: it changes the Amazon account by creating a virtual device, retains a more powerful long-lived secret, and has not been verified with this account.

## Evidence and limits

Project observations supplied on 2026-11-15: `amazon-orders==6.0.0` on amazon.it could not pass a JavaScript sign-in challenge using requests, before OTP. Its Playwright browser login, using system Chromium at `/usr/sbin/chromium`, succeeded. The account uses 2FA. This work made **no Amazon requests**, performed no login, and did not read any existing home-directory cookie/config files. The installed Python source was inspected, not its session data.

Research used GitHub API/curl and shallow source checkouts. Revisions inspected:

- Alexa Media Player: `b7b6c72ecb88bb8f144c7689ac9770a74d7f9c1f` (`dev`).
- authcaptureproxy: `710e058e8f5b14bf5d23102ed509380896f23b56` (`main`, version 1.3.9).
- LordHenry76/ha-amazon-orders: `77403bafd9184598e5ffaf032d30e4bcf5444bfc`.
- alexapy: PyPI 1.36.0 wheel, especially `alexaproxy.py` and `alexalogin.py`. AMP's fetched manifest still pins alexapy 1.35.0; these are different snapshots, not a claim that AMP uses 1.36.0.

### Alexa Media Player / authcaptureproxy

AMP creates an `AlexaProxy` for a config flow, registers Home Assistant HTTP views, sends the user to an external-step URL, then verifies the resulting login. This is a Core integration's HTTP-view mechanism; an add-on must supply its own transport rather than import those views.[1]

`AuthCaptureProxy` maintains an upstream `httpx.AsyncClient` cookie jar. Its aiohttp handler forwards form/AJAX requests and rewrites HTML URLs. A completion callback can inspect the upstream response and jar. The library accumulates submitted form data and emits sensitive DEBUG output; our adapter clears those dictionaries and response references after each request, disables dependency logging, and never persists passwords or OTPs.[2]

AlexaProxy recognizes the Amazon landing URL, transfers the upstream cookies to AlexaLogin, and captures an authorization code/access token. It can autofill credentials and TOTP when supplied by its caller. Our prototype deliberately omits autofill and TOTP secrets: Amazon's relayed forms collect the human's current OTP. Captcha also stays human-operated.[8]

The WAF interceptor rewrites cross-host CAPTCHA requests, injects JavaScript shims, and handles CVF challenge submission. It is targeted compatibility code, not a general browser emulator or a guarantee for every Akamai/JavaScript/passkey challenge.[3]

Maturity is mixed: this is the deployed AMP pattern, but authcaptureproxy's own package classifier remains Alpha.[1][4] Recent primary reports show why a fallback is necessary:

- AMP PR #3690, updated 2026-11-11, reports a live amazon.com login after enabling the WAF interceptor. That report does not validate amazon.it.[5]
- Proxy PR #51, updated 2026-11-08, fixes relative/query-only form actions and adds split-email/password `/ax/claim` fixtures.[6]
- AMP #3660, opened 2026-11-03 and now closed, reports password-stage failure before OTP on amazon.co.uk, including passkey-related behavior.[7]
- AMP #3538 remained open in the fetched results, updated 2026-11-07, reporting a login loop.[18]

### Device registration and Italian order history

alexapy registers an app-like device through `/auth/register`, using an access token or authorization code plus PKCE verifier. It tries the selected regional API and can fall back to `api.amazon.com`. Its cookie renewal posts a refresh token with `requested_token_type=auth_cookies` to `https://www.<site>/ap/exchangetoken/cookies`; `site=amazon.it` therefore targets Italian web cookies. It imports returned domain/path/expiry metadata into its jar.[8]

LordHenry76's implementation uses global `www.amazon.com` sign-in, PKCE scope `device_auth_access`, and `api.amazon.com/auth/register`. It renews via `api.amazon.com/auth/token` with `domain=www.amazon.it`, rather than alexapy's exchange endpoint. Its order client sends the renewed cookies to `/your-orders/orders?timeFilter=last30`, refreshes once on a sign-in redirect, and explicitly identifies amazon.it as its tested site.[9][10]

This is source-level evidence that these tokens are intended to unlock retail order history, not merely Alexa endpoints. It is **not a live verification here**. Access to `/your-orders`, `/your-orders/orders`, and legacy `/gp/css/order-history` may differ because Amazon can require fresh authentication for individual pages. The human must verify the library's current Italian list URL and, separately, the legacy route before relying on renewal.

The opt-in demo proxies the global PKCE login; only after the human completes it does it attempt registration and `/auth/token` exchange. It saves only refresh token, serial and domain to `device.json`, not customer metadata. Automatic renewal scheduling and deregistration are not implemented. If exchange fails after registration, the token/serial file remains so the device is identifiable; remove the device manually in Amazon after the experiment. LordHenry76 also labels its deregistration path unverified.[9]

### amazon-auth session injection

Installed versions inspected: `amazon-orders==6.0.0`, `amazon-auth==1.1.0`. `amazonorders.session.AmazonSession` subclasses the auth package's session. The modern jar is a JSON array of `{name,value,domain,path,secure,expires}` records; the loader also accepts a legacy name/value dictionary. Domain and path collisions must remain separate.[11]

Use `AmazonOrdersConfig(config_path=<isolated path>, data={domain: amazon.it, cookie_jar_path: <explicit file>, warn_on_missing_required_field: true})`, then `AmazonSession(config=config)`. The public `import_cookies(records, verify=False)` accepts Playwright-shaped records, filters site domains, and writes the library's jar without network access. `verify=True` additionally requests order history. Cookie presence alone is not proof that Amazon accepts a session.[11][12]

The adapter ignores `AMAZON_*` environment configuration and never uses the home default path, shared-cookie migration, username/password settings or `login()`. It refuses the user's `~/.config/amazonorders` directory. The standalone demo requires a new/empty temporary directory. Cookies use the upstream private-file writer (mode 0600), and the demo directory is 0700. This work inspected only synthetic files created by tests.

## Options

| Option | Feasibility / reliability | Phone UX | Security / maintenance |
| --- | --- | --- | --- |
| Requests login | Already blocked on this account | Would require a custom form state machine | Reject; do not collect credentials in HA settings |
| Login relay | Small Python dependency; user browser executes JS, but changed origins and URL shims can fail | Native forms and keyboard; password managers/passkeys may not recognize the relay origin | Password transits the add-on; third-party JS must be isolated from HA; Amazon-specific patches need maintenance |
| Device token after human login | Both inspected implementations have the protocol; not locally verified | Reauthentication less frequent if renewal works | Opt-in account change; refresh-token theft/revocation risk; private endpoints may change |
| Chromium + noVNC | Best match for the browser login already observed working | Remote desktop needs zoom/touch/keyboard controls | Heavier; trusted noVNC UI can stay on HA origin while Amazon JS stays inside Chromium |
| Manual cookie export | Technically easy via import_cookies | Poor on phones | Not the recommended UX; do not ask the user to paste cookies in chat |

These comparisons are design judgments based on the inspected implementations and the supplied local observation, not measurements of production reliability.

## Flow and backend contract

All interface methods are **synchronous**:

```python
status() -> {"state": "ok" | "auth_required" | "in_progress",
             "method": str, "expires_hint": str | None}
start() -> str  # short-lived browser URL, no Amazon request
logout() -> None  # local deletion only, never AmazonSession.logout()
get_session() -> amazonorders.session.AmazonSession  # or AuthRequired
```

`CookieAuthProvider` owns storage and verification. `ProxyAuthProvider` adds the login transport. `get_session()` may make one read-only order-history verification; call it inside the backend's single request gate/thread, never on the async HTTP event loop. After restart, `status()` remains `auth_required` until that verification succeeds. On a later authentication failure the worker calls `invalidate()`, stops jobs and emits the existing auth-required event. Cookie expiry is not a reliable session-validity deadline, so `expires_hint` is `None`.

Backend integration points:

1. Construct one provider for `/data/amazonorders`; no global singleton/shared account jar.
2. Route authenticated `POST api/auth/start` to `start()` and return its URL; serialize starts and enforce same-origin/CSRF checks.
3. The prototype offers aiohttp `create_app()` / `handle(request)` plus `aclose()`. It is **not a FastAPI router**. A backend bridge must proxy HTTP to a private loopback aiohttp listener, preserve the configured external path prefix/Host, and never expose that listener as a host port. The bridge is not implemented in this slice.
4. Derive the external Ingress prefix only from Supervisor-trusted metadata. Supervisor documents `X-Ingress-Path`, WebSocket support and allowing ingress connections only from its gateway address.[13]
5. For the relay, do not activate the bridge on HA's normal origin until origin isolation passes. A sandbox without `allow-same-origin` may break Origin validation/CAPTCHA; the current demo intentionally rejects `Origin: null`. A separate isolated HTTPS origin avoids HA DOM access but needs explicit authentication and deployment plumbing.
6. `logout()` clears local cookies/token and invalidates active login. The backend must also close/cancel the interactive transport with `await aclose()` before accepting another start. It does not revoke Amazon sessions/devices; tell the user how to revoke them.

```mermaid
sequenceDiagram
    actor Human
    participant UI as HA Ingress UI
    participant Auth as AuthProvider
    participant Browser as Isolated relay / remote Chromium
    participant Amazon
    participant Gate as Read-only request gate
    Human->>UI: Start sign-in
    UI->>Auth: start()
    Auth-->>UI: Short-lived URL (no upstream request)
    Human->>Browser: Open URL; type password and OTP
    Browser->>Amazon: Human-driven sign-in and challenges
    Amazon-->>Browser: Authenticated cookies / optional PKCE code
    opt Explicit device-registration flag
        Auth->>Amazon: Register virtual device; exchange refresh token
        Amazon-->>Auth: Italian website cookies
    end
    Browser-->>Auth: Capture cookies
    Auth->>Auth: Persist isolated private jar
    Gate->>Amazon: Read last30 order list; no details
    Amazon-->>Gate: Order-list pages or challenge
    Gate-->>UI: Verified count / auth_required
    Note over Browser,Amazon: If relay JS fails, stop retries and switch to real Chromium
```

## Remote-browser fallback under Ingress

Use a Debian/glibc image, not the current common Alpine add-on base. Playwright documents Debian/Ubuntu arm64 support; Debian packages Chromium for arm64. Playwright's browser distributions do not support musl-based Alpine. This is a project deployment choice, not a claim that every form of Chromium is impossible on Alpine.[15][16][17]

Proposed on-demand process tree (not yet built or exercised on HA/Pi):

- Xvfb, display `:99`, initially 1280×900×24, `-nolisten tcp`.
- Headed Chromium controlled by Playwright, using a disposable profile and the distribution's Chromium executable (discover its path inside the image; the host's `/usr/sbin/chromium` is not a container guarantee).
- x11vnc bound to loopback only; websockify bound to loopback only. Authorize the browser session at the backend and do not publish ports 5900/6080. Prefer an ephemeral VNC credential passed through private runtime files, not a URL or logs.
- Serve packaged, trusted noVNC assets at `auth/browser/<nonce>/...`; forward `auth/browser/<nonce>/websockify` as a WebSocket. Construct its `ws:`/`wss:` URL from the actual Ingress URL and full prefix. noVNC supports a relative or absolute WebSocket `path`.[14]
- Start navigation only when the human opens the session. Do not run Playwright form fill, credential reads, screenshots, HAR, traces, downloads or page-content logging.
- The human clicks Finish. Export `context.cookies()`, import through the same provider, perform the gated list check, then kill Chromium/Xvfb/VNC and remove the profile. Timeout, logout and add-on shutdown must do the same.

Playwright's `connect`/CDP endpoint is an automation API, not a phone-ready remote desktop. Do not expose it to the browser/client or use Inspector/codegen as a substitute for noVNC.

Pi 5 capacity is **unmeasured**. Use 512 MiB–1 GiB of incremental RAM as an initial planning allowance, not a benchmark or limit guaranteed to work; Chromium may exceed it. Xvfb's raw framebuffer is only one component. Measure full process-tree RSS, CPU peaks, startup time, image size and HA responsiveness on the target aarch64 host. Run one session at a time, stop it when idle, and do not enable GPU/privileged container access merely to improve login speed. Maintain the Chromium sandbox under a non-root user where HA's confinement permits; running the browser as root disables its sandbox per Playwright's Docker guidance.[16]

## Local prototype

Files live under `amazon_orders/backend/src/amazon_orders_ha/auth/` and `backend/scripts/`. The demo is loopback-only on **http://localhost:8098**. It prints instructions to stderr and only the successful last-30-days count to stdout; it never prints order titles, IDs, names, addresses or raw exceptions. The list operation may use multiple pages, with a 20–40 second delay between requests. No detail pages are fetched. A missing order-history count marker fails closed rather than reporting a JavaScript challenge as zero orders.

From the repository root:

```bash
uv venv .venv-auth-demo
uv pip install --python .venv-auth-demo/bin/python \
  -r amazon_orders/backend/scripts/requirements-auth-demo.txt
AUTH_DATA_DIR="$(mktemp -d)"
.venv-auth-demo/bin/python \
  amazon_orders/backend/scripts/auth_proxy_demo.py --data-dir "$AUTH_DATA_DIR"
```

Open localhost:8098 yourself. For the device experiment, use a **different empty temporary directory** and append `--register-device`. If the browser is on another machine, use an SSH local-port forward rather than binding this HTTP relay to the LAN. Do not use the localhost experiment from an HA iframe.

Dependencies are pinned in `scripts/requirements-auth-demo.txt`: amazon-orders 6.0.0, amazon-auth 1.1.0, authcaptureproxy 1.3.9, httpx 0.28.1, aiohttp 3.13.3. The backend pyproject was not changed. Browser fallback would additionally require Playwright and Debian Chromium/Xvfb/x11vnc/noVNC/websockify; their image pins belong to the later container implementation.

## Security gates and known gaps

- The add-on sees credentials transiently when relaying forms. “User types them” does not mean the backend cannot see them. TLS to Amazon is verified; production client-to-relay transport must also be HTTPS.
- The random URL is a short-lived bearer capability. Avoid browser history/referrer leakage, analytics, access logs and proxy exception dumps. Do not share the URL or browser developer-console output; upstream CAPTCHA scripts can include challenge data in their console messages.
- Auth requests use destination allowlists, TLS, Host/Origin checks, private upstream cookies and no inherited proxy environment. HA cookies, Authorization/Supervisor headers and ingress metadata are not forwarded. Cross-host credential-body redirects are blocked. These controls have synthetic coverage, not a security audit.
- The adapter is deliberately stricter than AMP. Unlisted authentication/asset hosts or paths may break real login. Add only observed, reviewed destinations; never turn this into an arbitrary URL proxy.
- There is no secure memory zeroization guarantee in Python, and a malicious upstream script could still navigate outside the relay. Do not store a HAR or browser profile for diagnosis.
- Production cancellation/races, cookie-write atomicity under concurrent backend jobs, renewed-token revocation, backup policy and sandbox behavior still need implementation/validation. Do not run sync while changing session files. In particular, cancel/await an in-flight device-registration task before logout returns; a remote registration may already have created a device.
- Test only one interactive attempt at a time. Stop after a repeated challenge; no unattended password/OTP retry loops.
- Rollback is local: stop the demo, delete only its temporary data directory, and remove the optional experimental device in Amazon's account settings. Do not touch the user's existing amazon-orders jar.

## Verification and human test plan

Completed without Amazon access: synthetic cookie conversion/domain filtering; prefix/query-action rewriting; destination/Origin rejection; environment/path isolation; private-file persistence/local logout; local relay with HTTPX mock transport; cookie capture and relay shutdown; real amazon-orders parsing of synthetic empty-history/challenge pages. A real loopback server smoke test returned 200 for landing/health, created no session files before human navigation, and printed no count. Dependency code emits aiohttp `has_body` deprecation warnings during tests; these are not an Amazon failure.

The human executes the remaining checks:

- [ ] Start the ordinary demo in a new empty directory. Verify no Amazon navigation until clicking Start.
- [ ] Enter email, password and OTP yourself. Test one wrong OTP, then a correct current OTP; no saved credential/TOTP secret should be required. Do not send credentials to an agent.
- [ ] If shown, complete CAPTCHA/JS in the browser. Record only the challenge category and sanitized success/failure; do not export a HAR, raw HTML or logs.
- [ ] On success, compare stdout's last30 count with Amazon manually. Confirm no order details or personal data appear in output. Verify jar file permissions without displaying its contents.
- [ ] Test cookie reuse/restart through the backend gate, expiration, logout, failed network, cancellation and two competing starts. Failed/challenged verification must stop sync and must not become an empty successful history.
- [ ] In a separate opt-in run, confirm the new virtual device appears; verify Italian cookie exchange and a fresh last30 list. Later, test renewal after restarting without a password/OTP, and revoke the device to verify auth-required behavior. Renewal execution needs the later backend implementation.
- [ ] Separately verify Italian `/your-orders` and `/gp/css/order-history` access; do not infer legacy access from Alexa API success.
- [ ] Implement/test noVNC on actual HA Ingress: dynamic prefix changes, wss forwarding, Supervisor-only access, auth expiry, logout/timeout cleanup, iOS/Android keyboard, rotation, paste/zoom and touch CAPTCHA.
- [ ] Prove no Amazon JavaScript can access HA parent DOM/storage or invoke HA-origin APIs. If sandboxed relay CAPTCHA needs `allow-same-origin`, reject that deployment and use noVNC or a separate origin.
- [ ] Measure Pi 5 memory/CPU during challenge, verify architecture/image builds and Chromium sandbox, and confirm HA automations remain responsive.

## Sources

[1] https://github.com/alandtse/alexa_media_player/blob/b7b6c72ecb88bb8f144c7689ac9770a74d7f9c1f/custom_components/alexa_media/config_flow.py
[2] https://github.com/alandtse/auth_capture_proxy/blob/710e058e8f5b14bf5d23102ed509380896f23b56/authcaptureproxy/auth_capture_proxy.py
[3] https://github.com/alandtse/auth_capture_proxy/blob/710e058e8f5b14bf5d23102ed509380896f23b56/authcaptureproxy/examples/amazon_waf.py
[4] https://github.com/alandtse/auth_capture_proxy/blob/710e058e8f5b14bf5d23102ed509380896f23b56/pyproject.toml
[5] https://github.com/alandtse/alexa_media_player/pull/3690
[6] https://github.com/alandtse/auth_capture_proxy/pull/51
[7] https://github.com/alandtse/alexa_media_player/issues/3660
[8] https://files.pythonhosted.org/packages/14/c9/71defac0b33f46192efcb2ff4c751aee7001eb826b6e15fb61d3675f26c4/alexapy-1.36.0-py3-none-any.whl
[9] https://github.com/LordHenry76/ha-amazon-orders/blob/77403bafd9184598e5ffaf032d30e4bcf5444bfc/custom_components/amazon_orders/api/auth.py
[10] https://github.com/LordHenry76/ha-amazon-orders/blob/77403bafd9184598e5ffaf032d30e4bcf5444bfc/custom_components/amazon_orders/api/client.py
[11] https://raw.githubusercontent.com/alexdlaird/amazon-auth/main/amazonauth/session.py
[12] https://raw.githubusercontent.com/alexdlaird/amazon-auth/main/amazonauth/conf.py
[13] https://raw.githubusercontent.com/home-assistant/developers.home-assistant/master/docs/apps/presentation.md
[14] https://raw.githubusercontent.com/novnc/noVNC/master/docs/EMBEDDING.md
[15] https://playwright.dev/python/docs/intro
[16] https://playwright.dev/python/docs/docker
[17] https://packages.debian.org/trixie/chromium
[18] https://github.com/alandtse/alexa_media_player/issues/3538
