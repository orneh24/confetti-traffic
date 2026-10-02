#!/bin/sh
# confettictl-update.sh — pull the latest confetti code onto an already-installed hub
# or node. Both build scripts install it as /usr/local/bin/confettictl-update.
#
# Usage:
#   confettictl-update         download the latest code, confirm, apply
#   confettictl-update -y      same, without the confirmation
#   sh <repo>/confettictl-update.sh      apply from an unpacked repo instead of
#                            downloading (no GitHub access: scp the repo over)
#
# Where it downloads from:
#   hub   the GitHub main tarball
#   node  its own hub's node bundle (${HUB_URL}/node/bundle.tar.gz) -- never
#         GitHub. The hub rebuilds that bundle from its own code on every hub
#         update, so a node can't get ahead of its hub. The hub's dashboard
#         push-update runs this over SSH.
# CONFETTI_UPDATE_URL overrides both.
#
# The apply is `<role>/confettictl-build-template.sh --update`: the same install steps as
# the build, so there is no second file list here to drift. It keeps the
# node's config, hostname and keys, and the hub's hub.env and database.
#
# Manual only -- never put this on cron. It replaces confettictl-register.sh, which
# constraint 13 says must be pushed deliberately: a broken copy stops
# registration and the self-update that would repair it. On a node, confettictl-setup.sh
# runs at the end, so the new confettictl-register.sh is tried right away, in front of
# whoever ran the update.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GITHUB_URL="https://github.com/orneh24/confetti-traffic/archive/refs/heads/main.tar.gz"
RELEASE_FILE="/etc/confetti-release"
NODE_CONFIG="/etc/confetti/config"

log() {
    printf '[update] %s\n' "$1"
}

die() {
    printf '[update] FATAL: %s\n' "$1" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "Must run as root"

case "${1:-}" in
    "") AUTO_YES="" ;;
    -y|--yes) AUTO_YES="1" ;;
    *)
        echo "Usage: confettictl-update [-y]" >&2
        exit 2
        ;;
esac

# -------------------------------------------------------------------
# Which role -- the same markers confettictl-install.sh refuses to run on
# -------------------------------------------------------------------
if [ -f /usr/local/bin/confetti/confettictl-setup.sh ]; then
    ROLE="node"
elif [ -d /opt/confetti-hub ]; then
    ROLE="hub"
else
    # An old VM's own updater (e.g. pervium-update) downloads this repo (GitHub
    # redirects the renamed URL) and lands here. Say why, not just "nothing
    # found": every path changed in the rename, so there is no in-place move.
    for _old in /usr/local/bin/pervium /opt/pervium-hub /usr/local/bin/mesh-flux /opt/mesh-flux-hub /usr/local/bin/mesh-probe /opt/mesh-probe-hub; do
        if [ -e "$_old" ]; then
            die "This VM runs the project under an earlier name ($_old). Confetti Traffic can't update it in place -- rebuild it from a fresh Alpine VM."
        fi
    done
    die "No Confetti Traffic install found on this VM. For a fresh Alpine VM, use confettictl-install.sh."
fi

if [ -n "${CONFETTI_UPDATE_URL:-}" ]; then
    UPDATE_URL="$CONFETTI_UPDATE_URL"
elif [ "$ROLE" = "hub" ]; then
    UPDATE_URL="$GITHUB_URL"
else
    # shellcheck source=/dev/null
    _hub=$( . "$NODE_CONFIG" >/dev/null 2>&1; printf '%s' "${HUB_URL:-}" ) || _hub=""
    UPDATE_URL="${_hub:+${_hub}/node/bundle.tar.gz}"
fi

