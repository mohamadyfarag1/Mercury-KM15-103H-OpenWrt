# API and Protocols (HMP)

HMP (Horus Management Protocol) is a custom protocol for the Horus
ecosystem. This document describes the **actual wire format implemented in
`protocol.py`, `root.py`, and `satellite.py`** — if you're about to write
code that produces or consumes an HMP message, check the field names here
first; earlier revisions of this doc described a different, aspirational
format (e.g. `mac`/`version`/`uptime`/`api_key` fields, a `delete_node`
message type) that was never actually implemented. When in doubt, the code
is the source of truth — this doc is kept in sync with it, but re-check
`protocol.py` for anything security- or wire-format-critical.

## Transport

- **Layer 2 (primary, default):** raw Ethernet via `AF_PACKET`,
  EtherType `0x88B5`, interface `br-lan` (or auto-detected bridge on the
  client). Frame layout: destination MAC (6 bytes, `FF:FF:FF:FF:FF:FF` for
  broadcast or a specific unicast target) + source MAC (6 bytes) +
  EtherType (2 bytes) + payload.
- **Layer 3 (opt-in only):** UDP port `8885`, used only when the user has
  explicitly typed a `Controller IP` in the client's settings. See the
  "Golden Rule" in `architecture.md` — this must never be automatic.
- **Payload encoding:** the JSON payload is **`zlib`-compressed**, nothing
  more. `parse_incoming_data()` tries `zlib.decompress()` first and falls
  back to plain JSON if that fails (for forward/backward tolerance), but
  every sender in this codebase always compresses.
- **There is no encryption.** No `crypto.py` module exists in either
  project despite what older documentation said. Messages are readable by
  anyone who can capture L2 traffic on the segment; only integrity/origin
  is protected, and only when a secret is configured (see below).

## Authentication (HMAC, not encryption)

`send_hmp_frame(..., secret=...)` adds a `ts` (unix timestamp) field, then
— if `secret` is non-empty — computes
`hmac.new(secret, json.dumps(payload, sort_keys=True, separators=(',',':')),
sha256).hexdigest()` over the payload (with any existing `hmac` field
removed first) and attaches it as the `hmac` field.

`verify_hmac()` on the receiving side recomputes the same HMAC and compares
with `hmac.compare_digest()`. If the receiver's own `secret` is empty,
`verify_hmac()` returns `True` unconditionally (auth is a no-op until a
secret is configured — this is intentional, it's what allows the initial
unauthenticated adoption handshake).

