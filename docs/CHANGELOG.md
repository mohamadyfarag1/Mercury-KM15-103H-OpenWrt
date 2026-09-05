# Changelog: Controller ↔ Client Repair & Redesign Session

This documents one continuous work session (versions `1.2.43` → `1.2.49`)
that started from "the Controller and Client don't talk to each other, and
almost nothing works," went through a full backend repair, then a full
frontend/UI redesign, then two rounds of real-device deployment debugging.
Read [AI_AGENT_RULES.md](AI_AGENT_RULES.md) for the guardrails these
incidents produced.


## Security, Flash-Wear & System Audit Rollout (Phases 1 → 5)

Controller `1.3.12` → `1.3.17`, Client `1.2.74` → `1.2.79`. Comprehensive 5-phase audit and hardening pass based on senior code review findings:

1. **Flash-Wear Elimination (`db.py`)**:
   - `snapshot_if_due()` was hashing the full state including timestamps (`router_time`, `last_seen`) and live client RSSI, forcing a flash write every 90 seconds (350,000 writes/year).
   - Added `_extract_persist_state()` to strip volatile churn and calculate deterministic `hashlib.md5` digests, reducing SPI/NAND flash writes by >99.9% (persisting only on genuine configuration changes like adoption, ban, or Wi-Fi profile edits).

2. **Shell Injection Hardening (`horus_groups`, `sys_wifi.py`)**:
   - Converted all `subprocess.run(f"uci set ...='{val}'", shell=True)` calls in `horus_groups` and `sys_wifi.py` (`apply_wifi_config`, `enable_80211kv_locally`) to use argument lists (`["uci", "set", ...]`) without shell interpolation.
   - Prevents command execution or syntax corruption when SSIDs, group names, or passwords contain single quotes (`'`), semicolons, or dollar signs.

3. **Logic & Protocol Fixes (`root.py`, `horus_test`, `ban.js`)**:
   - Removed accidental `ban_mac_locally(cmac)` inside the `unban` handler in `root.py` (which dropped clients momentarily before removing the ban).
   - Routed RRM automatic channel adjustments through `self.db.enqueue_cmd()` instead of direct `send_cmd()` to guarantee reliable delivery, retries, and acknowledgments.
   - Added full connection testing for `icm`, `um7`, and `mikrotik` engines in `horus_test` CGI, fixing false "unknown server type" errors from the settings UI.
   - Removed non-functional "Allow Home AP Only" placeholder from `ban.js`.

4. **Performance & Embedded Python Optimization (`horus-radius.py`, `satellite.py`)**:
   - Added `get_all_uci_config()` to `horus-radius.py` to parse `/etc/config/horus_controller` directly in Python, eliminating 7 repetitive `subprocess.check_output` shell forks per sync loop.
   - Replaced `urllib.request` in `satellite.py` (`install_package`) with robust `uclient-fetch`/`wget`/`curl` fallback to guarantee compatibility with stripped `python3-light` builds.

5. **Code Drift Synchronization & Theme Cleanup (`sys_wifi.py`, `horus_version`, `build_ipk.py`)**:
   - Synchronized dynamic wireless interface detection from `/sys/class/net` into Controller's `sys_wifi.py`.
   - Added fast-path `/tmp/horus_pkg_version` check to Controller's `horus_version` CGI.
   - Removed legacy 32-character secret overwrite from Controller's `build_ipk.py` postinst to protect custom high-entropy secrets on upgrade.
   - Added automatic theme header cleanup in Client's `prerm` script.


## Fix (regression) — every AP reported its RADIUS server "offline": `import ssl` is unavailable on python3-light

Client/Controller `1.2.73`/`1.3.11` -> `1.2.74`/`1.3.12`. **A regression I
introduced with the earlier HTTPS/Cloudflare support.** User reported that the
wireless pages showed "الرديس غير متصل" on every associated station and the AP
detail page listed every subscriber as "غير مسجل", while the settings page's
own connection test still said "متصل بالسيرفر بنجاح".

- **Root cause**: the HTTPS change added `import socket, ssl, json` at the top
  of `http_req()`. OpenWrt's `python3-light` has no `ssl` module (verified
  on-device: `python3 -c 'import ssl'` -> ImportError), so **every** call
  raised ImportError -- plain `http://` included -- and the sync loop wrote
  `status: "offline"` with zero records on every AP.
- **Why the settings page disagreed**: `horus_test` is a shell script using
  `curl`, a completely separate code path from the Python daemon that fetches
  the actual data. It kept reporting success while the daemon was dead.
- **Fix**: `ssl` is imported lazily inside the TLS branch only, and when it is
  genuinely missing an `https://` URL falls back to `curl`/`uclient-fetch`
  (both link libustream and do real TLS). `MikrotikApiClient.connect()` got the
  same treatment so the plain API port 8728 works on devices with no TLS at
  all. See [AI_AGENT_RULES.md](AI_AGENT_RULES.md) rule 25/28.
- **Verified live on both devices**: after deploying, `/tmp/horus_radius.json`
  went from `{"status":"offline","count":0}` to `{"status":"online","count":3}`
  with real subscriber records, and the wireless page now renders each station
  with its subscriber name, package, remaining quota and days, and the SAS
  badge.
- Covered by `test_no_ssl_module.py` (7 cases) which blocks `import ssl`
  process-wide and drives the real shipped file, so this exact regression
  cannot ship again.

## Fix — the CGI auth guard rejected EVERY browser request; individual "Activate AP" button was permanently dead

