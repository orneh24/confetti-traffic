#!/bin/sh
# confettictl-trust-hub.sh -- install the SSH keys this node gets from the hub.
# Installed as /usr/local/bin/confettictl-trust-hub.
#
#   confettictl-trust-hub          fetch the hub's management key, show it, ask,
#                              pin it (the deliberate re-pin)
#   confettictl-trust-hub -y       same, without asking
#   confettictl-trust-hub.sh --auto        what confettictl-setup.sh and confettictl-register.sh run: install the
#                              mesh key; pin the management key only when
#                              nothing is pinned yet or HUB_URL changed;
#                              unpin when HUB_MANAGED=false
#
# Two keys, trusted very differently:
#
# Mesh key -- the SSH test's keypair (constraint 3). Every node must hold the
# same one, and nodes installed from the hub were never cloned from a common
# template, so the hub is where it lives. It is served over plain HTTP, which
# is only safe because of how it is trusted: forced to run `echo ok` (exactly
# what confettictl-test-cycle.sh's SSH test runs) with no pty and no forwarding. Holding
# it proves nothing beyond "SSH to this node works". Re-fetched on every
# --auto run -- harmless, and it follows a rebuilt hub.
#
# Management key -- gives the hub root, and is fetched over the same plain
# HTTP, so anything answering as the hub during the fetch could plant its
# own. Trust on first use limits that to the moment of pinning: after that
# the pin is never replaced automatically (confettictl-register.sh only warns on a
# mismatch). --auto re-pins when HUB_URL changes, because re-homing a node
# is itself an admin action (guestinfo in vCenter, or the config by hand).

set -eu

CONFIG="/etc/confetti/config"
PIN="/etc/confetti/hub_key.pub"
PIN_URL="/etc/confetti/hub_key.url"
MESH_KEY="/etc/confetti/id_confetti"
AUTH="/root/.ssh/authorized_keys"

log() { printf '[trust-hub] %s\n' "$1"; }

[ -f "$CONFIG" ] || { log "no $CONFIG -- run confettictl-setup.sh first"; exit 1; }
# shellcheck source=/dev/null
. "$CONFIG"

MODE="ask"
case "${1:-}" in
    --auto) MODE="auto" ;;
    -y|--yes) MODE="yes" ;;
    "") ;;
    *) echo "Usage: confettictl-trust-hub [-y]" >&2; exit 2 ;;
esac

# Print "type base64" of the first line of stdin if it is an ed25519 public
# key, nothing otherwise. The hub's comment is dropped: each line is
# re-tagged with our own so it can always be found again.
valid_pub() {
    awk 'NR==1 && $1 == "ssh-ed25519" && $2 ~ /^[A-Za-z0-9+\/=]+$/ {print $1, $2}'
}

fetch() {
    curl -s -f --connect-timeout 5 --max-time 10 "${HUB_URL}$1" 2>/dev/null
}

# Rewrite authorized_keys without lines tagged $1 (plus any extra pattern
# $3), then add line $2 if given.
set_auth_line() {
    mkdir -p /root/.ssh
    chmod 700 /root/.ssh
    touch "$AUTH"
    grep -v -e " ${1}\$" -e "${3:- ${1}\$}" "$AUTH" > "${AUTH}.new" || true
    [ -n "$2" ] && printf '%s %s\n' "$2" "$1" >> "${AUTH}.new"
    chmod 600 "${AUTH}.new"
    mv -f "${AUTH}.new" "$AUTH"
}

# -------------------------------------------------------------------
# Mesh key (--auto only)
# -------------------------------------------------------------------
if [ "$MODE" = "auto" ]; then
    _pub=$(fetch /node/mesh-key.pub | valid_pub) || _pub=""
    if [ -n "$_pub" ] && fetch /node/mesh-key > "${MESH_KEY}.new" \
            && grep -q 'PRIVATE KEY' "${MESH_KEY}.new"; then
        chmod 600 "${MESH_KEY}.new"
        mv -f "${MESH_KEY}.new" "$MESH_KEY"
        printf '%s confetti-mesh\n' "$_pub" > "${MESH_KEY}.pub"
        # ' confetti$' also drops the unrestricted template-era key.
        set_auth_line confetti-mesh \
            "command=\"echo ok\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ${_pub}" \
            ' confetti$'
    else
        rm -f "${MESH_KEY}.new"
        log "WARNING: no mesh key from ${HUB_URL}; SSH tests fail until it is fetched"
    fi
fi

# -------------------------------------------------------------------
# Management key
# -------------------------------------------------------------------
if [ "${HUB_MANAGED:-true}" != "true" ]; then
    if [ -f "$PIN" ]; then
        set_auth_line confetti-hub ""
        rm -f "$PIN" "$PIN_URL"
        log "HUB_MANAGED=${HUB_MANAGED}: hub key removed"
    fi
    exit 0
fi

if [ "$MODE" = "auto" ] && [ -f "$PIN" ] && [ "$(cat "$PIN_URL" 2>/dev/null)" = "$HUB_URL" ]; then
    # Already pinned for this hub: make sure the line is still there, from
    # the pinned copy -- never from a fresh fetch.
    set_auth_line confetti-hub "$(valid_pub < "$PIN")"
    exit 0
fi

_key=$(fetch /node/hub-key.pub | valid_pub) || _key=""
if [ -z "$_key" ]; then
    log "WARNING: no valid key from ${HUB_URL}/node/hub-key.pub -- hub cannot manage this node yet"
    [ "$MODE" = "auto" ] && exit 0
    exit 1
fi

printf '%s confetti-hub\n' "$_key" > "${PIN}.new"
_fp=$(ssh-keygen -lf "${PIN}.new" 2>/dev/null | awk '{print $2}') || _fp="?"

if [ "$MODE" = "ask" ]; then
    printf 'Hub %s key fingerprint: %s\nTrust it (gives the hub root on this node)? [y/N] ' "$HUB_URL" "$_fp"
    read -r _ans || _ans=""
    case "$_ans" in
        y|Y|yes) ;;
        *) rm -f "${PIN}.new"; log "not pinned"; exit 1 ;;
    esac
fi

mv -f "${PIN}.new" "$PIN"
printf '%s\n' "$HUB_URL" > "$PIN_URL"
set_auth_line confetti-hub "$_key"
log "pinned hub key ${_fp} for ${HUB_URL}"