**Rescue backdoor:** if normal HMAC verification fails, `parse_incoming_data()`
also tries `secret = "<MAC>_horus_rescue"` for a small set of candidate MAC
addresses drawn from the message itself (`target_mac`/`target_ap`, `src_mac`,
and the local device's own MAC). If that verifies, the message is accepted
as authenticated **only** for `type: "ap_manage", action: "set_api_key"` or
heartbeat message types — this exists so a controller can re-adopt an AP
that still holds a stale secret from a previous controller. Note this key
is derivable from a publicly-broadcast MAC address; this is a known,
accepted limitation, not a hidden one — see `AI_AGENT_RULES.md` and the
"what's documented but intentionally not fixed" section of `CHANGELOG.md`.

**There is no replay protection.** `ts` is attached but never checked
against a freshness window, and there's no sequence number. A captured,
validly-signed frame can be replayed later and will still be accepted.

## Message types actually implemented

Every message includes `type`, `src_mac`, and (once signed) `ts` + `hmac`.

| `type` | Direction | Key fields | Handled in |
|---|---|---|---|
| `hello` | Client → Root | `hostname`, `ip`, `netmask`, `gateway`, `wifi`, `ports`, `stats` | `root.py` (registers/updates the AP in the DB) |
| `telemetry` | Client → Root | same as `hello` plus `clients`, `scan_data` | `root.py` |
| `root_heartbeat` / `root_announce` | Root → Client (and Root → Root as an ACK) | `root_ip`, `root_hostname` | `satellite.py` (writes `/tmp/horus_controller_info.json`); `root.py` sends this as an ACK any time it receives `hello`/`telemetry` |
| `peer_announce` | any AP → broadcast | `hostname`, `ip`, `radios_5g`, `radios_2g`, `macs`, `health_5g` | both `root.py` and `satellite.py` (P2P neighbor discovery, unauthenticated by design — writes `/tmp/horus_ap_peers.json`) |
| `ban` / `unban` | Root → Client | `target_mac`, `duration` | `satellite.py` calls `ban_mac_locally()`/`unban_mac_locally()` |
| `wifi_config` | Root → Client | `target_mac`, `action`, `iface`, `value`, plus action-specific kwargs | `satellite.py` calls `apply_wifi_config()` |
| `ap_manage` | Root → Client | `target_mac`, `action` (see below), action-specific fields | `satellite.py`'s large `ap_manage` branch |
| `cmd_ack` | Client → Root | `target_mac` (the controller), `cmd_id`, `ok`, `error` | `root.py`'s `listen_loop()` calls `db.mark_cmd_result()` |

Any `ban`/`unban`/`wifi_config`/`ap_manage` frame the controller sends via
the command queue (see `AI_AGENT_RULES.md` rule 10 — this is every
single-AP-targeted command; `'ALL'`/broadcast commands don't use the queue
and carry no `cmd_id`) also carries a `cmd_id`. `satellite.py` echoes it
back in a `cmd_ack` after dispatching the command, from one shared insertion
point right after the ban/wifi_config/ap_manage handling in `listen_loop()`
— it does **not** send one per individual action, so don't expect a
per-sub-action ack granularity. The ack's HMAC is signed with whatever
`self.secret` held *before* dispatch (captured up front) specifically so
that an `unadopt` command's own ack — sent after `self.secret` has already
been cleared by that same command — is still verifiable by the controller,
which still holds the same (shared) secret this AP just gave up.

### `ap_manage` actions

`network`/`set_ip`, `reboot`, `install_package` (`package`, either an opkg
name or an `http(s)://...ipk` URL), `kick` (`mac`), `tx_power`
(`txpower`/`value`), `set_hostname` (`hostname`), `wifi_radio`/
`radio_toggle` (`radio`, `state`), `radio_restart` (`radio`),
`admin_password` (`password`), `set_api_key` (`key`, optionally
`controller_ip`/`root_ip` — **this is the adoption message**, see below),
`steer_client` (`mac`, `target_bssid`, `ban_time`), `enable_80211kv`,
`port_state`/`port_toggle` (`port`, `state`).

All values coming from the network are sanitized before being interpolated
into a shell command (`_sanitize_ip`, `_sanitize_mac`, `_sanitize_hostname`,
`_sanitize_port`, `_sanitize_int`, or the generic `_sanitize_value` with a
restrictive regex) — see the security fixes in `CHANGELOG.md` for the two
places this was missing and got fixed (`admin_password`,
`horus_rrm_apply`).

## Adoption flow (as actually implemented)

1. Client broadcasts `hello` on L2, unsigned (it has no secret yet).
2. Controller's `RootNode.listen_loop()` accepts `hello`/`telemetry`
   regardless of auth status, and registers the AP with `unauthorized=True`
   if it didn't verify. This is the correct, intended state for a
   not-yet-adopted AP — it is **not** a bug on its own.
3. User clicks "Activate" in the Controller UI → `POST
   /cgi-bin/horus_ap_action` with `{target_ap, action: "set_api_key", key:
   <controller's hmp_secret>}` → written to `/tmp/horus_ap_cmd.json` →
   picked up by `RootNode.process_fast_commands()`, which sends `type:
   "ap_manage", action: "set_api_key", key: <secret>` to the target,
   signed both with the controller's current secret and with the rescue
   secret (see above) for reliability.
4. Client's `satellite.py` accepts `set_api_key` even while it has no
   secret configured (see the "if not self.secret" exception in
   `listen_loop()`), sets `hmp_secret` via `uci`, and immediately re-sends
   `hello`/`telemetry` so the controller sees it as authenticated right
   away.
5. From then on, all further traffic between this pair must be
   HMAC-signed with the shared secret.
