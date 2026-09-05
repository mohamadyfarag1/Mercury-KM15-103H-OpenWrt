# Troubleshooting the Controller

## 1. APs Not Showing in the Controller UI (Layer 2 Failure)
**Symptoms:** Client AP is powered on and connected to the same switch/VLAN, but does not appear in the "Unauthorized" or "Map" tabs.
**Causes & Fixes:**
- **Socket Bind Error:** Ensure `protocol.py` is binding the raw socket to `"br-lan"` and NOT `""`. OpenWrt drops empty string interface binds with `[Errno 19] No such device`.
- **Bridge Filtering:** Check if the physical switch (e.g., MikroTik) is dropping EtherType `0x88B5`. Use a Python raw sniffer to test if frames arrive.
- **Daemon Crash:** Run `logread | grep horus` to see if the Python script crashed.

## 2. AP Stuck as "Disconnected" (Red) After Adoption
**Symptoms:** AP was adopted, but after a few minutes, it shows as disconnected.
**Causes & Fixes:**
- **Key Mismatch:** The API Key on the Client (`/tmp/horus_controller_info.json`) might not match the one stored in the Controller's database (`/tmp/horus_network_state.json`). Force delete the node from the Controller UI and restart the Client to trigger a fresh adoption.
- **Heartbeat Timeout:** The AP might have lost physical Layer 2 connectivity. Check the cabling or Wireless WDS bridge.

## 3. Python Syntax Errors After Edits
**Symptoms:** Daemon fails to start completely.
**Causes & Fixes:**
- Python 3 is strictly indented. Check for mixed tabs and spaces in `/usr/lib/horus/*.py`.
- Run `/usr/bin/python3 /usr/bin/horus-hmp.py` manually in SSH to see the exact stack trace (this is the real entry point — `horus-controller.py` does not exist).
- Before shipping any manual edit to a `.py` file, run `python3 -m py_compile <file>` locally. A real incident: `satellite.py` was found mid-project with a hand-inserted syntax error that `build_ipk.py`'s own sanity check caught, but only because the build was run — a device that had this file copied onto it directly would have had a permanently dead daemon with zero log output (the import itself failed).

## 4. UI Stale Data / Ghost APs
**Symptoms:** APs that were physically unplugged hours ago still show up, or old IP addresses are displayed.
**Causes & Fixes:**
- The JSON state file might be corrupted or caching old data.
- Run `rm /tmp/horus_network_state.json` and restart the controller daemon `/etc/init.d/horus_controller restart` to force a clean slate.
- `HorusDB.cleanup_stale()` also purges never-adopted (`unauthorized`) APs automatically if they haven't been seen in a while — adopted APs are intentionally kept and shown offline rather than removed, since users expect them to stay visible until explicitly deleted.

## 5. Duplicate Daemons
**Symptoms:** Port 8885 in use, or erratic adoption behavior.
**Causes & Fixes:**
- Ensure the `luci-app-horus-client` package is NOT installed on the Controller device — and vice versa. The two packages declare `Conflicts:` against each other in their `control` files specifically because they ship the same file paths; opkg should refuse to let both be installed at once. If you still find both present (e.g. from a leftover install predating that safeguard, or from files copied outside opkg), remove one.

## 6. `opkg install`/`upgrade` fails: `cannot find dependency python3-logging` (or `python3-urllib`)
**Symptoms:** LuCI's Software page shows `pkg_hash_check_unresolved: cannot find dependency ...` and refuses to install.
**Cause:** the package's `Depends:` line listed a split Python stdlib package that doesn't exist in this device's opkg feed. This project's `control` should only ever declare `Depends: libc, python3-light` — see `AI_AGENT_RULES.md` rule 3 for why and what to do instead if new code needs another stdlib module.
**Fix:** rebuild from the current source (which already reverted this), or if you must unblock an already-built bad `.ipk` immediately: `opkg install --force-depends <file>.ipk` (only as a last resort — confirm the actually-needed modules are present with `python3 -c "import logging, urllib.request"` afterward).