Client/Controller `1.2.72`/`1.3.10` -> `1.2.73`/`1.3.11`. Reported live with screenshots: after a package update the Client page
still showed "🔴 غير متصل بالكنترولر / LuCI login required" even after logging
out and back in, and on the Controller the per-AP adopt button could not be
clicked at all -- it only ever read "جاري التفعيل", forcing the use of "ضم
الكل". Diagnosed by driving a real browser against the live devices
(`192.168.109.145` and `192.168.169.225`) rather than replaying requests over
SSH -- which is why it had been missed twice before. **Three separate bugs,
all confirmed and fixed live.**

- **1. LuCI's session cookie never reaches our endpoints.** LuCI sets
  `sysauth_http=...; path=/cgi-bin/luci/`. Our scripts live at
  `/cgi-bin/horus_*` -- outside that path -- so the browser correctly never
  sends the cookie, `cgi_auth.sh` found none, and returned 403 to **every
  request from every logged-in admin, always**. The guard had been
  unconditionally closed to browsers since the day it was added; it only
  looked functional because the escape hatch (`cgi_auth='0'`) was set on the
  test devices. Every SSH reproduction passed because a hand-written
  `-H 'Cookie: ...'` bypasses path scoping entirely.
  **Fix**: the frontend mirrors `L.env.sessionid` into a `horus_sid` cookie
  scoped to `/cgi-bin/` with `SameSite=Strict`; both guards accept it and
  still validate it through rpcd, so a forged or expired id is refused
  exactly as before (verified live). See rule 25.
- **2. `E('button', {disabled: false})` renders a disabled button.**
  `disabled` is an HTML boolean attribute -- present at all means disabled,
  so `disabled="false"` is still disabled. The per-AP "تفعيل الإكسس" button
  was therefore **unclickable in every state, for every AP, always**. Fix:
  only set the attribute when it should actually be disabled. See rule
  26.
- **3. Completed adoption commands never aged out.** `getAdoptStatus()`
  returned the newest `set_api_key` queue entry regardless of age, and an
  `acked` entry renders as a disabled "⏳ جاري التفعيل...". Any AP that had
  ever been adopted and later released kept an old `acked` entry, pinning its
  button to a permanent "activating" state. Fix: ignore entries older than 30s,
  aged against the controller's own `router_time` -- never the browser clock,
  since AP/controller clocks in this fleet were measured ~22 hours apart.
  See rule 27.
- **Verified end-to-end in a real browser**: all previously-403 endpoints now
  return 200 with the guard fully enabled, unauthenticated and forged-cookie
  requests still get 403, the individual Activate button renders enabled, and
  clicking it adopted the target AP (confirmed by reading `hmp_secret` on the
  client over SSH) with the pending banner clearing on the next poll.
- The `cgi_auth='0'` escape hatch left on the controller during earlier
  debugging has been removed, so that device is protected again.
- Covered by `test_adopt_button_state.js` (12 cases against the real
  button-state logic).


## Fix — the "only reload rpcd if the ACL changed" fix (rule 15/17) was defeated by any reboot, plus a misleading RADIUS status label

Client/Controller `1.2.71`/`1.3.9` -> `1.2.72`/`1.3.10`. Reported live: a
Client settings page showed "🔴 غير متصل بالكنترولر / LuCI login required"
right after an opkg update, and the same page's RADIUS tab showed "🟡
متصل ولكن بيانات الدخول غير صحيحة" (credentials invalid) — looking like
two separate problems, one of them implicating the SAS server credentials.

- **Root cause of both, at once**: the ACL-change-detection hash from the
  earlier `postinst` fix (rule 15/17) was stored at `/tmp/.horus_acl_hash`
  — tmpfs, wiped on every reboot. Any device rebooted for any reason
  between installs loses that file, so the next update always "detects" a
  change and reloads rpcd anyway, killing the current session — exactly
  the bug that fix was meant to eliminate, just reboot-gated instead of
  actually-changed-gated.
- **The "wrong credentials" message was never about credentials.**
  Investigated over SSH on the reporting device (`192.168.109.145`):
  decrypted the stored SAS password from UCI and replayed the exact
  login request `horus_test` sends directly against the real SAS server
  — it authenticated immediately, valid token returned. The RADIUS status
  widget was showing the generic "credentials invalid" label for ANY
  failure it didn't recognize as a timeout, including our own
  `cgi_auth.sh` returning 403 for the exact same reason the controller
  connection was down — an invalidated session, from the same reboot/hash
  bug above.
- **Fix**: `ACL_HASH_FILE` moved to `/etc/.horus_acl_hash` (survives a
  reboot; see [AI_AGENT_RULES.md](AI_AGENT_RULES.md) rule 23). The RADIUS
  status widget now recognizes `d.error === 'forbidden'` (our own auth
  guard) separately from a real RADIUS rejection and shows "🔄 انتهت
  جلستك -- حدّث الصفحة" instead (rule 24).
- This is very likely the same root cause behind the original incident
  this whole session started from, where the RADIUS panel was reported as
  rejecting valid credentials after an update.

## Feature — added MikroTik direct connect (RouterOS API, v6+v7, hotspot + PPPoE) as a sixth RADIUS type

Client/Controller `1.2.69`/`1.3.8` -> `1.2.70`/`1.3.9`. Follow-up to the ICM
and User Manager 7 addition: the user wants a MikroTik router itself
connectable too — separate from User Manager 7 — with two hard
requirements: (1) support both RouterOS v6 and v7, (2) when the extension
asks about a set of connected MACs, the **router** filters and only sends
back matching rows — the AP must not pull the whole active-user list and
filter it locally on its own limited CPU. Both hotspot and PPPoE need to be
covered since the user runs both simultaneously. See
[AI_AGENT_RULES.md](AI_AGENT_RULES.md) rule 22 for the full design.

