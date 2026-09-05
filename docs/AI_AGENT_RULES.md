# Rules for AI Agents Working on This Codebase

Read this before touching anything. Every rule here exists because breaking it
already broke a real, deployed device during development. This is not
theoretical advice — it is a record of what actually went wrong and how to
avoid repeating it.

See also: [CHANGELOG.md](CHANGELOG.md) for the full history of what was found
and fixed, and [UI_DESIGN_SYSTEM.md](UI_DESIGN_SYSTEM.md) for the frontend
design system in detail.

## 1. The Controller and Client are two packages sharing one codebase

`Horus_Controller_Plugin` (`luci-app-horus-controller`) and
`Horus_Client_Plugin` (`luci-app-horus-client`) are **separate OpenWrt
packages that must never both be installed on the same device** — they ship
overlapping file paths (`/usr/lib/horus/*.py`, `/usr/bin/horus-hmp.py`,
`/etc/uci-defaults/99_horus-controller-patch`, several `/www/cgi-bin/*`
scripts) and each `control` file declares `Conflicts:` against the other for
exactly this reason. **Never remove that `Conflicts:` line.** If you need to
test a device that has the wrong package installed, uninstall it first —
don't work around the conflict.

Several files are meant to be **byte-identical** between the two trees:

- `usr/lib/horus/protocol.py`
- `usr/lib/horus/config.py`, `sys_network.py`, `sys_security.py`,
  `sys_utils.py`, `sys_wifi.py`
- `usr/lib/horus/satellite.py` (identical except one line: the syslog tag,
  `"horus-controller: %(message)s"` vs `"horus-client: %(message)s"`)
- `www/luci-static/resources/horus_{controller,client}/horus-theme.css`
  (must be **fully identical**, including the different directory name in
  the file path)

**Whenever you edit one of these files, copy the same edit to its sibling in
the other project and re-diff to confirm.** A drift here is how a real bug
happened this session: the client's `satellite.py` got a security fix
(input sanitization, safe subprocess calls) that never made it into the
controller's copy, and separately the controller's copy had a working
`root_heartbeat` handler that the client's copy didn't. If you're adding a
feature to `satellite.py`, `protocol.py`, or the shared CSS, always ask "does
the other project's copy need this too?"

## 2. Never disable or remove the sanity checks in `build_ipk.py`