## 7. `opkg install` fails: `check_conflicts_for: ... conflict with luci-app-horus-controller` even though the conflicting package isn't actually installed
**Symptoms:** `opkg list-installed | grep horus` shows nothing, `opkg remove <package>` says "No packages removed", but install still fails citing a conflict.
**Cause:** a stale status stanza left in `/usr/lib/opkg/status` from an earlier partial/failed/manual install — look for `Status: install prefer,user not-installed` (or similar) under `grep -A4 "^Package: <name>$" /usr/lib/opkg/status`. opkg's conflict check considers this stanza "known", even though nothing is actually on disk.
**Fix:**
```sh
cp /usr/lib/opkg/status /usr/lib/opkg/status.bak   # always back up first
sed -i '/^Package: <name>$/,/^$/d' /usr/lib/opkg/status
```
Replace `<name>` with the exact conflicting package name from the error. Verify with `grep -A4 "^Package: <name>$" /usr/lib/opkg/status` (should print nothing), then retry the install. There can be more than one stale stanza for the same package name (e.g. from several old versions) — the same `sed` command removes all of them in one pass since the range re-triggers on each match.

## 8. Settings page shows raw translation keys (e.g. `header_brand` instead of Arabic text), or looks like a mix of old and new styling
**Symptoms:** literal untranslated strings visible in the UI; a page that looks "half-upgraded" right after installing a new version.
**Cause:** the browser served a stale cached copy of a shared JS module (most often `i18n.js`) that predates the strings/behavior the currently-installed package expects.
**Fix:** every shared module and view file this package ships is renamed to a version-stamped filename on install specifically to prevent this (see `AI_AGENT_RULES.md` rule 4) — if you still see it, first try a hard refresh in a private/incognito browser window to rule out a browser-side cache that predates this protection being added. If it persists even there, check that `/etc/uci-defaults/99_horus-controller-patch` actually ran (`cat /tmp/horus_pkg_version` should match the installed package version) and that `/usr/share/luci/menu.d/luci-app-horus-controller.json` points at versioned filenames, not the bare `map`/`ban`/`settings`.

## 9. Settings page fields are misplaced, overlapping, or huge empty gaps appear between a field's label and its input
**Cause:** the active LuCI theme's own CSS for `.cbi-value`/`.cbi-value-title`/`.cbi-value-field` is winning the cascade over this project's overrides in `horus-theme.css`.
**Fix:** every rule in `horus-theme.css`'s `.horus-settings-view .cbi-*` section must carry `!important` — see `AI_AGENT_RULES.md` rule 5. If you're seeing this after a manual CSS edit, check that `!important` wasn't dropped.

## 10. Plugin pages show errors / empty data right after upgrading, and the browser console shows 403 on `/cgi-bin/horus_*`
**Symptoms:** the map/settings pages load but every panel is empty or shows a
fetch error; DevTools shows `403 Forbidden` with
`{"error":"forbidden","message":"LuCI login required"}`.
**Cause:** the CGI endpoints now require a valid LuCI session (they used to be
open to anyone on the LAN — see `AI_AGENT_RULES.md` rule 9). A 403 means the
browser's `sysauth` session cookie was not accepted. **As of `1.3.5`/`1.2.66`
this should only ever happen right after a genuine logout/expiry, not after
every single package update** — see item 16 below if you're seeing it on
every upgrade across many devices.
**Checks & fixes:**
- Make sure you are actually logged into LuCI in that browser tab, and that the
  session has not expired. Log out and back in.
- Confirm the helper is installed: `ls -l /usr/lib/horus/cgi_auth.sh`. If it is
  missing the endpoints return an empty 500 response instead (fail-closed by
  design) — reinstall the package.
- Verify rpcd answers the ACL query for your session:
  ```sh
  SID="<paste the sysauth cookie value from your browser>"
  ubus call session access "{\"ubus_rpc_session\":\"$SID\",\"scope\":\"uci\",\"object\":\"horus_controller\",\"function\":\"read\"}"
  ```
  It should print `{"access":true}`.
