#!/bin/sh
# confettictl-register.sh — Register this node with the confetti hub.
# Runs on boot and every 5 minutes via cron.
# Reads config from /etc/confetti/config.

set -u

CONFIG="/etc/confetti/config"
LOG_TAG="confetti-register"
MAX_RETRIES=3
RETRY_DELAY=5

# -------------------------------------------------------------------
# Logging helper — prepends ISO-8601 timestamp
# -------------------------------------------------------------------
log() {
    printf '%s [%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$LOG_TAG" "$1"
}

# -------------------------------------------------------------------
# Load configuration
# -------------------------------------------------------------------
if [ ! -f "$CONFIG" ]; then
    log "ERROR: config file $CONFIG not found"
    exit 1
fi

# shellcheck source=/dev/null
. "$CONFIG"

# Validate required variables
for var in HUB_URL GROUP_NAME SUBNET; do
    eval val=\$$var
    if [ -z "$val" ]; then
        log "ERROR: $var is not set in $CONFIG"
        exit 1
    fi
done

# -------------------------------------------------------------------
# Detect hostname and IP
# -------------------------------------------------------------------
HOSTNAME=$(hostname)

# Get the IP address of the first non-loopback interface
IP=$(ip -4 -o addr show scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')

if [ -z "$IP" ]; then
    log "ERROR: could not detect IP address"
    exit 1
fi

log "Detected hostname=$HOSTNAME ip=$IP group=$GROUP_NAME subnet=$SUBNET"

# -------------------------------------------------------------------
# Build JSON payload
# -------------------------------------------------------------------
# build: the commit this node's code came from (confettictl-update.sh / confettictl-node-install.sh
# write /etc/confetti-release). managed: whether the hub may SSH in to push
# updates (HUB_MANAGED, default true). Both are shown on the dashboard.
BUILD=$(sed -n 's/^commit=//p' /etc/confetti-release 2>/dev/null | head -n 1 | tr -cd '0-9a-z')
BUILD="${BUILD:-unknown}"
if [ "${HUB_MANAGED:-true}" = "true" ]; then MANAGED=true; else MANAGED=false; fi

# clock_synced / clock_offset_s: this node's chrony state, shown on the
# dashboard. null when chronyc is missing or says nothing usable — this must
# never stop registration (constraint 11). The offset goes through awk's
# %.6f so it is always a valid JSON number (constraint 9).
CLOCK_SYNCED=null
CLOCK_OFFSET=null
_tracking=$(chronyc -n tracking 2>/dev/null) || _tracking=""
if [ -n "$_tracking" ]; then
    case "$(printf '%s\n' "$_tracking" | sed -n 's/^Leap status *: *//p')" in
        Normal) CLOCK_SYNCED=true ;;
        ?*) CLOCK_SYNCED=false ;;
    esac
    CLOCK_OFFSET=$(printf '%s\n' "$_tracking" | awk -F: '/^System time/ {
        split($2, w, " "); if (w[1] ~ /^[0-9.]+$/) printf "%.6f", ($0 ~ /slow/ ? -w[1] : w[1]) }')
    CLOCK_OFFSET="${CLOCK_OFFSET:-null}"
fi

PAYLOAD=$(printf '{"hostname":"%s","ip":"%s","subnet":"%s","group_name":"%s","build":"%s","managed":%s,"clock_synced":%s,"clock_offset_s":%s}' \
    "$HOSTNAME" "$IP" "$SUBNET" "$GROUP_NAME" "$BUILD" "$MANAGED" "$CLOCK_SYNCED" "$CLOCK_OFFSET")

# -------------------------------------------------------------------
# POST to hub with retry logic
# -------------------------------------------------------------------
attempt=1
REGISTERED="no"
while [ "$attempt" -le "$MAX_RETRIES" ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
        --connect-timeout 5 \
        --max-time 10 \
        -X POST \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "${HUB_URL}/register" 2>/dev/null) || HTTP_CODE="000"

    if [ "$HTTP_CODE" -ge 200 ] 2>/dev/null && [ "$HTTP_CODE" -lt 300 ] 2>/dev/null; then
        log "Registration successful (HTTP $HTTP_CODE)"
        REGISTERED="yes"
        break
    fi

    log "Attempt $attempt/$MAX_RETRIES failed (HTTP $HTTP_CODE)"
    attempt=$((attempt + 1))

    if [ "$attempt" -le "$MAX_RETRIES" ]; then
        sleep "$RETRY_DELAY"
    fi