Both projects have a `build_ipk.py` that runs `run_sanity_checks()` before
packaging: Python syntax check (`py_compile`) on every `.py` file, Node
syntax check (`node -c`) on every `.js` file, and a check for dots in LuCI
view filenames (which break LuCI's class loader). **This is not boilerplate
— it is what catches broken code before it ships.** During this session it
caught a corrupted `satellite.py` that would otherwise have shipped and
crashed the daemon on every device that installed it. If a build fails here,
the fix is to fix the actual file, not to skip or weaken the check.

Also: `build_ipk.py` walks the **entire package source directory**, not just
`root/`. Do not leave stray copies of source files anywhere under
`Horus_Controller_Plugin/luci-app-horus-controller/` or
`Horus_Client_Plugin/luci-app-horus-client/` outside the real `root/` tree —
a leftover `tmp/` directory with a stale duplicate of `satellite.py` blocked
a build for exactly this reason. If you create scratch/debug copies while
working, delete them before finishing, or put them entirely outside the
package source tree.

## 3. `Depends:` in `control` must only list packages that actually resolve

Both packages' `control` file currently declares `Depends: libc,
python3-light`. **Do not add split Python stdlib packages
(`python3-logging`, `python3-urllib`, `python3-json`, etc.) to this line
unless you have confirmed they exist in the target device's actual opkg
feed.** This was tried once and it broke installation entirely on a real
device with `pkg_hash_check_unresolved: cannot find dependency
python3-logging` — opkg refuses to install a package whose declared
dependency can't be resolved, full stop, no partial install.

If code needs a stdlib module beyond what `python3-light` bundles:
- If the module is genuinely core (like `logging`, which is used at the top
  of `root.py` and `satellite.py`), it's safe to just `import` it —
  `python3-light` includes it on every OpenWrt target this project ships to.
- If the module is more specialized (like `urllib.request`, used only for
  optional AP-side package installs from a URL), import it **lazily inside
  the function that needs it**, wrapped in `try/except`, so its absence
  degrades one optional feature instead of crashing the whole daemon or
  blocking installation.

## 4. Every LuCI JS module needs cache-busting, not just the entry view

LuCI's classloader (`'require horus_controller.i18n as horusI18n'` etc.) has
no reliable automatic cache invalidation tied to package version. If you ship
a new version of a shared module (`i18n.js`, `styles.js`, `bulk.js`,
`groups.js`, `detail_v2.js`) or a view (`map.js`, `ban.js`, `settings.js`)
under its original filename, browsers can and will keep serving an old
cached copy after the upgrade — this actually happened, and it's a nasty bug
to diagnose because the symptom (raw translation keys like `header_brand`
showing as literal text instead of Arabic, or a UI that's "half old, half
new") looks like a code bug, not a caching bug.

The fix already in place: `etc/uci-defaults/99_horus-controller-patch`
(both projects) renames every module/view file to
`<name>_<version_with_underscores>.js` on every install/upgrade, rewrites
every `'require horus_controller.X ...'` (or `horus_client.X`) reference to
match, and updates `menu.d/luci-app-horus-*.json` for the renamed views. It
is idempotent (safe to re-run for the same version) and self-cleaning (old
versioned copies get deleted on upgrade).

**If you add a new shared module or view file, you must add its name to the
`resource_modules` / `view_modules` list in that script** (both projects'
copy) or it will silently fall back to being unversioned and reintroduce
this exact bug. `horus-theme.css` and `horus_injector.js` use a simpler
`?v=<version>` query-string scheme instead (see their `<link>`/`<script>`
injection in the same script) — that works fine for files that aren't
`require`d by LuCI's classloader.

`build_ipk.py` auto-stamps the current `PKG_VERSION` into `PKG_VER="..."` in
this script (and into `var horus_version = '...';` in `styles.js`) — you
don't need to hand-edit version numbers there, just bump `VERSION` and
rebuild.

## 5. CSS overriding LuCI's native CBI form classes needs `!important`

`horus-theme.css`'s `.horus-settings-view .cbi-*` rules override the active
LuCI theme's own styling for form elements (`.cbi-value`, `.cbi-value-title`,
`.cbi-value-field`, `.cbi-tabmenu`, inputs, buttons). The active LuCI theme
is not under this project's control, and its stylesheet's specificity and
load order relative to ours can't be guaranteed. **Every rule in that
section of `horus-theme.css` needs `!important`.** Removing it (in the name
of "cleaner CSS") was tried once and produced a genuinely broken settings
page on a real device — labels stacked correctly but input fields were
pushed out of place by the native theme's leftover float/width rules,
including an orphaned native tooltip icon floating in empty space. Every
other class this project owns outright (`.h-panel`, `.h-btn`, `.h-hero`,
etc.) does **not** need `!important` — this rule is specifically for the
handful of selectors that override LuCI's own `.cbi-*` classes.

Similarly: `settings.js` in both projects must call
`horusStyles.getStyles()` itself (like `map.js` and `ban.js` already do),
not rely solely on the global `</body>` stylesheet injection in
`uci-defaults` — the settings view can otherwise render before that global
`<link>` has been fetched.

## 6. Don't hand-edit generated/patched files without re-testing

`satellite.py` in both projects was found mid-session with a hand-inserted
syntax error (`class DummyLog:` with a stray, disconnected `.handlers`
statement) — apparently an attempt to remove the `logging` import without
actually testing that the result still parsed. **Any manual edit to a
`.py` file must be validated with `python3 -m py_compile <file>` (or
equivalent) before considering the change done.** The `build_ipk.py` sanity
check will catch this too, but don't rely on the build to be your only
test — a broken daemon that fails to import crashes silently and produces
exactly the confusing "why can't the AP see the controller" symptoms this
project already has enough of.

## 7. P2P discovery is a STANDALONE fallback — never let it run alongside a controller

`peer_announce` (P2P neighbour discovery) and the controller's
`hello`/`telemetry` flow are two competing ways to build a picture of the
same network. They must never both be active on one AP, or the UI ends up
showing two different, disagreeing views.

The rule implemented in `satellite.py`'s `is_controller_managed()`:

| AP state | P2P |
|---|---|
| adopted (`hmp_secret` set) **and** controller heartbeat fresh (< 60s) | **off** — controller owns the map; peer table is cleared |
| adopted but heartbeat stale (controller died) | **on** — automatic fallback |
| not adopted (standalone), even if it overhears a controller's broadcast beacon | **on** |
| `neighbors_enabled = 0` | **off** |

Both halves of the adopted-AND-fresh condition matter. Gating on the
heartbeat alone would silence a genuinely standalone AP that merely
overhears a nearby controller's broadcast beacon; gating on adoption alone
would leave an orphaned AP permanently silent after its controller dies.

Two related invariants that are easy to break:

- **`peer_loop` must always be started** in `core.py`, never conditionally on
  the boot-time `neighbors_enabled` value. The loop re-reads the setting (and
  the controller check) every tick and returns early when it should stay
  quiet — that is what makes toggling P2P in the UI take effect without a
  daemon restart.
- **Peer TTL must scale with `neighbors_interval`** (`peer_ttl()`, currently
  `max(90, interval * 3)`). It used to be a flat 90 seconds, which silently
  broke discovery for any interval above ~90s: every peer expired before the
  next announcement could refresh it. `root.py` has a matching calculation —
  keep the two in sync.

### `peer_announce` is unsigned — treat its contents as hostile

P2P discovery has to work before any adoption exists, so `peer_announce`
frames carry **no HMAC** (`send_hmp_frame(..., secret="")`). That means
`hostname`, `ip`, and `medium` are attacker-controlled by anything on the
LAN, and they are rendered into the admin's LuCI page in two places:
`settings.js`'s peer panel and `horus_injector.js`'s wireless-table badges.

**Everything from a peer must be HTML-escaped before it touches
`innerHTML`** (`window.horusEsc` / `esc()`), and anything used in an `href`
must be validated as a literal dotted-quad IPv4 (`window.horusSafeIp` /
`safeIp()`), not merely escaped — escaping alone does not stop a
`javascript:` URI. This was a real stored-XSS hole: a malicious AP
broadcasting `hostname: "<img src=x onerror=...>"` executed script in the
admin's session, on *every* native LuCI page, since the injector runs
site-wide.

## 8. The adoption lock — a branch answers to exactly one controller

The AP lifecycle is a state machine. Breaking any one of these transitions
lets a second controller steal an AP, or leaves an AP permanently orphaned:

| State | Sends | Visible to |
|---|---|---|
| **Unadopted** (no `hmp_secret`) | bare beacon only: `type`, `src_mac`, `hostname`, `ip` — unsigned | every controller, as an adoption candidate |
| **Adopted** (`hmp_secret` + `controller_mac` set) | full `hello` + `telemetry`, HMAC-signed, carrying `adopted_by: <owner MAC>` | its owner only |
| **Ejected** (secret wiped) | back to bare beacon | every controller again |

Rules that keep this intact:

- **Never send inventory/telemetry before adoption.** `send_hello_once()`
  only adds `wifi`/`ports`/`stats`/`netmask`/`gateway` when `self.secret` is
  set, and `send_telemetry_once()` returns immediately without one. These
  frames are unsigned *and* unencrypted, and the controller discards that
  data for unauthorized APs anyway (`db.update_ap` wipes it) — sending it
  early was pure leakage to anyone sniffing the segment.
- **`adopted_by` is what makes an AP invisible to other controllers.**
  `root.py` skips any `hello`/`telemetry` whose `adopted_by` is set and is
  not its own MAC. Without it, a foreign AP's frames fail our HMAC, land in
  the DB as "unauthorized", and get offered up for stealing in the UI.
- **`controller_mac` must be persisted to UCI**, not just held in memory, or
  the lock evaporates on reboot. It is set on `set_api_key`, and self-heals
  from the first authenticated heartbeat for APs adopted by older builds.
- **Deleting an AP from the controller's DB does NOT release it.** The AP
  still holds the key and simply re-registers on its next hello. `delete_ap`
  must first send the signed `unadopt` command. This is why the UI has a
  separate **Eject** button for *online* adopted APs — an offline AP cannot
  receive the command, so the offline "delete" only removes a stale row.
- **Only the owner can evict.** `unadopt` is handled after the normal HMAC
  gate, so it must be signed with the AP's current secret. Do not add it to
  the rescue-secret whitelist in `protocol.py` (which is limited to
  `set_api_key` and heartbeats) or any LAN device could evict any AP.
- The second escape hatch is the operator clearing `hmp_secret` in the
  client's own LuCI page. `sync_identity_from_uci()` (called each hello tick)
  is what makes that take effect, including via a bare `uci set` over SSH
  with no service restart.

### Layer 2 vs the VLAN case

L2 is always used (`send_hmp_frame` broadcasts every frame at the Ethernet
layer). L3/UDP is *additional* and only engages when `dst_ip` is a real
address — the client passes `controller_ip` there, which is empty by
default. That option exists for exactly one situation: the branch and the
controller are on **different VLANs / routed segments**, where an L2
broadcast cannot reach. `sync_identity_from_uci()` re-reads it every tick so
setting it works without a restart — important, because in that scenario the
AP may never receive the heartbeat that would otherwise refresh it.

## 9. The CGI endpoints are authenticated — do not "simplify" the guard away

`/www/cgi-bin/horus_*` is served **directly by uhttpd**. These scripts never
pass through LuCI's session layer, and the `rpcd` ACL files this package ships
do **not** protect them (those only govern LuCI's own ubus calls). Until this
was fixed, anyone who could reach the router's HTTP port could, with no
credentials whatsoever: reboot every AP, set the root password, re-key the
whole mesh, push Wi-Fi profiles, and read every RADIUS subscriber's name and
balance.

Every endpoint now starts with:

```sh
. /usr/lib/horus/cgi_auth.sh || exit 1
horus_require_auth read     # or: write
```

Rules:

- **The `|| exit 1` is load-bearing.** Sourcing on its own fails *open* if the
  helper is ever missing (partial install): the script would carry on
  unauthenticated. With it, a missing guard means no service instead of an
  open door.
- **The guard must come before any output.** A 403 has to send its own
  `Status:` line, which is impossible once headers have been written. Adding a
  `printf` above the guard silently breaks the rejection path.
- **Read vs write matters.** Data endpoints ask for `read`, anything that
  writes a command file or touches UCI asks for `write`, so the ACL is
  meaningful rather than decorative.
- `horus_groups` is Python and carries its own `require_auth()` twin of the
  shell helper — **keep the two in step**. Note that `build_ipk.py`'s Python
  syntax check only looks at `*.py` files, and these CGIs have no extension,
  so it does **not** cover them: validate `horus_groups` by hand with
  `python3 -m py_compile` after editing it.
- The wildcard `Access-Control-Allow-Origin: *` was removed from the endpoints
  that had it. They are only ever called same-origin from LuCI's own pages;
  do not add it back.

**Escape hatch.** If the guard ever misfires and locks you out of the plugin's
own UI, over SSH:

```sh
uci set horus_controller.main.cgi_auth='0'; uci commit horus_controller
```

That relaxes only the HTTP endpoints back to their old behaviour — daemons,
adoption and the HMP protocol are unaffected. It is intended as a recovery
path, not a normal configuration.

### Still open (deliberately not fixed here)

`horus_groups` builds `uci set` commands by string-concatenating the group
name/SSID/password from the request body, so a quote in a group name is an
injection. Authentication now limits this to logged-in admins (it is no longer
reachable by an anonymous LAN device), which drops it from critical to
low-severity, but it should still be converted to argument-list `subprocess`
calls like the rest of the codebase.

## 10. Commands are queued and acknowledged, not fired and forgotten

Every command the controller sends to a *specific* AP (Wi-Fi config, reboot,
ban to a named AP, eject/unadopt, set_api_key, admin_password, ...) goes
through `HorusDB`'s command queue (`db.py`: `enqueue_cmd` /
`cmd_due_for_send` / `mark_cmd_sent` / `mark_cmd_result`), not a direct
`send_cmd()` call. Lifecycle: `queued -> sent -> acked` (or `failed` after
`CMD_MAX_ATTEMPTS` unacknowledged retries, spaced `CMD_RETRY_INTERVAL`
seconds apart). `RootNode.dispatch_queue()` (called every `fast_cmd_loop`
tick, alongside `process_fast_commands()`) is what actually sends due
entries; `listen_loop()`'s `cmd_ack` branch is what completes them.

**Why:** before this, `process_fast_commands()` sent once and deleted the
command file immediately — a dropped frame (common on a broadcast L2
network) looked identical to success in the UI. There was also no state that
survived a daemon restart, so a command in flight when the daemon crashed
just vanished.

**What still bypasses the queue, on purpose:** any command whose target is
`'ALL'` or the broadcast case for `ban`. There's no single AP to track an ack
against for those, so they remain the old best-effort broadcast. Don't route
them through `enqueue_cmd` without first deciding how a multi-AP ack should
aggregate — that's unsolved, not an oversight.

**The ack itself, on the AP side** (`satellite.py`, both projects — keep
byte-identical per rule 1): sent from one single insertion point right after
the ban/wifi_config/ap_manage dispatch chain in `listen_loop()`, gated on
`cmd_id` being present (so an older controller that never sends `cmd_id`
gets no ack, harmlessly). **Capture `ack_secret = self.secret` before
dispatch, not after.** The `unadopt` action clears `self.secret` as part of
handling the command — if the ack read `self.secret` fresh afterward it
would go out unsigned, the controller would drop it (fails HMAC), and the
queue would report a `failed` eject that actually succeeded. This exact bug
was caught by `test_phase0_satellite_ack.py`'s "unadopt ack signed with the
PRE-unadopt secret" case before it shipped — if you touch the ack block,
re-verify that case specifically.

## 11. `/tmp/horus_network_state.json` is world-readable-to-any-LuCI-session — never put a secret in it unredacted

`db.py`'s `save()` writes the SAME `self.state` to two places: `db_path`
(engine-internal, `/tmp/horus_db.json`) and `/tmp/horus_network_state.json`
(what `horus_map_data` and friends hand straight to the browser for anyone
with a valid LuCI session, not just admins). The command queue can
legitimately carry a plaintext Wi-Fi password in transit — `_redacted_state()`
is what strips it (and `rescue_secret`) before that second, HTTP-facing copy
is written. If you add another field to a queued payload that could be a
credential, redact it there too. The flash snapshot
(`/etc/horus/state_snapshot.json`, see rule 12) is NOT redacted — it's never
served over HTTP, same trust boundary as `/etc/config/horus_groups` already
storing SSID passwords in plaintext.

## 12. Controller state now survives a reboot — via a rate-limited flash snapshot, not by writing state to flash on every change

`HorusDB.load()` falls back to `/etc/horus/state_snapshot.json` when
`/tmp/horus_db.json` doesn't exist (a fresh boot: `/tmp` is tmpfs and was
just wiped). That snapshot is written by `snapshot_if_due()`, called once
per `maintenance_loop` tick but internally rate-limited to at most once every
`PERSIST_INTERVAL` (90s) **and only when the content actually changed**
(compared by hash). **Do not call `snapshot_if_due` more often, and do not
make it write unconditionally** — `self.state` changes on nearly every
`update_ap`/`update_clients` call (RSSI, timestamps), and OpenWrt's flash has
a finite write-cycle budget; the real-time copy already goes to `/tmp` via
the existing `save()` on every change, this is purely the reboot-survival
fallback and should stay infrequent.

## 13. Foreign APs get their own dict — never let them into `self.state["aps"]`

An AP adopted by a *different* controller is now recorded in
`self.state["foreign_aps"]` (`db.py`: `note_foreign_ap` / `cleanup_foreign_aps`)
instead of being silently dropped — see `root.py`'s `listen_loop()`, the
`adopted_by` check right after the auth gate. **This dict must stay
completely separate from `self.state["aps"]`.** RRM auto-channel, smart
steering, and the anti-spoof loop all iterate `self.db.get_aps()` /
`get_all_aps()` assuming every entry is a device this controller is allowed
to command — mixing a foreign AP into that dict would let those loops try to
push a Wi-Fi channel change or a steer command to hardware we don't own and
whose secret we don't hold (the command would just fail HMAC on their side,
but the intent is that this controller should never even try). `foreign_aps`
records are read-only, display-purposed, and never touched by any command
dispatch path.

## 14. `map.js`'s zero-flicker in-place row update can't patch structural
    changes — check `dataset.rowSig` before assuming a poll refreshed correctly

`updateDashboardTableInPlace()` patches existing `<tr>` elements in place
(status dot, hostname, IP, speeds) without rebuilding them, for performance.
That only works for changes that don't alter the row's *shape* — the action
button set and wifi pills are completely different between "unauthorized",
"pending adoption" (queued/sent/failed), and "authorized". Each row carries
`tr.dataset.rowSig = ap.unauthorized + '|' + adoptStatus`; when the incoming
data's signature differs from what's stored, the row is fully replaced via
`createApTableRow()` instead of patched. **If you add another state that
changes which buttons a row shows, you must fold it into `rowSig` too** — an
easy way to reintroduce "the button doesn't update until a manual page
reload" bugs, which is exactly what made the original optimistic
`ap.unauthorized = false` hack necessary before the command queue existed to
report the truth.

## 15. Never let a WiFi password reach a hello/telemetry payload, or `_redacted_state()`

`get_wifi_info()` (`sys_wifi.py`, shared) returns each radio's CURRENT
password straight out of UCI -- that's correct and necessary for local use,
but it must never leave the device. `satellite.py`'s `send_hello_once()` and
`send_telemetry_once()` call `_wifi_info_no_secrets()` (a thin wrapper that
strips `password` from each entry) instead of `get_wifi_info()` directly.
**If you add another place that puts `get_wifi_info()`'s result into an
outgoing HMP frame, route it through `_wifi_info_no_secrets()` too** — those
frames are compressed but NOT encrypted, broadcast to the whole L2 segment,
so anything in them is readable by anyone with a sniffer, no authentication
required.

This was a real, shipped vulnerability (found while investigating the data
source for Phase 2's topology view, fixed in `1.3.2`/`1.2.64` before Phase 2
itself): every adopted AP broadcast its own WiFi password in cleartext on
every hello/telemetry cycle, and the controller both stored it and served it
back through `horus_map_data` to any authenticated LuCI **read**-scope
session — not just whoever configured it.

Two more layers exist specifically because of that incident, and both must
stay:
- `db.py`'s `_redacted_state()` also strips `password` from every
  `aps[mac]["wifi"]` entry before the HTTP-facing copy is written — this is
  defense-in-depth for an already-adopted AP still running a pre-`1.3.2`
  build that still sends the password; once it upgrades, this path finds
  nothing to redact.
- `detail_v2.js`'s per-AP WiFi edit form never pre-fills the password field
  with the stored value (`value: ''`, type `password`). This isn't just
  about not leaking it to the screen — leaving it blank and saving already
  preserves whatever password is currently set, because `apply_wifi_config`
  (`sys_wifi.py`) only ever *sets* a new key when one is explicitly provided
  (`if key: uci set ...`), it never needs to read the old one back. Don't
  "restore" a pre-filled password field without re-verifying that.

## 16. Topology has no dedicated protocol message — it's derived, not broadcast

`db.py`'s `compute_topology()` builds the AP-to-AP link list entirely from
data every AP already sends in `hello`/`telemetry` (bridge forwarding
tables for wired links, `radio_macs` cross-referenced against every other
AP's associated-clients list for wireless backhaul). **This is deliberate,
not a missing feature**: P2P `peer_announce` — which WOULD be the natural
source for this — is fully gated off while controller-managed (see
`is_controller_managed()` in `satellite.py`), and that gate must never be
relaxed just to feed topology (the earlier P2P-fix round exists specifically
to guarantee "everyone talks only to the controller" when one is present).

If you need another cross-AP signal, extend the ALREADY-flowing
hello/telemetry payload (like `radio_macs` was added), never re-enable or
special-case `peer_announce` for it.

`compute_topology()`'s `confirmed` flag means two INDEPENDENTLY-reported
facts agree — one AP's own report plus a second, different AP's own report
— not a single side's claim. Keep that property if you touch the wired or
wireless detection loops; it's what backs the "أدق من UniFi" (more accurate
than UniFi, which only has one-sided self-reports) claim in the product
vision.

`compute_topology()` only considers authorized (adopted) APs — an
unauthorized or foreign-owned device is never a topology node, matching
rule 13's separation between `aps` and `foreign_aps`.

## 17. `postinst` must not force-reload rpcd unless the ACL actually changed

`build_ipk.py` generates a `postinst` that ends with an rpcd reload and (until
this rule) an unconditional `uhttpd restart`. **Both are dangerous to run
unconditionally on every single install/upgrade**: `/etc/init.d/rpcd reload`
(or its `restart` fallback) resets rpcd's in-memory session table, which is
the ONLY thing backing every LuCI login on that device (OpenWrt 23.05+ has
no `/tmp/luci-session-*` files to inspect — that's a leftover naming
convention from the old Lua-CBI LuCI; sessions live entirely inside rpcd).
Reload it and every admin's active login on THAT device is invalidated —
its dashboard/status endpoints (guarded by `cgi_auth.sh`, rule 9/10) start
403'ing until they log back in. Across a deployment with many APs, that
turned every routine package update into what looked like a total outage.

**This was a real, shipped incident** (fixed in `1.3.5`/`1.2.66`), diagnosed
live via SSH against real hardware: `cgi_auth.sh` and the rpcd ACL grant
were both proven 100% correct — a manually-created session authenticated
and fetched data successfully on both the controller and a client. The
controller's own `/tmp/horus_network_state.json` had 5 live, actively
reporting APs the whole time. The only thing actually broken was that the
browser's existing session no longer existed server-side, because the
*previous* install's postinst had just reset rpcd.

**The fix**: `postinst` now hashes the ACL file it's about to install and
compares it to `/tmp/.horus_acl_hash` (written by the previous install). It
only calls `rpcd reload`/`restart` when the hash differs — i.e., only when
an update genuinely adds/changes an ACL grant, not on every code-only or
UI-only update (which is nearly all of them). **If you ever add a new ACL
entry, this reload will correctly still fire — don't try to skip it or make
the check less precise.** The `uhttpd restart` was removed outright, not
just guarded: CGI scripts execute fresh on every single request with
nothing to invalidate, and static JS/CSS is already cache-busted via
renamed filenames + `?v=` query strings (rule 4) — the restart bought
nothing here, only added a second disruption on top of the rpcd one.

If you ever need to intentionally force every device to drop its sessions
(e.g. after a real security-relevant ACL tightening), that's the one
legitimate reason to bump the ACL file's content (even a comment-only
change) so the hash naturally differs and the reload fires — don't add a
separate unconditional call back in.

## 18. `set_api_key`'s secret is resolved server-side — the browser never sources it

`root.py`'s `process_fast_commands()` fills in `cmd['key']` from `self.secret`
(the controller's own loaded secret) whenever an AP-adoption request didn't
supply one, and refuses to enqueue the command at all if `self.secret` is
also empty (an empty key would "adopt" the AP with a falsy secret, leaving
it stuck reporting as if still unadopted — every `if self.secret:` check on
its side would read false). `map.js`'s `sendAdopt()` deliberately sends
`{target_ap, action: 'set_api_key'}` with **no `key` field at all**.

**Do not reintroduce a client-side secret lookup** (e.g. `L.uci.load('horus_controller')`
before the fetch). That was the original design, and it caused a real,
confirmed incident: a multi-AP "أدوبت الكل" click silently dropped one
target with no visible error — diagnosed live via SSH against real
hardware, tracing all the way down to the fact that the manually-replayed
CGI call (same payload, no browser involved) worked instantly. The exact
JS-side failure was never pinned down, which is itself the argument for
this fix: removing the client's dependency on LuCI's async UCI/form-loading
machinery for something the server already has loaded removes the entire
failure class, not just the one symptom that was caught.

## 19. Golden rule reminder (from the original architecture docs)

Layer 2 HMP (raw Ethernet, EtherType `0x88B5`, interface `br-lan`) is the
default and required transport for discovery, adoption, and heartbeats.
Layer 3 UDP is opt-in only, triggered exclusively by the user typing an IP
into the `Controller IP` field. Nothing in this session's changes altered
this rule — see `ARCHITECTURE.md` for the full explanation, including the
`raw_sock.bind(("br-lan", ...))` vs `raw_sock.bind(("", ...))` pitfall.

## 20. `horus-radius.py`'s `http_req()` never actually did TLS — `https://` base URLs silently failed

`SasEngine`/`DmaEngine`/`AdvEngine` all share one hand-rolled HTTP/1.0 client,
`http_req()`. It used to strip an `https://` prefix off the URL and then open
a **plain, unencrypted** `socket.socket(...)` regardless — no `ssl` handshake
ever happened. Against a plain-HTTP LAN panel this was invisible. Against
anything actually served over HTTPS (a cloud-hosted SAS/DMA panel behind a
domain, e.g. fronted by Cloudflare) it silently produced garbage/empty
responses, `http_req()` returned `None`, and the sync loop reported
`"offline"` with no error anywhere to explain why.

- **Fix**: `http_req()` now detects `https://`, opens the TCP socket exactly
  as before, then wraps it with `ssl.create_default_context().wrap_socket(s,
  server_hostname=host)` before sending the request. `server_hostname` is
  required, not optional — it drives SNI, and SNI is exactly what a
  Cloudflare-fronted domain (or any shared-IP reverse proxy) needs to route
  the connection to the right backend. Default port also now follows the
  scheme (443 for `https://`, 80 for `http://`) when the URL has no explicit
  `:port`.
- **Verified against a real public HTTPS endpoint** (`https://httpbin.org/get`,
  a Cloudflare-fronted domain with a real CA-signed cert) — full TLS
  handshake + SNI + JSON parse succeeded end-to-end. This was not a unit
  test with a mocked socket; it was a live TLS round-trip over the internet.
- **If you add a new RADIUS engine class**, route it through this same
  `http_req()` rather than writing another raw socket client — that's the
  whole point of centralizing it, and it's what makes fixes like this one
  apply to every RADIUS type at once instead of needing to be found and
  fixed three separate times.

## 21. Two more RADIUS engines added: ICM Radius and MikroTik User Manager 7 — and why MikroTik-the-router itself is NOT one of them

The user has a separate Flutter app (`D:\sas4\ops-go\opsgo`) that already
talks to SAS, DMA, ADV, ICM, User Manager 7, and MikroTik routers directly.
They asked for the extension's RADIUS system to support the same panels —
explicitly using the *existing* fast pattern (one HTTP request per sync
cycle, matched against connected MACs via an in-memory dict — what
`DmaEngine` already does), not the Flutter app's own bulk-paginated
sync-then-cache approach, which they described as slower to show newly
connected users. `IcmEngine` and `Um7Engine` (`horus-radius.py`) both follow
`DmaEngine`'s shape exactly for this reason. **Explicitly excluded per the
user's request: the Flutter app's "Smart" radius type — do not add it.**

- **`IcmEngine`**: ICM only exposes one endpoint,
  `/api/users/list/index.php` (auth via `username`+`password`+`key` query
  params, same shape as DMA), which returns the *entire* subscriber list —
  there's no per-mac search endpoint like SAS/DMA have. `limit=5000` in a
  single request stands in for a real filtered lookup; the online/offline
  split (`status.is_online`) and the mac/ip match against `connected_macs`
  both happen locally afterward, so it's still exactly one HTTP round trip
  per sync cycle regardless of connected client count — same complexity
  class as `DmaEngine`, not the Flutter app's paginated crawl.
- **`Um7Engine`**: talks to RouterOS v7's own **native REST API**
  (`GET /rest/user-manager/session`, HTTP Basic Auth), not a PHP panel.
  Filters on the `active` field client-side (no server-side query filter
  available). No balance/quota is reported — User Manager 7 has no wallet
  concept, packages are enforced at the router level.
- **RouterOS REST is TLS-only by default with a self-signed cert.**
  `Um7Engine` calls `http_req(..., verify=False)` deliberately — every other
  engine keeps full certificate validation (see rule 20), but a MikroTik
  router's own admin API is not something with a real CA-signed cert to
  check in the first place, the same trust model as any router's local
  HTTPS admin panel. `http_req()` gained a `verify` parameter (default
  `True`) specifically to allow this one exception without weakening TLS
  validation for the cloud-hosted RADIUS panels.
- **ICM's `key` parameter is genuinely required with no safe default —
  confirmed against the Flutter app itself**, not just assumed: the opsgo
  source never hardcodes an ICM key anywhere (unlike DMA's well-known
  `Mohamady_Radius_2026`, which IS hardcoded there); the app only ever
  reads it back from what the admin typed in. So `IcmEngine` doesn't invent
  one either (`api_key or ""` — an empty key is sent as empty, not
  papered over). It must be set via
  `uci set horus_controller.main.api_key=...` over SSH; there's still no UI
  field for it (matches the user's explicit preference from the DMA
  review) — **ICM will not work until this is set**, unlike DMA.
- Verified with `test_icm_um7_engines.py` (23 cases against the real
  `horus-radius.py`, mocked `http_req`): both engines correctly extract
  only the actually-online/active user, resolve mac/ip/username/quota/
  balance fields from realistically-shaped server responses, issue exactly
  one HTTP call per sync cycle regardless of connected-client count, and
  degrade to `[], "offline"` (not a crash) on auth failure or an
  unreachable/malformed response.

## 22. A fifth engine: MikroTik direct (RouterOS API, v6 and v7, hotspot + PPPoE) — with real server-side filtering, not client-side

Follow-up to rule 21: the user clarified that MikroTik-the-router should
be added after all, as its own `radius_type` (`mikrotik`), separate from
User Manager 7. Two requirements made this a real reimplementation rather
than a port of the Flutter app's own code:

- **Support both RouterOS v6 and v7.** The binary API (length-prefixed
  word/sentence framing) has been unchanged since RouterOS v3, so one
  client (`MikrotikApiClient` in `horus-radius.py`) speaks to both. Login
  has two paths in one round trip: send `/login =name= =password=`
  directly; RouterOS >= 6.43 and v7 reply `!done` immediately, while an
  older router embeds an MD5 challenge in that same reply (`=ret=<hex>`),
  which triggers a second `/login =name= =response=00<md5>` call
  (`MD5(0x00 + password + challenge_bytes)`). This mirrors the Flutter
  app's own login strategy in `mikrotik_service.dart` (`login()`), minus
  its socket-retry/reconnect resilience layer, which is about flaky-link
  recovery, not version support — the polling daemon just retries on the
  next `sync_interval` tick regardless.
- **Filtering happens on the router, not on the AP.** The user was
  explicit about this: the AP's own CPU must not pull every active
  hotspot/PPP session and filter locally. `MikrotikApiClient.query()`
  builds RouterOS's native server-side filter — one `?mac-address=<mac>`
  (or `?caller-id=<mac>` for PPP) word per connected MAC, OR'd together
  with `?#|` operators — so the router itself only returns rows for the
  MACs actually connected on this AP's WiFi. Notably, **the Flutter app
  itself does NOT do this** (`mikrotik_user_queries.dart` fetches the
  entire active list and filters in Dart) — this is a deliberate
  improvement over the reference implementation, not a port of it.
- **Both hotspot and PPPoE are queried, matched by different fields**:
  `/ip/hotspot/active/print` filtered on `mac-address`, `/ppp/active/print`
  filtered on `caller-id` (PPPoE's own field for the client's MAC) — a
  subscriber is on one or the other, never both.
- RouterOS reports session length as a duration string, not seconds
  (`"1h2m3s"` on newer output, `"2w3d10:20:30"` on the classic API) —
  `parse_routeros_uptime()` handles both shapes and is now also used by
  `Um7Engine` (previously left at a hardcoded `0`, since at the time there
  was no parser for it yet).
- No balance/quota/package name is reported — a bare MikroTik connection
  (hotspot or PPP active session) carries none of that; it lives in User
  Manager or a RADIUS panel, not on the router itself.
- Verified with `test_mikrotik_engine.py` against a **real TCP socket**
  speaking the actual wire protocol (not a mocked function call) — three
  fake RouterOS servers in background threads covering: plain v6.43+/v7
  login with both hotspot and PPP results correctly matched and uptime
  parsed; the legacy MD5 challenge-response path end-to-end (own MD5
  computed independently in the test, not reusing the engine's own
  formula, so a bug in the digest calc wouldn't hide itself); and a
  rejected login degrading to `[], "offline"` without crashing. The
  server-side filter assertion inspects the literal bytes received by the
  fake router and confirms one `?mac-address=` per connected MAC plus
  `len(macs)-1` `?#|` operators — i.e. it verifies the router was actually
  asked to filter, not just that the final output happened to be right.

## 23. The ACL-hash file that gates rpcd reload (rule 17) lived in `/tmp` — wiped on every reboot, defeating its entire purpose

Rule 17 fixed `postinst` reloading rpcd (and killing every LuCI session)
unconditionally on every install by comparing the ACL file's hash against
the hash from the previous install, only reloading when it actually
changed. That comparison hash was stored at `/tmp/.horus_acl_hash` —
**`/tmp` is tmpfs, wiped on every reboot.** Any device that gets rebooted
for any reason (power blip, watchdog, a manual reboot) between installs
loses that file, so the very next update finds `OLD_ACL_HASH` empty,
"detects" a change that never happened, and reloads rpcd anyway — the
exact session-killing behavior rule 17 was written to eliminate, just
gated on "has this device rebooted since its last update" instead of "did
the ACL actually change". For a fleet that reboots routinely, this made
the fix far less effective than it looked in testing (a dev box that
isn't power-cycled between test installs never notices).

**Found live**: a user reported the Client's own settings page showing
both "🔴 غير متصل بالكنترولر / LuCI login required" AND, on the same
page, the RADIUS tab showing "🟡 متصل ولكن بيانات الدخول غير صحيحة" right
after an opkg update. Investigated over SSH on the actual device
(`192.168.109.145`): decrypted the stored SAS password from UCI and
replayed the exact login request `horus_test`'s `test_sas()` sends
(AES-encrypted payload, same URL construction) directly against the real
SAS server — it returned a valid token immediately. **The credentials
were never wrong.** Running the CGI script's own body directly (bypassing
only the cookie check) also succeeded cleanly. Both "errors" were the
same one root cause: `cgi_auth.sh`'s `horus_deny()` returns
`{"status":"error","error":"forbidden","message":"LuCI login required"}`
for ANY blocked request, RADIUS test included — and the RADIUS status
widget's JS had no way to tell "our own auth guard blocked this" apart
from "the RADIUS server rejected these credentials"; both landed in the
same generic `status_auth_error` label. See rule 24 for that UI fix.

- **Fix**: `ACL_HASH_FILE` moved to `/etc/.horus_acl_hash` — `/etc` is
  part of the overlay filesystem and survives a reboot, so the hash
  comparison actually reflects "did the ACL change between installs",
  not "did the device reboot since its last install".
- If you ever add another file that a `postinst`/`preinst` script writes
  specifically to detect state *across* installs (not just within one
  script run), it needs to live somewhere that survives a reboot — `/etc`
  or another overlay path, never `/tmp`.

## 24. RADIUS status widget mislabeled our own `cgi_auth` 403 as "RADIUS credentials invalid"

Direct fallout from rule 23: `horus_test`'s JS caller (`settings.js`)
only checked `d.success`; anything falsy fell straight to
`status_auth_error` ("🟡 متصل ولكن بيانات الدخول غير صحيحة" / "credentials
invalid") without checking *why* it failed. A `cgi_auth.sh` denial
(`d.error === "forbidden"`) looks exactly like a real RADIUS rejection to
that check, so an expired browser session — nothing to do with the RADIUS
server at all — reads as "your SAS/DMA/etc. password is wrong". This is
almost certainly what actually happened in the *original* incident this
whole session started from (the user reported the RADIUS panel saying
credentials were wrong after an update): the credentials were fine then
too, most likely, it's just that no one had a way to see the request was
being blocked by our own guard rather than rejected by the RADIUS server.
- **Fix**: added a `d.error === 'forbidden'` branch before the generic
  failure case, showing a new `status_session_expired` string ("🔄 انتهت
  جلستك -- حدّث الصفحة وسجّل الدخول من جديد") instead of the misleading
  credentials-invalid label. Applied to both packages' `settings.js`
  (identical widget in each) plus the matching i18n key in both
  `i18n.js` files (AR + EN).
- The controller-connection "hero" status widget (`refreshHeroStatus()`,
  same file) was NOT changed — it already surfaces `d.message` verbatim
  in its subtitle, so a `cgi_auth` denial already shows the true
  "LuCI login required" text there; only the RADIUS test widget was
  translating the failure reason into something misleading.

## 25. `cgi_auth` denied 100% of real browser requests — LuCI's session cookie is scoped to `/cgi-bin/luci/` and never reaches `/cgi-bin/horus_*`

The single root cause behind every "🔴 غير متصل بالكنترولر / LuCI login
required" report, and behind the RADIUS tab claiming valid credentials were
invalid (rule 24). LuCI issues its session cookie as:

    set-cookie: sysauth_http=<32hex>; path=/cgi-bin/luci/; SameSite=strict; HttpOnly

**`path=/cgi-bin/luci/`.** Our endpoints live at `/cgi-bin/horus_*`, which is
NOT under that path, so the browser correctly never sends the cookie to them.
`cgi_auth.sh` (and its Python twin in `horus_groups`) looked only for a
`sysauth*` cookie, found nothing, and returned 403 — **for every request, from
every logged-in admin, always**. The guard was not "occasionally strict"; it
was unconditionally closed to browsers from the day it was added. It only
appeared to work because the escape hatch (`cgi_auth='0'`) had been set on the
devices used for testing, which silently disabled the whole guard.

Why it hid for so long: `curl`-with-a-cookie-jar tests over SSH *pass*, because
curl scopes cookies per path too but a hand-written `-H 'Cookie: sysauth=...'`
bypasses scoping entirely — so every manual reproduction succeeded while every
real browser failed. **Reproduce auth problems in an actual browser, or by
inspecting `HTTP_COOKIE` as the CGI itself sees it — never with a hand-set
Cookie header, which is exactly the case that cannot fail.**

- **Fix**: the frontend mirrors `L.env.sessionid` into a second cookie,
  `horus_sid`, scoped to `path=/cgi-bin/` with `SameSite=Strict`, and both
  guards accept it as an alternative to `sysauth*`. It is the SAME session id
  and is still validated by `ubus call session access`, so it grants nothing
  on its own — verified live that a random/forged id and a
  `evil_horus_sid=`-style prefix both still get 403.
- `SameSite=Strict` is load-bearing, not decoration: without it this cookie
  would be attached to cross-site requests and re-open CSRF against every
  endpoint the guard protects. Never drop it.
- The cookie is set in `i18n.js` (module load — covers every plugin view, all
  of which `require` it), in `horus_injector.js` (before each poll — it runs
  on pages where LuCI's JS may still be initialising), and in
  `horus_augment.js`. If you add a new standalone script that calls these
  endpoints, set the cookie there too.
- **`horus_groups` is a Python CGI with its own hand-rolled copy of the same
  guard** (`require_auth()`), because it does not source the shell helper.
  Any change to the auth logic must be made in BOTH files or the two drift —
  which is precisely how it kept its own copy of this bug.

## 26. `E('button', {disabled: false})` renders a PERMANENTLY DISABLED button — `disabled` is an HTML boolean attribute

`disabled` is a boolean attribute: the browser disables the element if the
attribute is *present at all*, whatever its value. `disabled="false"` is still
disabled. LuCI's `E()` sets attributes literally, so
`E('button', { disabled: someFalseFlag })` emits `disabled="false"` and
produces a dead button.

This shipped on the per-AP "تفعيل الإكسس" (Activate) button in `map.js`, which
meant **the individual adopt button was unclickable in every state, for every
AP, always** — the user could only ever adopt via "ضم الكل" (Adopt All), which
does not go through that button. Confirmed live by reading the rendered
`outerHTML` (`disabled="false"`, `button.disabled === true`), and confirmed
fixed by clicking the real button in a browser and watching the target AP's
`hmp_secret` get set.

- **Fix**: build the attribute object and only add the key when it should be
  disabled (`if (btnDisabled) attrs.disabled = '';`).
- **Never pass a falsy value to a boolean attribute** (`disabled`, `checked`,
  `readonly`, `required`, `selected`, `multiple`) in an `E()` call. Add the
  key conditionally instead.
- When you change a button's enabled/disabled logic, verify it in a browser by
  reading `outerHTML` — a `disabled` bug is invisible in the source review and
  invisible in any test that does not render.

## 27. A completed command in the queue must age out, or it describes the UI forever

`getAdoptStatus()` returned the newest `set_api_key` queue entry for an AP
*regardless of age*, and the renderer treats `acked` as "⏳ جاري التفعيل..."
+ disabled. The queue keeps completed entries, so an AP that was adopted once
and later released (ejected, secret cleared on the AP side, re-flashed) still
had an old `acked` entry on file — pinning its button to a permanent
"activating" state. Together with rule 26 this is what the user saw as "زر
الضم مش عارف اضغط عليه لو فردي وظاهر كلمه جاري الضم فقط".

- **Fix**: ignore entries older than `ADOPT_INFLIGHT_WINDOW` (30s — the
  backend gives up after ~10s of retries, so anything older is finished).
  Past that window the AP's own current authorized/unauthorized state is the
  truth, not a stale command.
- **Age it against `state.data.router_time` (the CONTROLLER's clock), never
  the browser's `Date.now()`.** Clocks in this fleet have been observed
  ~22 hours apart between an AP and its controller; a browser-side age
  comparison would be either always-stale or never-stale depending on which
  way the skew ran. `router_time` and `created_at` both come from the
  controller, so their difference is always meaningful.
- Covered by `test_adopt_button_state.js` (12 cases): stale `acked`/`sent`
  entries release the button, genuinely in-flight ones still show progress,
  the newest entry wins regardless of array order, another AP's commands
  never affect this AP, and a controller too old to send `router_time`
  degrades to the previous behaviour instead of breaking.

## 28. Never `import ssl` (or any non-core stdlib module) at the top of a hot function — python3-light has no `ssl`

I caused a fleet-wide RADIUS outage with this. Adding HTTPS support to
`horus-radius.py`'s `http_req()` started it with:

    import socket, ssl, json

OpenWrt's `python3-light` — the only Python these APs have (rule 3) — **does
not ship the `ssl` module**. So that line raised `ImportError` on EVERY call,
including plain `http://` ones, `http_req()` returned nothing for everything,
and every AP reported its RADIUS server as **offline** — no subscriber names,
no quotas, "الرديس غير متصل" on every wireless row. Confirmed on-device with
`python3 -c 'import ssl'` → `ImportError`.

What made it hard to spot: the settings page's own "connection status" test
(`horus_test`) is a **shell** script using `curl`, so it kept reporting
"✅ متصل بالسيرفر بنجاح" while the Python daemon that actually fetches the
data was dead. Two different code paths to the same server, only one broken.
**When a status indicator and the real data disagree, suspect that they do
not share an implementation.**

- **Fix**: `import ssl` moved inside the `if use_tls:` branch, wrapped in
  `try/except ImportError`. Plain HTTP — what every existing deployment uses
  — never touches it. When `ssl` is genuinely missing and the URL *is*
  `https://`, `_http_req_via_tool()` falls back to `curl` (preferred: it can
  send the Authorization headers the SAS/UM7 engines need) or
  `uclient-fetch`, both of which link libustream and do real TLS. Same lazy
  treatment in `MikrotikApiClient.connect()`, so the plain API port 8728
  keeps working on a device that cannot do TLS at all.
- **Rule**: in `horus-radius.py` / `satellite.py` / anything running on the
  APs, only `os, sys, time, json, re, subprocess, threading, socket,
  logging, hashlib, base64` are safe at import time. Anything else goes
  inside the function that needs it, in a `try/except ImportError`, with a
  degraded path — never at module or function top level where it takes down
  callers that never needed it.
- Covered by `test_no_ssl_module.py`, which blocks `import ssl` process-wide,
  loads the real shipped `horus-radius.py`, and asserts that plain HTTP and a
  full `SasEngine` login still work, that `https://` degrades to `None`
  instead of raising, and that the curl fallback is actually invoked.
