# Horus OpenWrt - Controller Architecture & Reference

## Overview
The Horus OpenWrt Controller is responsible for discovering, managing, and adopting Horus Satellite/Client APs across the network. 

## 1. Network Communication (The Golden Rule)
**ALL communication between the Controller and the Client APs MUST occur over Layer 2 (MAC-based) by default.**

### 1.1 Layer 2 HMP (Horus Management Protocol)
- **Protocol**: Raw Ethernet Socket (AF_PACKET)
- **EtherType**: `0x88B5`
- **Interface**: `br-lan`
- **Rule**: The Controller and Client MUST use `dst_mac` for all discovery, adoption, heartbeats, and commands.

### 1.2 Layer 3 Fallback (Strict Red Line)
- **Layer 3 (UDP Port 8885)** is **STRICTLY PROHIBITED** for auto-discovery.
- Layer 3 can **ONLY** be used if the user explicitly inputs an IP address into the `Controller IP` field in the Client's UI settings.
- If the `Controller IP` field is empty, the Client and Controller must remain completely isolated to Layer 2, regardless of whether they have IP addresses in different subnets.

## 2. Technical Quirks & Past Bugs
### 2.1 Python `AF_PACKET` Bind on OpenWrt
When creating the raw socket in Python on OpenWrt, **NEVER** use an empty string `""` for the interface name. The actual code (`protocol.py`'s `create_sockets()`) uses `socket.htons()` only for the socket's own `proto` argument, not for the `bind()` call itself:
```python
# WRONG - Will fail silently with [Errno 19] No such device
raw_sock.bind(("", ETH_P_HMP))

# CORRECT (this is the real code)
proto = socket.htons(ETH_P_HMP)
raw_sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, proto)
raw_sock.bind((INTERFACE, ETH_P_HMP))
```
`INTERFACE` is auto-detected in `config.py` (tries `br-lan`, `br0`,
`br-lan.1`, then the first bridge device under `/sys/class/net`) — don't
assume it's a literal hardcoded `"br-lan"` string when reading the code.

### 2.2 Daemons and Services
- The Controller daemon's entry point is `/usr/bin/horus-hmp.py` (started by
  `/etc/init.d/horus_controller`) — there is no `horus-controller.py`.
- Ensure that the Client daemon and Controller daemon (same entry point
  filename, different `role` in UCI) do not both run on the same device —
  see `AI_AGENT_RULES.md` rule 1 for why the two packages declare
  `Conflicts:` against each other.

## 3. Discovery & Adoption Flow
1. **Discovery**: Client AP broadcasts `{ "type": "hello", "src_mac": ..., "hostname": ..., "ip": ..., "wifi": ..., "ports": ..., "stats": ... }` to `FF:FF:FF:FF:FF:FF` via `0x88B5`.
2. **Adoption**: Controller receives `hello`, registers the MAC as `unauthorized`, and awaits the user's "Adopt" click.
3. **Provisioning**: Once adopted, Controller sends `{ "type": "ap_manage", "action": "set_api_key", "key": "..." }` directly to the Client's MAC address over Layer 2 (the field is `key`, not `api_key`, despite the action name).
4. **Heartbeat**: Client sends `hello`/`telemetry` every 10/5 seconds respectively to the Controller's MAC address (broadcast, not unicast — the Controller filters by matching `src_mac`). Controller updates the database and mirrors it to `/tmp/horus_network_state.json`. The Controller also ACKs every `hello`/`telemetry` it accepts with a `root_heartbeat` sent directly to the sender's MAC, which is what the Client uses to know it's actually connected.

See `API_AND_PROTOCOLS.md` in this same `docs/` directory for the complete, code-accurate list of message types and fields.

## 4. UI Indicators
- **L2 HMP Direct Mesh**: Displayed in the Controller UI when a node is connected strictly via Layer 2 MAC bridging.
- **L3 UDP Routing**: Displayed ONLY when the Client is actively using a manually configured Controller IP.