done

if [ "$REGISTERED" != "yes" ]; then
    log "ERROR: registration failed after $MAX_RETRIES attempts"
    exit 1
fi

# -------------------------------------------------------------------
# Refresh the identity page.
#
# It is generated once at setup time with the address of the moment. Under
# DHCP that goes stale after a lease change, leaving the page advertising an
# address the node no longer has. Regenerating here keeps it honest.
# -------------------------------------------------------------------
WEB_ROOT="/var/www/localhost/htdocs"
if [ -d "$WEB_ROOT" ]; then
    cat > "${WEB_ROOT}/index.html" <<EOF
<!DOCTYPE html>
<html>
<head>
  <title>${HOSTNAME} - confetti</title>
  <style>
    body { font-family: monospace; margin: 2em; background: #1a1a2e; color: #e0e0e0; }
    h1 { color: #00d4ff; }
    table { border-collapse: collapse; margin-top: 1em; }
    td { padding: 0.3em 1em; }
    td:first-child { color: #888; }
  </style>
</head>
<body>
  <h1>${HOSTNAME}</h1>
  <p>confetti endpoint</p>
  <table>
    <tr><td>Hostname</td><td>${HOSTNAME}</td></tr>
    <tr><td>IP Address</td><td>${IP}</td></tr>
    <tr><td>Group</td><td>${GROUP_NAME}</td></tr>
    <tr><td>Subnet</td><td>${SUBNET}</td></tr>
    <tr><td>Updated</td><td>$(date -u '+%Y-%m-%dT%H:%M:%SZ')</td></tr>
  </table>
</body>
</html>
EOF
fi

# -------------------------------------------------------------------
# Hub key check. Report only: the pinned management key is never replaced
# from here. A different key at the hub means the hub was rebuilt -- or
# something else is answering as the hub. Re-pin deliberately with
# confettictl-trust-hub once you know which.
# -------------------------------------------------------------------
# Keys still missing (the hub was down when confettictl-setup.sh ran): retry now.
if [ ! -f /etc/confetti/id_confetti ] || \
   { [ "${HUB_MANAGED:-true}" = "true" ] && [ ! -f /etc/confetti/hub_key.pub ]; }; then
    /usr/local/bin/confetti/confettictl-trust-hub.sh --auto 2>&1 | while IFS= read -r _l; do log "$_l"; done
fi

if [ "${HUB_MANAGED:-true}" = "true" ] && [ -f /etc/confetti/hub_key.pub ]; then
    _served=$(curl -s -f --connect-timeout 5 --max-time 10 "${HUB_URL}/node/hub-key.pub" 2>/dev/null \
        | awk 'NR==1 {print $1, $2}') || _served=""
    _pinned=$(awk 'NR==1 {print $1, $2}' /etc/confetti/hub_key.pub)
    if [ -n "$_served" ] && [ "$_served" != "$_pinned" ]; then
        log "WARNING: hub serves a different management key than the pinned one; not replacing it (run confettictl-trust-hub to re-pin)"
    fi
fi

# -------------------------------------------------------------------
# Agent self-update.
#
# The hub is the single place agent scripts are edited; every node converges
# here on its 5-minute run. A bad push would otherwise break the whole mesh
# at once, so an update is only accepted when it clears three gates:
#
#   1. the downloaded body matches the sha256 the hub published
#   2. it parses as a shell script (sh -n)
#   3. for confettictl-test-cycle.sh, a real run of the new script succeeds
#
# The previous version is kept as .known-good and restored if gate 3 fails,
# so a node can never be left running a script that does not work.
#
# Set AGENT_AUTOUPDATE=false in the config to opt a node out entirely.
# -------------------------------------------------------------------
AGENT_AUTOUPDATE="${AGENT_AUTOUPDATE:-true}"

if [ "$AGENT_AUTOUPDATE" != "true" ]; then
    log "Self-update disabled (AGENT_AUTOUPDATE=$AGENT_AUTOUPDATE)"
    exit 0
fi

command -v sha256sum >/dev/null 2>&1 || {
    log "sha256sum unavailable, skipping self-update"
    exit 0
}

SCRIPT_DIR="/usr/local/bin/confetti"
MANIFEST=$(curl -s --connect-timeout 5 --max-time 10 "${HUB_URL}/agent/manifest" 2>/dev/null) || MANIFEST=""

if [ -z "$MANIFEST" ] || ! printf '%s' "$MANIFEST" | jq empty 2>/dev/null; then
    log "No agent manifest available, skipping self-update"
    exit 0
fi

update_script() {
    _name="$1"
    _want=$(printf '%s' "$MANIFEST" | jq -r ".scripts[\"${_name}\"].sha256 // empty")
    [ -z "$_want" ] && return 0

    _local="${SCRIPT_DIR}/${_name}"
    if [ -f "$_local" ]; then
        _have=$(sha256sum "$_local" | awk '{print $1}')
        [ "$_have" = "$_want" ] && return 0
    fi

    log "Update available for ${_name}"
    _tmp="/tmp/confetti-${_name}.$$"

    if ! curl -s -f --connect-timeout 5 --max-time 20 \
            -o "$_tmp" "${HUB_URL}/agent/${_name}" 2>/dev/null; then
        log "  download failed, keeping current version"
        rm -f "$_tmp"
        return 0
    fi

    # Gate 1: checksum
    _got=$(sha256sum "$_tmp" | awk '{print $1}')
    if [ "$_got" != "$_want" ]; then
        log "  checksum mismatch (want $(printf '%s' "$_want" | cut -c1-12)..., got $(printf '%s' "$_got" | cut -c1-12)...), rejecting"
        rm -f "$_tmp"
        return 0
    fi

    # Gate 2: it has to parse
    if ! sh -n "$_tmp" 2>/dev/null; then
        log "  ERROR: downloaded ${_name} is not valid shell, rejecting"
        rm -f "$_tmp"
        return 0
    fi

    # Swap in, keeping the current version recoverable.
    [ -f "$_local" ] && cp -f "$_local" "${_local}.known-good"
    mv -f "$_tmp" "$_local"
    chmod +x "$_local"
    log "  installed new ${_name}"

    # Gate 3: prove the new test-cycle actually runs before trusting it.
    #
    # Caveat: if a cycle is already in flight the new script will take the
    # lock path and exit 0 without doing much, so this gate can pass without
    # having exercised the change. It still catches an outright broken
    # script, and gate 2 plus the rollback below cover the rest.
    if [ "$_name" = "confettictl-test-cycle.sh" ]; then
        if "$_local" >/dev/null 2>&1; then
            log "  verification run passed"
        else
            if [ -f "${_local}.known-good" ]; then
                log "  ERROR: verification run failed, rolling back to known-good"
                mv -f "${_local}.known-good" "$_local"
                chmod +x "$_local"
            else
                log "  ERROR: verification run failed and no known-good copy exists"
            fi
        fi
    fi
}

# Only confettictl-test-cycle.sh auto-updates.
#
# confettictl-register.sh is the updater itself, so a version of it that passes `sh -n`
# but fails at runtime would stop the node registering *and* disable the
# mechanism that would otherwise repair it — every node would need fixing by
# hand, which is the exact opposite of what self-update is for. There is also
# no equivalent of the gate-3 verification run for it: running confettictl-register.sh to
# test confettictl-register.sh is circular.
#
# confettictl-test-cycle.sh is what actually gets iterated on, and it is safely
# verifiable. To roll out a confettictl-register.sh change, push it deliberately: the
# dashboard's update button (or confettictl-update on the node) runs confettictl-update.sh,
# which re-runs confettictl-setup.sh and so tries the new confettictl-register.sh on the spot.
update_script "confettictl-test-cycle.sh"

exit 0