- Added `MikrotikApiClient` (a from-scratch RouterOS binary API client —
  length-prefixed word/sentence framing, works unchanged across v6/v7) and
  `MikrotikEngine` to `horus-radius.py`, wired in as `radius_type=mikrotik`.
- Login tries a direct `/login =name=/=password=` first; if the router
  embeds an MD5 challenge in that reply (older RouterOS, pre-6.43), a
  second round with the computed response completes the handshake — one
  code path covers both eras.
- Queries use RouterOS's own `?key=value` / `?#|` server-side filter
  syntax so the router — not the AP — does the MAC matching. This is
  actually stricter than the reference Flutter app, which fetches every
  active session and filters client-side.
- `parse_routeros_uptime()` added to correctly turn RouterOS's duration
  strings (`"1h2m3s"`, `"2w3d10:20:30"`) into seconds; also backfilled into
  `Um7Engine`, which previously left session time at a hardcoded `0`.
- Verified with `test_mikrotik_engine.py` against **three fake RouterOS
  servers speaking the real wire protocol** over actual TCP sockets (not
  mocked): plain login, legacy MD5 challenge login, and a rejected-login
  case — including inspecting the literal bytes sent to confirm the
  server-side filter words are actually being constructed correctly.

## Feature — added ICM Radius and MikroTik User Manager 7 as RADIUS types

