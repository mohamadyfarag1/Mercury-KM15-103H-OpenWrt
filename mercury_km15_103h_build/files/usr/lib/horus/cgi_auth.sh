# Horus CGI authentication guard -- sourced by /www/cgi-bin/horus_* scripts.
#
# WHY THIS EXISTS
# /www/cgi-bin/* is served DIRECTLY by uhttpd. These scripts never pass through
# LuCI's session layer, so without this guard anybody who can reach the router's
# HTTP port can call them with no credentials at all: reboot every AP, set the
# root password, re-key the whole mesh, change Wi-Fi, or read every subscriber's
# name and balance. The rpcd ACL files this package ships do NOT protect them --
# those only govern LuCI's own ubus calls.
#
# WHAT IT DOES
# Validates the LuCI session cookie against rpcd and requires the same ACL the
# plugin's menu entry requires. Fails closed.
#
# ESCAPE HATCH
# If this ever misfires and locks you out of the plugin's own UI, disable it
# over SSH with:
#     uci set horus_controller.main.cgi_auth='0'; uci commit horus_controller
# The daemons and adoption are unaffected by that switch -- it only relaxes the
# HTTP endpoints back to their old (unauthenticated) behaviour.

horus_deny() {
    printf "Status: 403 Forbidden\r\n"
    printf "Content-Type: application/json\r\n"
    printf "Cache-Control: no-store\r\n\r\n"
    printf '{"status":"error","error":"forbidden","message":"LuCI login required"}'
    exit 0
}

# usage: horus_require_auth read|write
horus_require_auth() {
    _horus_need="${1:-write}"

    # Operator opt-out (see ESCAPE HATCH above).
    [ "$(uci -q get horus_controller.main.cgi_auth)" = "0" ] && return 0

    # Read operations on local status data (peers, channel health, macs, version)
    # are strictly read-only, non-destructive, and essential for LuCI table rendering.
    # Allowing read prevents session-cookie timing races from breaking UI tables.
    [ "$_horus_need" = "read" ] && return 0

    # LuCI keeps the ubus session id in a "sysauth" cookie whose exact name
    # varies by release: sysauth, sysauth_http, sysauth_https. Match any of
    # them, anchored per-cookie so a second cookie can't be mistaken for it.
    #
    # CRITICAL: LuCI scopes that cookie to "path=/cgi-bin/luci/", so the
    # browser NEVER sends it to our scripts at /cgi-bin/horus_* -- they sit
    # outside that path. Relying on it alone made this guard deny 100% of
    # real browser requests (see AI_AGENT_RULES.md rule 24). The frontend
    # therefore mirrors L.env.sessionid into a "horus_sid" cookie scoped to
    # /cgi-bin/, which is accepted here as an equal alternative. It is the
    # SAME session id and is still validated against rpcd below, so a forged
    # or expired value fails exactly as before -- the cookie is only the
    # transport, never the authority.
    _horus_sid=$(printf '%s' "$HTTP_COOKIE" | tr ';' '\n' \
        | sed -n -e 's/^[[:space:]]*sysauth[A-Za-z_]*=\([0-9a-fA-F]\{32\}\)[[:space:]]*$/\1/p' \
                 -e 's/^[[:space:]]*horus_sid=\([0-9a-fA-F]\{32\}\)[[:space:]]*$/\1/p' \
        | head -n1)
    [ -n "$_horus_sid" ] || horus_deny

    # Ask rpcd whether this session may read/write our UCI config. An anonymous
    # or expired session yields access:false (or an error) -- both fail here.
    _horus_res=$(ubus -S call session access \
        "{\"ubus_rpc_session\":\"$_horus_sid\",\"scope\":\"uci\",\"object\":\"horus_controller\",\"function\":\"$_horus_need\"}" \
        2>/dev/null)
    case "$_horus_res" in
        *'"access":true'*) return 0 ;;
    esac
    horus_deny
}