# -------------------------------------------------------------------
# Download, unless this copy is already inside an unpacked repo.
#
# The installed copy only downloads. It then runs the confettictl-update.sh from the
# download, so the newest update logic always does the apply.
# -------------------------------------------------------------------
if [ ! -f "$SCRIPT_DIR/$ROLE/confettictl-build-template.sh" ]; then
    [ -n "$UPDATE_URL" ] || die "No HUB_URL in $NODE_CONFIG -- a node updates from its hub. Run confettictl-setup.sh first."
    TMP=$(mktemp -d /tmp/confettictl-update.XXXXXX)

    log "Downloading $UPDATE_URL"
    if ! curl -fsSL --connect-timeout 10 --max-time 300 -o "$TMP/src.tar.gz" "$UPDATE_URL"; then
        rm -rf "$TMP"
        # A hub set up without a DNS server has an empty resolv.conf: the
        # build clears it, and DNS is optional in confettictl-hub-setup.sh.
        if ! grep -q '^nameserver' /etc/resolv.conf 2>/dev/null; then
            log "No nameserver in /etc/resolv.conf -- add one first:"
            log "  echo 'nameserver <dns-ip>' > /etc/resolv.conf"
        fi
        die "Download failed. Nothing changed."
    fi

    if ! tar -xzf "$TMP/src.tar.gz" -C "$TMP"; then
        rm -rf "$TMP"
        die "Download is not a valid tarball. Nothing changed."
    fi

    SRC=""
    for _d in "$TMP"/*/; do
        [ -f "${_d}confettictl-update.sh" ] && SRC="${_d%/}"
    done
    if [ -z "$SRC" ] || [ ! -f "$SRC/$ROLE/confettictl-build-template.sh" ]; then
        rm -rf "$TMP"
        die "Download has no confettictl-update.sh or $ROLE/confettictl-build-template.sh. Nothing changed."
    fi

    if ! sh -n "$SRC/confettictl-update.sh" || ! sh -n "$SRC/$ROLE/confettictl-build-template.sh"; then
        rm -rf "$TMP"
        die "Downloaded scripts do not parse. Nothing changed."
    fi

    # GitHub archives carry the commit id in the tarball's pax header. The
    # hub's node bundle has none; it carries a RELEASE file instead, which
    # the apply below reads.
    COMMIT=$(gzip -dc "$TMP/src.tar.gz" 2>/dev/null | head -c 1024 | tr '\0' '\n' \
        | sed -n 's/^.*comment=\([0-9a-f]\{40\}\).*$/\1/p' | head -n 1) || COMMIT=""

    _rc=0
    CONFETTI_UPDATE_FROM="$UPDATE_URL" CONFETTI_UPDATE_COMMIT="${COMMIT:-unknown}" \
        sh "$SRC/confettictl-update.sh" "$@" || _rc=$?
    rm -rf "$TMP"
    exit "$_rc"
fi

# -------------------------------------------------------------------
# Apply from the repo tree this script sits in
# -------------------------------------------------------------------
SRC="$SCRIPT_DIR"
COMMIT="${CONFETTI_UPDATE_COMMIT:-unknown}"
if [ "$COMMIT" = "unknown" ] && [ -f "$SRC/RELEASE" ]; then
    COMMIT=$(sed -n 's/^commit=//p' "$SRC/RELEASE" | head -n 1 | tr -cd '0-9a-z')
    COMMIT="${COMMIT:-unknown}"
fi
FROM="${CONFETTI_UPDATE_FROM:-$SRC}"
CURRENT=$(sed -n 's/^commit=//p' "$RELEASE_FILE" 2>/dev/null) || CURRENT=""

echo
log "Role:      $ROLE"
log "Installed: ${CURRENT:-unknown}"
log "New:       $COMMIT"
log "From:      $FROM"
echo

if [ -z "$AUTO_YES" ]; then
    if [ "$ROLE" = "hub" ]; then
        echo "This updates the hub's code and packages and restarts it."
        echo "hub.env and the database are kept."
    else
        echo "This updates the node's code and packages and re-runs confettictl-setup.sh."
        echo "The config, hostname and SSH keys are kept."
    fi
    printf 'Update now? [y/N] '
    read -r ANSWER || ANSWER=""
    case "$ANSWER" in
        [yY]*) ;;
        *)
            log "Cancelled. Nothing changed."
            exit 0
            ;;
    esac
fi

log "Running $ROLE/confettictl-build-template.sh --update"
# The hub build stamps COMMIT into the node bundle it builds.
CONFETTI_UPDATE_COMMIT="$COMMIT" sh "$SRC/$ROLE/confettictl-build-template.sh" --update \
    || die "confettictl-build-template.sh --update failed (see above)"

cat > "$RELEASE_FILE" <<EOF
commit=$COMMIT
source=$FROM
updated=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

STATUS=0

if [ "$ROLE" = "hub" ]; then
    # The schema migrates itself on start (init_db). Results pushed during
    # the few seconds of the restart are lost.
    if rc-service confettid-hub restart; then
        log "confettid-hub restarted"
    else
        log "WARNING: confettid-hub did not restart -- check /var/log/confetti-hub.log"
        STATUS=1
    fi
elif [ -f "$NODE_CONFIG" ]; then
    # The documented safe re-run: keeps the config, merges cron, restarts
    # crond and confettid-httpd, and registers with the hub.
    log "Re-running confettictl-setup.sh"
    if ! /usr/local/bin/confetti/confettictl-setup.sh; then
        log "WARNING: confettictl-setup.sh failed (see above)"
        STATUS=1
    fi

    # confettictl-setup.sh only starts these. Restart the ones already running so they
    # read their new configs.
    for _svc in confettid-smbd confettid-smtpd confettid-iperf3; do
        if rc-service "$_svc" status >/dev/null 2>&1; then
            if rc-service "$_svc" restart >/dev/null 2>&1; then
                log "$_svc restarted"
            else
                log "WARNING: $_svc did not restart"
                STATUS=1
            fi
        fi
    done
else
    log "No $NODE_CONFIG: files updated, confettictl-setup.sh not run."
fi

echo
if [ "$STATUS" -eq 0 ]; then
    log "Update complete ($COMMIT)"
else
    log "Update applied with warnings (see above)"
fi
exit "$STATUS"