Client/Controller `1.2.68`/`1.3.7` -> `1.2.69`/`1.3.8`. User has a Flutter
app (`D:\sas4\ops-go\opsgo`) that already integrates with several RADIUS-like
systems and asked for the extension to support the same ones, specifically
using the extension's existing fast single-request-per-cycle pattern (not
the Flutter app's slower bulk-paginated sync) — see
[AI_AGENT_RULES.md](AI_AGENT_RULES.md) rule 21 for the full reasoning,
including what was deliberately left out (the Flutter app's "Smart" type,
and MikroTik-the-router itself, which needs a binary protocol client rather
than HTTP/JSON and hasn't been scoped).

- Added `IcmEngine` and `Um7Engine` to `horus-radius.py`, wired into the
  `radius_type` dropdown as `icm` (ICM Radius) and `um7` (MikroTik User
  Manager 7) in both packages' settings pages.
- `http_req()` gained a `verify` parameter (default `True`, unchanged for
  every existing engine) so `Um7Engine` can turn off certificate validation
  specifically for RouterOS's own REST API, which is TLS-only with a
  self-signed cert out of the box — this does not weaken validation for any
  cloud-hosted RADIUS panel.
- Verified with `test_icm_um7_engines.py` (23 cases against the real
  `horus-radius.py`): correct online/active filtering, correct field
  extraction, exactly one HTTP call per sync cycle, and graceful
  `[], "offline"` degradation on auth failure or an unreachable panel.

## Fix — `horus-radius.py` couldn't actually reach an `https://` RADIUS panel

Controller/Client `1.3.6`/`1.2.67` -> `1.3.7`/`1.2.68`. User question: would
a SAS/DMA panel hosted on a cloud VM behind a Cloudflare domain (HTTPS) work
with the extension? Answer at the time was no — traced during the DMA API
review (comparing `horus-radius.py`'s `DmaEngine` against the real
`D:\sas4\ops-go\dma-sql` server source) to `http_req()`, the one hand-rolled
HTTP client shared by all three RADIUS engines (SAS/DMA/ADV): it stripped an
`https://` prefix and then opened a plain unencrypted socket anyway — no TLS
was ever performed. Against a cloud/Cloudflare-fronted panel this silently
produces empty responses, `http_req()` returns `None`, and the daemon just
reports `"offline"` with nothing to explain why.

Fixed by wrapping the socket with `ssl.create_default_context().wrap_socket(
s, server_hostname=host)` when the URL is `https://` — `server_hostname`
matters here specifically because it drives SNI, which is what lets a
Cloudflare-fronted domain route the TLS connection to the right backend at
all. See [AI_AGENT_RULES.md](AI_AGENT_RULES.md) rule 20. Verified live
against a real public HTTPS endpoint (`https://httpbin.org/get`), not just a
unit test — full TLS handshake, SNI, and JSON parse succeeded.

Also reviewed as part of the same pass and found correct, no fix needed: the
DMA endpoint/action names, auth flow (`key`+`admin_user`+`admin_pass`), and
every field name `DmaEngine` reads all match the live
`user_api.php`/`actions_online.php`/`batch_overview.php` server code exactly.

## Reliability fix — "Adopt All" silently dropped one AP, plus live command-system verification

Controller `1.3.5` -> `1.3.6`. Follow-up to a user report: after "Adopt
All" for 2 pending APs, one adopted successfully and the other stayed
stuck on "awaiting activation" with no visible error, and its individual
"Activate" button looked unresponsive.

- **Root cause**: `sendAdopt()` looked up the controller's `hmp_secret` via
  `L.uci.load('horus_controller')` before every single adopt click — an
  async round-trip through LuCI's client-side UCI/form cache. For one of
  the two targets in the bulk sequence, this silently failed to produce a
  working request (the exact JS-side mechanism was not pinned down).
  Manually replaying the identical CGI call over SSH (same payload, no
  browser) worked on the first try, isolating the fault to the browser-side
  secret lookup, not the backend.
- **Fix**: the controller now fills in `key` from its own already-loaded
  `self.secret` server-side (`root.py`) whenever a `set_api_key` request
  doesn't supply one, and refuses to enqueue the command at all if it has
  no secret configured (rather than shipping a half-adopted AP with an
  empty shared secret). `map.js` no longer sources or sends the secret at
  all — see `AI_AGENT_RULES.md` rule 18.
- **The rest of the command/queue/ack system was verified solid live**,
  against real hardware, while investigating this: a WiFi 2.4GHz-only SSID
  rename, a hostname change, and a LAN port down/up toggle were all issued
  from the controller and independently confirmed on the client device
  (`uci show`, `ip link show`) — typical ack turnaround was 250-400ms. One
  port-toggle ack was dropped on the wire during testing; the queue's
  automatic retry (rule 10) resent it and got a confirmed ack ~5s later
  with zero manual intervention, exactly as designed.
- Verified with `test_setapikey_server_secret.py` (6 cases against the
  real `root.py`): no-key-supplied fills in the server's own secret,
  an explicitly-supplied key is still respected, a controller with no
  secret configured refuses rather than sending an empty one, and this
  holds for both single- and list-target adoption requests.

## Reliability fix — every package update was logging admins out of every device

Controller `1.3.4` -> `1.3.5`, Client `1.2.65` -> `1.2.66`. Diagnosed live
via SSH against real hardware after a user report: after installing the
latest packages across several APs, the controller dashboard showed "no
APs found" and a client's own settings page showed "LuCI login required" as
its connection status.

- **Root cause: `postinst` unconditionally reloaded rpcd (with a `restart`
  fallback) and, 3 seconds later, restarted uhttpd, on EVERY single
  install/upgrade.** `rpcd reload`/`restart` resets rpcd's in-memory session
  table — the only thing backing a LuCI login on OpenWrt 23.05+ (there are
  no `/tmp/luci-session-*` files to preserve on this LuCI generation; that
  was confirmed live — `ls /tmp/luci-session*` found nothing on either
  device). Every admin's active session on that device was invalidated the
  moment the package finished installing, and `cgi_auth.sh` (rule 9/10)
  correctly starts rejecting every dashboard/status request until they log
  back in. Across a deployment with many APs, that turned a routine update
  into what looked like total connectivity loss.
- **The backend itself was never broken.** Live verification during the
  incident: a manually-created rpcd session authenticated successfully and
  fetched real data from both the controller and a client's
  `horus_ping_controller`. The controller's own `/tmp/horus_network_state.json`
  had 5 APs, all with `last_seen` timestamps within a second of the
  server's own clock — the daemon, the HMP protocol, and every change made
  in Phases 0-2 were functioning correctly the entire time.
- **Fix**: `postinst` (both projects) now hashes the installed ACL file and
  only calls `rpcd reload`/`restart` when that hash differs from the
  previous install's — i.e. only when an update actually changes what the
  ACL grants, not on every code-only or UI-only update (nearly all of
  them). The unconditional `uhttpd restart` was removed outright: CGI
  scripts execute fresh per-request with nothing to invalidate, and static
  assets are already cache-busted via renamed filenames (rule 4) — the
  restart added a second disruption for no benefit. See
  `AI_AGENT_RULES.md` rule 15 (client) / 17 (controller).
- Verified with `test_postinst_session_fix.py` (6 cases against the real
  generated `build_ipk.py` output) plus a live functional test of the exact
  hash-comparison logic run directly on a real device's BusyBox shell
  (first install reloads once, a second run with an unchanged ACL correctly
  skips the reload).
- **This update itself will still cause one final session reset** on any
  device that hasn't run this fix before (no prior hash to compare against)
  — expected and harmless, just log back into LuCI once after this specific
  upgrade. Every update after this one, on any device, preserves existing
  sessions unless that update genuinely changes the ACL.

## Phase 2 (Product Roadmap) — Live network topology

Controller `1.3.2` -> `1.3.4`, Client `1.2.64` -> `1.2.65`. The last of the
three structural gaps named in the product-direction artifact: a real,
dual-confirmed AP-to-AP link map, without the mesh feature UniFi doesn't
have.

- **No new protocol message was added for this.** The natural source
  (P2P `peer_announce`) is fully gated off while controller-managed by
  design (see the earlier P2P-fix round) and that must stay true. Instead,
  `db.py`'s new `compute_topology()` derives every link from data already
  in `hello`/`telemetry`: wired links from each AP's bridge forwarding
  table (`ports[*].clients`, already collected via `brctl showmacs`), and
  wireless backhaul from a NEW `radio_macs` field (each AP's own radio
  hardware MACs, from `get_wifi_radios_and_macs()` — already used by the
  now-dormant-while-managed P2P code) cross-referenced against every other
  AP's associated-clients list.
- **"Confirmed" means two independently-reported facts agree** — AP-B's own
  client list shows AP-A's radio associated, AND AP-A's own wifi state
  independently reports a `sta`-mode radio. A link seen from only one side
  is still shown (dashed in the UI) but marked unconfirmed. Wired links use
  the same two-sided rule (both APs' own bridge tables agree). Only
  authorized (adopted) APs are ever topology nodes — a foreign or
  not-yet-adopted device is excluded, consistent with rule 13's `aps`/
  `foreign_aps` separation.
- Computed every ~5s in `maintenance_loop` (not on every 1s tick — this is
  O(APs²) over each AP's client/port lists, cheap for a realistic AP count
  but no reason to run it every second) and stored in `self.state["topology"]`
  / `self.state["topology_root"]`, flowing through the existing
  `horus_map_data` plumbing with no new CGI endpoint needed.
- **New UI tab** ("الطوبولوجيا"): an SVG tree, controller at the root, each
  AP placed by hop count via a BFS layout (`topology.js`). Wired edges are
  green, wireless are blue-ish, confirmed links are solid, inferred links
  are dashed, and wireless line thickness scales with signal strength. An
  AP not reachable from the root at all (e.g. an isolated wireless island)
  is shown separately below a dashed divider instead of silently vanishing
  from layout math it can't participate in.
- **A real bug was caught by the new test suite before shipping**: the BFS
  layout traversed into ANY AP referenced by an edge, including one that
  had just been ejected/deauthorized since the topology was last computed
  (`compute_topology()` runs on its own ~5s cadence, independent of the
  poll that fetches it) — such a stale edge would consume a layout slot for
  a node with no real position data behind it. Fixed by only traversing
  into MACs still in the current authorized set.
- Added `topology` to `99_horus-controller-patch`'s `resource_modules`
  cache-busting list (see `AI_AGENT_RULES.md` rule 4) — easy to forget for
  a brand new shared module, and forgetting it reintroduces the exact
  stale-cache bug documented there.
- Verified with `test_phase2_topology.py` (17 cases against the real
  `db.py`: mutual vs one-sided wired/wireless confirmation, wired
  preferred over a coincidental wireless reading for the same pair, regular
  client MACs never becoming edges, unauthorized/foreign APs excluded,
  empty-network and no-edges cases), `test_phase2_radio_macs.py` (4 cases:
  `radio_macs` present in hello/telemetry once adopted, absent before
  adoption matching the existing data-minimization rule, and confirms
  `send_peer_announce()`'s `is_controller_managed()` gate is untouched), and
  a standalone algorithmic test for the BFS layout itself
  (`test_phase2_topology_layout.js` — 7 cases including the stale-edge bug
  above, a cycle that must terminate, and a missing root that must not
  crash). All earlier suites re-run clean. **Not verified**: the actual
  SVG/DOM rendering in `topology.js` and the new tab's wiring in `map.js`
  have no automated test and were not exercised in a live browser against a
  real router in this session.

## Security fix — WiFi passwords were broadcast in cleartext and exposed via the API

Controller `1.3.1` -> `1.3.2`, Client `1.2.63` -> `1.2.64`. Found while
investigating the data source for Phase 2 (live topology), fixed before that
phase started because of severity, not as part of it.

- **Every adopted AP was broadcasting its own current WiFi password in
  plaintext** inside every `hello`/`telemetry` frame (`wifi_info` from
  `get_wifi_info()` was sent as-is). Those frames are compressed but not
  encrypted, and go out as an L2 broadcast — readable by anyone on the
  segment with a packet sniffer, no authentication needed, on every hello
  cycle for every AP.
- The controller also **stored and re-served that password** through
  `horus_map_data` to any authenticated LuCI session with `read` access, not
  only whoever actually configured Wi-Fi — the dashboard's own JSON response
  carried every managed AP's current password.
- Fixed at the source: `satellite.py`'s `send_hello_once()`/
  `send_telemetry_once()` now call a new `_wifi_info_no_secrets()` wrapper
  that strips `password` before the payload is built, instead of using
  `get_wifi_info()`'s result directly. `get_wifi_info()` itself is
  unchanged — it's still correct for genuinely local uses.
- Defense in depth for already-adopted APs still running an older build:
  `db.py`'s `_redacted_state()` (the function added in Phase 0 to keep the
  command queue's in-transit passwords off the HTTP-facing copy) now also
  strips `password` from every `aps[mac]["wifi"]` entry.
- `detail_v2.js`'s per-AP Wi-Fi edit form no longer pre-fills the password
  field with the stored value — it starts blank (type `password`, not
  `text`) with a placeholder explaining that leaving it blank keeps the
  current password. This was already true functionally (`apply_wifi_config`
  only ever *sets* a password when one is explicitly given, never reads the
  old one back), so this only removes a needless on-screen exposure, it
  doesn't change what "save without touching this field" does.
- Verified with `test_security_wifi_password_leak.py` (11 cases): confirms
  no `password` key reaches the outgoing hello/telemetry payload while every
  other wifi field (SSID, channel, band) is preserved; confirms
  `get_wifi_info()` itself is untouched; confirms `_redacted_state()` strips
  a password that does make it into `aps[mac]["wifi"]` (the stale-AP case)
  while leaving already-clean data and APs with no wifi data at all
  untouched. All earlier suites re-run clean, no regressions.
- See `AI_AGENT_RULES.md` rule 13 (client) / 15 (controller) for the rule
  this incident produced.

## Phase 1 (Product Roadmap) — Adoption is now a visible process, not a guess

Controller `1.3.0` -> `1.3.1` (controller-only; nothing in the client
changed this round). Builds directly on Phase 0's command queue to fix the
single biggest "feels like a toy" gap named in the product-direction
artifact: the adopt button lied about success, and a foreign controller's
APs just vanished instead of explaining why.

- **Real adoption progress, not an optimistic guess.** The old "Activate"
  button flipped `ap.unauthorized = false` client-side the instant `fetch()`
  resolved — success was assumed, not confirmed. It now reads the actual
  `set_api_key` entry for that AP from `cmd_queue` (exposed by Phase 0) and
  shows "⏳ جاري التفعيل..." (disabled) while queued/sent, "⚠️ فشل - أعد
  المحاولة" if the AP never acknowledged after retries, and only shows the
  row as authorized once the controller's own DB says so on the next poll —
  which only happens once the AP's own telemetry validates with the secret.
- **"Adopt All" for the new-devices queue.** A dedicated panel appears above
  the table whenever any AP is unauthorized, with a one-click bulk adopt.
  Sends sequentially (300ms apart), reusing the existing safe pattern from
  `openBulkPkgModal` — the CGI hand-off (`AP_CMD_FILE`) is a single-slot
  file, so firing every POST back-to-back would silently overwrite all but
  the last one before `fast_cmd_loop`'s 0.2s tick could drain it.
- **Foreign APs are now visible instead of silently dropped.** `root.py`
  previously just `continue`d past any hello/telemetry whose `adopted_by`
  named a different controller — the device never appeared anywhere. It now
  gets a minimal record in a new, deliberately separate `foreign_aps` dict
  (`db.py`: `note_foreign_ap`/`cleanup_foreign_aps` — see
  `AI_AGENT_RULES.md` rule 13 for why it must never merge into `aps`), shown
  in its own greyed, action-free panel with the owning controller's MAC.
- **A real backfill bug was caught by the new test suite before shipping**:
  `HorusDB.load()`'s `.setdefault("cmd_queue", [])` /
  `.setdefault("foreign_aps", {})` calls were placed after an early `return`
  that fires whenever `/tmp/horus_db.json` already exists — which is exactly
  the common case for an in-place package upgrade (the daemon restarts
  without a reboot, so `/tmp` is never wiped). A controller upgrading from a
  pre-`1.3.0` build would have loaded old state missing both keys and
  crashed the first time anything touched them. Fixed by restructuring
  `load()` so the backfill always runs regardless of which branch populated
  `self.state`.
- Since the in-place row update (`updateDashboardTableInPlace`) can't patch
  a change in which action buttons a row shows, each `<tr>` now carries a
  `dataset.rowSig` fingerprint of `unauthorized + adoptStatus`; a mismatch
  on the next poll triggers a full replace of just that row instead of the
  whole table. See `AI_AGENT_RULES.md` rule 14.
- Verified with two new Python suites against the real shipped `db.py` and
  `root.py` (`test_phase1_foreign.py` — 17 cases including the backfill
  regression above; `test_phase1_foreign_root.py` — 9 cases confirming
  `listen_loop()` actually calls `note_foreign_ap()` and never ACKs or
  registers a foreign device) and a standalone algorithmic test for
  `getAdoptStatus()`'s "most recent entry wins" selection and the
  status→label mapping (`test_phase1_getadoptstatus.js`). All Phase 0 and
  earlier suites re-run clean. **Not verified**: the actual DOM/LuCI wiring
  in `map.js` (the new panels, row replacement, button state) has no
  automated test and was not exercised in a live browser against a real
  router in this session — review the diff and test on a real device before
  trusting it blindly.

## Phase 0 (Product Roadmap) — Durable state + acknowledged command queue

Controller `1.2.52` -> `1.3.0`, Client `1.2.62` -> `1.2.63`. First step of the
product-direction roadmap (see the "Horus WLC: Product Direction" artifact):
the backend foundation everything else (visible adoption progress, config
drift detection, network history) depends on.

- **Command queue with retry and acknowledgment**, replacing "write a
  command file, send once, delete the file" for every AP-targeted command
  (Wi-Fi config, reboot, ban-to-a-specific-AP, eject/unadopt, set_api_key,
  admin_password, and the rest of `ap_manage`). New `HorusDB` methods:
  `enqueue_cmd`, `cmd_due_for_send`, `mark_cmd_sent`, `mark_cmd_result`,
  `get_cmd_queue`. New `RootNode.dispatch_queue()` (controller) sends due
  entries and retries unacknowledged ones up to `CMD_MAX_ATTEMPTS` (4, spaced
  `CMD_RETRY_INTERVAL` = 2.5s apart) before marking them `failed`. New
  `cmd_ack` message type, sent from `satellite.py`'s `listen_loop()` (one
  insertion point, gated on the inbound frame carrying a `cmd_id`) and
  handled in the controller's `listen_loop()`. Commands with no single
  target (`'ALL'`, or `ban`'s network-wide broadcast case) intentionally
  keep the old best-effort broadcast — see `AI_AGENT_RULES.md` rule 10.
- **A real bug was caught by the new test suite before shipping**: the
  `unadopt` action clears the AP's own secret as part of handling the
  command; sending its ack *after* that (reading `self.secret` fresh) would
  produce an unsigned frame the controller can't verify, and the queue would
  report a `failed` eject that had actually succeeded. Fixed by capturing
  the secret before dispatching the command, not after.
- **State now survives a reboot.** `HorusDB.load()` falls back to
  `/etc/horus/state_snapshot.json` (OpenWrt's writable overlay, unlike
  `/tmp` which is tmpfs) when the primary `/tmp/horus_db.json` is missing —
  i.e., right after a fresh boot. Written by `snapshot_if_due()`, rate
  limited to once per 90s and skipped entirely when the content is
  unchanged, to avoid wearing the flash — see `AI_AGENT_RULES.md` rule 12.
- **Security fix in the same change**: the command queue can carry a
  plaintext Wi-Fi password in transit (needed to actually deliver it), and
  `self.state` — including the queue — is dumped verbatim to
  `/tmp/horus_network_state.json`, which any authenticated LuCI session can
  read via `horus_map_data`. Added `_redacted_state()` to strip `password`
  and `rescue_secret` from that specific HTTP-facing copy before it's
  written; the engine-internal copy and the flash snapshot keep full
  fidelity (neither is served over HTTP). See `AI_AGENT_RULES.md` rule 11.
- Verified with three new test suites run against the actual shipped code
  (not reasoning-only): `test_phase0.py` (24 cases — snapshot fallback,
  queue lifecycle, retry exhaustion, cap eviction, redaction),
  `test_phase0_root.py` (30 cases — every `process_fast_commands()` routing
  decision: which command kinds get queued vs. stay direct-broadcast, the
  ban/wifi_config field-name distinction between "client being banned" and
  "destination AP", the set_api_key dual normal+rescue-secret send), and
  `test_phase0_satellite_ack.py` (14 cases — ack sent/not-sent per message
  type and cmd_id presence, plus the unadopt-secret-timing regression
  above). All pre-existing suites (adoption lock, P2P gate, XSS escaping)
  re-run clean with no regressions.

## Phase 1 — Backend: why nothing connected

Starting state: Controller and Client shared a protocol (`protocol.py`) that
was correct and identical between both projects, but five independent bugs
each individually prevented the adoption/heartbeat flow from ever
completing.

1. **Controller shipped with `role='standalone'`.** `postinst` never set
   `role='root'`, so `core.py`'s `RootNode` (the only code path that builds
   the database and listens for `hello`) never ran. Fixed: `build_ipk.py`'s
   generated `postinst` now sets `role='root'` and generates a random
   per-device `hmp_secret` (`head -c 24 /dev/urandom | md5sum | cut -c1-32`)
   at install time, with an upgrade-safe migration for existing installs
   that still have the old defaults. Also found and fixed in the same pass:
   `postinst` called `enable` but never `restart`, so a fresh install never
   actually started the daemon until a reboot.
2. **`db.py` had no `get_ap()` method**, but `root.py`'s `set_api_key`
   handler called it — an `AttributeError` swallowed by a bare `except`,
   silently aborting the "Activate AP" action before it ever sent a packet.
   Added `get_ap()` and `set_ap_authorized()`.
3. **`RootNode.send_cmd()` never passed `secret=` to `send_hmp_frame()`.**
   Every command the controller sent was unsigned. Once a satellite had a
   secret configured (i.e., right after adoption), it correctly rejected
   all unsigned traffic — so adoption appeared to "complete" and then the
   AP would immediately look disconnected. Fixed by threading `secret`
   through `send_cmd()`.
4. **Client's `satellite.py` had a `NameError`**: `root_name` and
   `root_mac` were used but never assigned in the `root_heartbeat` handler
   (this is exactly the kind of drift rule 1 in AI_AGENT_RULES.md warns
   about — the controller's copy of this handler was correct). This meant
   `/tmp/horus_controller_info.json` was never written, so the client's own
   "am I connected" status was permanently wrong regardless of actual
   network state.
5. **`hmp_secret` defaulted to the string `'123'`**, hardcoded and shared
   across every install from this build script — a real security issue
   (item 20 below), separate from bug #1.

Also fixed in this phase: `real_addr` was accepted by `db.update_ap()` but
never stored, so the documented Layer-3 UDP fallback path was silently
dead; ghost/never-adopted APs were never purged from the database; a race
condition where both `maintenance_loop` and `fast_cmd_loop` called
`process_fast_commands()` concurrently (removed the duplicate call);
`horus-hmp.py`'s `killall -9 python3` replaced with a targeted
`pkill -9 -f 'horus-hmp\.py|horus-radius\.py'` so it stops killing unrelated
Python processes on the router; `Conflicts:` added between the two packages
(see AI_AGENT_RULES.md rule 1); the two `satellite.py` copies were
resynchronized (the client's copy had gained input sanitization and safe
`subprocess` calls that the controller's copy was missing).

### Security fixes in the same phase

- **Command injection via `horus_rrm_apply`**: the CGI spliced the raw HTTP
  request body directly into a `python3 -c "..."` shell string. Rewritten
  to pipe the body over stdin to a real `.py` script (`rrm_apply.py`) that
  parses it as JSON.
- **`admin_password` shell injection**: `root.py`'s handler built a shell
  command by string-concatenating the new password. Replaced with
  `subprocess.Popen(["passwd", "root"], stdin=...)`.
- Rescue-key wiring was fixed (`send_cmd()` now actually signs re-adoption
  attempts with the per-AP rescue secret it was already computing but never
  using) — see the code comments in `root.py` for the known limitation this
  still carries (the rescue secret is derived only from a publicly-broadcast
  MAC address, which is a documented, accepted tradeoff for now, not a
  hidden one).

## Phase 2 — Frontend: UI/UX redesign

Full visual redesign, approved via a mockup before implementation. Summary
of what changed — see [UI_DESIGN_SYSTEM.md](UI_DESIGN_SYSTEM.md) for the
system itself:

- New color system in `horus-theme.css` (lapis/violet accent + gradient,
  semantic status colors, a dedicated "pending adoption" color) replacing a
  generic Tailwind-slate palette.
- Removed ~100 lines of genuinely dead code in `map.js` (a duplicate
  row-rendering code path that was computed but never attached to the DOM).
- Replaced ~60+ hardcoded hex colors across `map.js`, `detail_v2.js`,
  `settings.js` (both projects), `i18n.js`, and `horus_injector.js` with
  theme tokens — several of these were a leftover dark-only palette that
  was unreadable in light mode, including on **native LuCI pages**
  (`horus_injector.js` decorates the stock Network > Wireless > Associated
  Stations table, which wasn't loading `horus-theme.css` at all until this
  phase — see the global `<link>` injection in `uci-defaults`).
- Unified gradient page header (`.h-page-header`) across `map.js`/`ban.js`.
- Client's `settings.js`: promoted the "connected to controller" status
  from a field buried mid-form to a hero card (`.h-hero`) at the top of the
  page; converted the "nearby APs" raw HTML table to `.h-peer-card` list
  tiles; rewrote the RRM advisor panel's hardcoded-hex inline HTML to use
  theme classes/tokens.
- `ban.js` and both `settings.js` views were missing the `.horus-container`
  base class entirely (font/color/background reset never applied) — fixed.

## Phase 3 — Real-device deployment debugging

Three rounds of "it's still broken" after the redesign shipped, each with a
distinct real root cause — documented in detail because the *symptoms*
looked similar each time (a broken-looking settings page) but the causes
were unrelated:

1. **`opkg` refused to install**: `Depends: libc, python3-light,
   python3-logging, python3-urllib` — the split packages didn't resolve on
   the target device's feed. Reverted to `Depends: libc, python3-light`
   (see AI_AGENT_RULES.md rule 3).
2. **CBI form layout broken** (huge gaps, missing-looking fields, an
   orphaned native help icon): the `.horus-settings-view .cbi-value` rules
   had been rewritten to a column-stack layout without `!important`,
   losing the cascade against the active LuCI theme's own CBI styling.
   Reverted to the original's proven row layout (title 35% / field 60%,
   `flex-wrap`), re-themed with the new tokens, with `!important` restored
   (see AI_AGENT_RULES.md rule 5).
3. **`opkg` conflict errors on install/upgrade** (`check_conflicts_for`)
   even after the target package was confirmed *not* installed
   (`opkg list-installed` empty): stale `Status: install prefer,user
   not-installed` stanzas left in `/usr/lib/opkg/status` from earlier
   partial/failed installs. Fixed by removing the specific stanza with
   `sed -i '/^Package: <name>$/,/^$/d' /usr/lib/opkg/status` — this is a
   device-side data issue, not a packaging bug, but is recorded here since
   it's a real, reproducible opkg failure mode worth recognizing quickly.
4. **Raw translation keys showing as literal text** (`header_brand`
   instead of the Arabic string) plus a duplicated page title: the browser
   was serving a stale cached `i18n.js` because — unlike `settings.js`,
   which already had version-based cache-busting — none of the other
   shared JS modules did. Generalized the rename-and-repoint mechanism to
   cover every shared module and view file in both projects (see
   AI_AGENT_RULES.md rule 4). Also suppressed LuCI's native duplicate
   `.cbi-map` title/description in favor of the custom `topBar`.
5. **Corrupted `satellite.py`** (`class DummyLog:` with a syntax-error
   stray `.handlers` statement) found on disk in both projects mid-session
   — not made by this session's own edits. Restored real `import logging` /
   `logging.handlers`. A stray `tmp/` directory inside the controller
   package source (an old duplicate of the whole `root/` tree, containing
   the same corruption) was blocking `build_ipk.py`'s sanity checks and was
   removed — see AI_AGENT_RULES.md rules 2 and 6.

## What's documented but intentionally not fixed

Two larger architectural changes were identified but deliberately not
implemented, since they change the wire protocol / trust model and need
coordinated rollout across every device, not just a code fix:

- **No real encryption.** `docs/API_AND_PROTOCOLS.md` used to describe an
  `crypto.py` module doing AES-GCM encryption; it never existed. The actual
  transport is `zlib`-compressed JSON with an optional HMAC-SHA256 signature
  (see `protocol.py`) — compression, not encryption. The docs have been
  corrected to describe this accurately instead of the fictional module.
- **Single shared `hmp_secret` for the whole network.** A per-device key
  derived via HKDF from a controller-only root secret would contain a
  single leaked device's blast radius to that device alone. Not implemented
  this session.

## Phase 3 — UI State Polishing & Activation Logic (v1.2.54)

1. **Fixed UI Input Truncation**: Inputs were cutting off Arabic text at the bottom. Changed .h-input in 3-components.css from min-height: 40px; to height: 40px !important; line-height: 38px !important;.
2. **Fixed Activation Race Condition (Optimistic UI)**: When activating an AP, the UI now instantly updates the AP to 'Activated' and re-renders the dashboard without requiring a page refresh. db.py was also updated to ignore unauthenticated heartbeats from the AP for 15 seconds after a manual activation to prevent the AP's pre-restart telemetry from reverting the UI state.
3. **Added Awaiting Activation State to APs**: The Controller now broadcasts an is_authorized: bool flag inside the 
oot_heartbeat and ACK packets. This allows the Client AP to know it is awaiting activation, rather than just showing 'Disconnected'.
4. **Fixed LuCI Cache Issue**: Added 
m -rf /tmp/luci-* to uild_ipk.py's postinst script so that users don't have to manually clear their browser cache or press Ctrl+F5 after every upgrade to see new JS/CSS.
5. **Removed Random Secret Generation**: Removed the automatic HMP secret randomization in postinst that was breaking connections when the Controller upgraded and the Client AP was left behind with the old default 123 secret. Added a migration step to revert 32-char MD5 secrets back to 123.