- **Emergency recovery** (restores the previous, unauthenticated behaviour so
  you can regain access to the UI):
  ```sh
  uci set horus_controller.main.cgi_auth='0'; uci commit horus_controller
  ```
  Only the HTTP endpoints are affected — the HMP daemons and adoption keep
  working either way. Re-enable with `uci delete horus_controller.main.cgi_auth`
  once the cause is understood.

## 11. A command (Wi-Fi change, reboot, ban, eject) shows as stuck on "queued" or "sent", or ends up "failed" even though the AP visibly did it
**Symptoms:** an action taken from the controller UI doesn't appear to
complete, or `horus_map_data`'s `cmd_queue` array shows an entry stuck at
`sent` for a long time, or `failed`.
**Cause:** as of the command queue (see `AI_AGENT_RULES.md` rule 10), every
AP-targeted command must be delivered AND acknowledged — a dropped frame in
either direction (command out, or `cmd_ack` back) now shows up honestly
instead of silently looking like success. Common causes:
- The target AP is genuinely offline or unreachable at L2 (check its status
  on the map first).
- The AP is running a pre-`1.3.0` build that doesn't send `cmd_ack` at all
  — every command to it will exhaust `CMD_MAX_ATTEMPTS` and show `failed`
  even though it actually executed (this build has no way to know); upgrade
  the AP.
- A broadcast bridge/switch is dropping the ack frame specifically (rare,
  but possible on a busy segment) — the command itself got through and ran,
  the confirmation didn't. If the visible effect on the AP matches what was
  requested, this is what happened; the failed queue entry can be ignored.
**Fix:** re-issue the action; if a *specific* AP consistently fails to ack
even simple commands (e.g. `reboot`) while clearly being online and running
a current build, check `logread | grep horus` on that AP for exceptions in
its `ap_manage` handler — an unhandled exception there skips the ack (see
the "silence == let the controller's retry/timeout handle it" note in
`AI_AGENT_RULES.md` rule 10) without leaving any other trace.

## 12. Adopted APs / groups disappeared after a factory-reset-and-reflash, or after a power loss during boot
**Symptoms:** the controller previously had adopted APs and groups; after a
reboot (or reflash) they're gone and the map is empty.
**Cause:** `/tmp/horus_db.json` (the live, real-time state) is tmpfs and is
always wiped by a reboot — that's expected and fine, because
`HorusDB.load()` falls back to the flash snapshot at
`/etc/horus/state_snapshot.json`. If APs/groups are still gone after that
fallback, either: the daemon never ran long enough to write a snapshot (it
only writes at most once per 90s, and only after something changed — a
device that was adopted and immediately power-cycled before the next
snapshot tick genuinely has nothing to restore), or `/etc/horus/` doesn't
exist / isn't writable (check `ls -ld /etc/horus` and free space with `df
-h` — OpenWrt's overlay can fill up).
**Fix:** confirm the snapshot file exists and is recent:
`ls -l /etc/horus/state_snapshot.json`. If it's missing entirely and the
daemon has been running for more than a couple of minutes with adopted APs
present, something is preventing the write — check `logread | grep horus`
and free space on the overlay.

## 13. "Activate" button on a new AP is stuck on "⏳ جاري التفعيل..." and never flips to authorized
**Symptoms:** clicked Activate, the button shows the pending spinner label
indefinitely (more than ~15-20s, several retry cycles).
**Cause:** as of `1.3.1`, this label reflects the REAL status of the
`set_api_key` entry in the command queue (`AI_AGENT_RULES.md` rule 10), not
a guess — it means the controller has not received a `cmd_ack` back from
that AP yet.
**Checks:**
- If the button eventually turns into "⚠️ فشل - أعد المحاولة" (~10s later,
  after `CMD_MAX_ATTEMPTS` unacknowledged retries), the AP genuinely never
  got the command, or never applied it, or its ack never arrived — check
  `logread | grep horus` on the AP itself for a receive/HMAC error.
- If it stays on the spinner far longer than that, `dispatch_queue()` may
  not be running (check the controller's `fast_cmd_loop` — see
  `AI_AGENT_RULES.md` rule 10) or the AP simply isn't reachable at L2 yet
  (confirm it shows up in the pending list at all, meaning its `hello` is
  getting through).
- A pre-`1.3.0` AP build doesn't send `cmd_ack` at all — it will always show
  "failed" even on a successful adoption. Check the AP's package version.

## 14. A known AP is missing from the dashboard, but shows up greyed out under "أجهزة مملوكة لكنترولر آخر"
**Cause:** this is not a bug — as of `1.3.1`, an AP that announces itself as
already adopted by a *different* controller's MAC is shown in this
read-only panel instead of just disappearing, so you can tell it's not lost,
just owned elsewhere. It has no action buttons on purpose: this controller
has no valid secret for it and cannot manage it.
**Fix:** if this AP should belong to THIS controller, eject it from
whichever controller currently owns it (or clear its `hmp_secret` directly
on the AP over SSH — see the Client project's docs) before it will become
adoptable here.

## 15. Topology tab ("الطوبولوجيا") shows an AP as disconnected, or a link is missing / shown dashed instead of solid
**Symptoms:** an AP that's clearly online shows up under the dashed
"unreachable from the root" divider, or a real cable/backhaul link between
two APs is missing entirely, or shown dashed (unconfirmed) when you'd
expect solid.
**Cause:** there is no dedicated discovery protocol for this (see
`AI_AGENT_RULES.md` rule 16) — every link is derived from ordinary
hello/telemetry data, recomputed roughly every 5 seconds. A link needs BOTH
ends to report matching evidence to show as confirmed (solid); if only one
side's telemetry has arrived recently, it's still shown, just dashed. An AP
with genuinely no detectable path back to the controller (e.g. connected
through hardware this project doesn't fingerprint, or a very fresh
adoption before its first telemetry cycle) lands under the "unreachable"
divider — it's still fully managed, just not placeable in the tree yet.
**Checks:**
- Wired links need `brctl showmacs br-lan` to actually show the other AP's
  MAC on some port — an intermediate *unmanaged* switch between two Horus
  APs can still make this work (bridge learning sees through it), but a
  router or anything that NATs/isolates traffic between them will not.
- Wireless backhaul links need the repeater AP to actually be reporting a
  `sta`-mode radio in its wifi config, AND the AP it's meshing to needs to
  see that radio's MAC in its own associated-clients list. Give it one full
  telemetry cycle (`TELEMETRY_INTERVAL`) after a config change before
  concluding the link is genuinely missing.
- Wait ~5-10s after any topology change (adoption, reboot, cable move) —
  `compute_topology()` doesn't run on every single poll tick.

## 16. Every single package update logs you out of LuCI on every device / dashboard shows 0 APs right after upgrading
**Symptoms:** immediately after installing a new package version — on the
controller, on a client, or both — the dashboard shows no APs / all-zero
counts, and/or a client's own status shows "LuCI login required," even
though nothing about the network actually changed.
**Cause:** before `1.3.5`/`1.2.66`, `postinst` unconditionally reloaded
rpcd (and restarted uhttpd) on every install, which resets rpcd's session
table and invalidates every admin's active LuCI login on that device. This
was a real, confirmed incident — diagnosed live against real hardware, the
daemon and HMP protocol were never actually broken, only the browser's
session was invalidated by the *previous* install finishing.
**Fix:** upgrade to `1.3.5`/`1.2.66` or later on every device. `postinst`
now only reloads rpcd when the ACL definition itself actually changed
(hash-compared against the previous install), so a routine update no
longer touches session state at all. **You should still expect exactly one
final logout on the update that brings a device TO `1.3.5`/`1.2.66`** (no
prior hash to compare against yet) — after that, updates on that device
stop resetting sessions unless a future update genuinely changes the ACL.
**If you're still on an older version and need it working right now**:
`uci set horus_controller.main.cgi_auth='0'; uci commit horus_controller`
on the affected device(s) — see item 10's emergency recovery. Remember to
re-enable it (`uci delete horus_controller.main.cgi_auth`) after upgrading.
