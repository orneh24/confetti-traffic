#!/bin/sh
# confettictl-update.sh — pull the latest confetti code onto an already-installed hub
# or node. Both build scripts install it as /usr/local/bin/confettictl-update.
#
# Usage:
#   confettictl-update         download the latest code, confirm, apply
#   confettictl-update -y      same, without the confirmation
#   confettictl-update --rollback    hub only: put the previous hub code back
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
# On a hub it also backs up the database (sqlite3 .backup, newest 5 kept in
# /var/lib/confetti/backups), keeps the old code as /opt/confetti-hub.prev,
# waits for /api/health after the restart and puts the old code back by itself
# if the hub does not come up. The database is not restored on a rollback:
# new versions only add tables and columns.
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

ROLLBACK=""
case "${1:-}" in
    "") AUTO_YES="" ;;
    -y|--yes) AUTO_YES="1" ;;
    --rollback) AUTO_YES="1"; ROLLBACK="1" ;;
    *)
        echo "Usage: confettictl-update [-y | --rollback]" >&2
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

# -------------------------------------------------------------------
# Hub safety net: code copy, database backup, health check, rollback.
# A node has no database and updates from its hub, so none of this is for it.
# -------------------------------------------------------------------
HUB_DIR="/opt/confetti-hub"
HUB_PREV="${HUB_DIR}.prev"
HUB_ENV="${HUB_DIR}/hub.env"
BACKUP_DIR="/var/lib/confetti/backups"
BACKUP_KEEP=5
HEALTH_WAIT_S=30

hub_health_url() {
    _port=$(sed -n 's/^HUB_PORT=//p' "$HUB_ENV" 2>/dev/null | tr -d '"' | tail -n 1)
    printf 'http://127.0.0.1:%s/api/health' "${_port:-80}"
}

hub_wait_healthy() {
    _url=$(hub_health_url)
    _i=0
    while [ "$_i" -lt "$HEALTH_WAIT_S" ]; do
        if curl -fs -m 3 -o /dev/null "$_url"; then
            return 0
        fi
        sleep 1
        _i=$((_i + 1))
    done
    return 1
}

# Put the previous hub code back. $1 = where the current (bad) one is parked.
# The database is not restored: new versions only add tables and columns.
hub_swap_back() {
    rc-service confettid-hub stop >/dev/null 2>&1 || true
    rm -rf "$1"
    mv "$HUB_DIR" "$1"
    mv "$HUB_PREV" "$HUB_DIR"
    rc-service confettid-hub start >/dev/null 2>&1 || true
}

if [ -n "$ROLLBACK" ]; then
    [ "$ROLE" = "hub" ] || die "--rollback is for a hub; a node updates from its hub"
    [ -d "$HUB_PREV" ] || die "No previous version at $HUB_PREV"
    log "Rolling back the hub code to the previous version"
    hub_swap_back "${HUB_DIR}.rolled-back"
    hub_wait_healthy || die "Previous version did not become healthy -- check /var/log/confetti-hub.log"
    log "Rolled back. The version you left is in ${HUB_DIR}.rolled-back"
    exit 0
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

BACKUP=""
if [ "$ROLE" = "hub" ]; then
    # Database backup (WAL-safe: sqlite3 .backup, not a file copy), then a copy
    # of the code for the rollback. Both before anything is changed.
    _db=$(sed -n 's/^HUB_DB_PATH=//p' "$HUB_ENV" 2>/dev/null | tr -d '"' | tail -n 1)
    _db="${_db:-/var/lib/confetti/hub.db}"
    if [ -f "$_db" ]; then
        command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is not installed. Nothing changed."
        mkdir -p "$BACKUP_DIR"
        chmod 700 "$BACKUP_DIR"
        BACKUP="${BACKUP_DIR}/hub-pre-update-$(date -u +%Y%m%d-%H%M%S).db"
        log "Backing up the database to $BACKUP"
        sqlite3 "$_db" ".backup '${BACKUP}'" || die "Database backup failed. Nothing changed."
        chmod 600 "$BACKUP"
        # Our own names (no spaces), newest first; drop all but the newest few.
        for _old in $(ls -1t "${BACKUP_DIR}"/hub-pre-update-*.db 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))"); do
            rm -f "$_old"
        done
    fi
    log "Saving the current hub code to $HUB_PREV (confettictl-update --rollback)"
    rm -rf "$HUB_PREV"
    cp -a "$HUB_DIR" "$HUB_PREV" || die "Could not copy $HUB_DIR. Nothing changed."
fi

log "Running $ROLE/confettictl-build-template.sh --update"
# The hub build stamps COMMIT into the node bundle it builds.
if ! CONFETTI_UPDATE_COMMIT="$COMMIT" sh "$SRC/$ROLE/confettictl-build-template.sh" --update; then
    if [ "$ROLE" = "hub" ]; then
        log "Build failed -- putting the previous hub code back"
        hub_swap_back "${HUB_DIR}.failed"
        [ -z "$BACKUP" ] || log "Database backup: $BACKUP"
    fi
    die "confettictl-build-template.sh --update failed (see above)"
fi

write_release() {
    cat > "$RELEASE_FILE" <<EOF
commit=$COMMIT
source=$FROM
updated=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF
}

STATUS=0

if [ "$ROLE" = "hub" ]; then
    # The schema migrates itself on start (init_db). Results pushed during
    # the few seconds of the restart are lost.
    rc-service confettid-hub restart >/dev/null 2>&1 || true
    if hub_wait_healthy; then
        log "confettid-hub restarted and healthy. Previous code kept in $HUB_PREV (confettictl-update --rollback)."
        [ -z "$BACKUP" ] || log "Database backup: $BACKUP"
        write_release
    else
        log "New hub did not become healthy within ${HEALTH_WAIT_S}s -- rolling back"
        hub_swap_back "${HUB_DIR}.failed"
        if hub_wait_healthy; then
            log "Rolled back to the previous code. The failed one is in ${HUB_DIR}.failed; see /var/log/confetti-hub.log"
        else
            log "Previous code is not healthy either -- check /var/log/confetti-hub.log"
        fi
        [ -z "$BACKUP" ] || log "Database backup: $BACKUP"
        exit 1
    fi
elif [ -f "$NODE_CONFIG" ]; then
    write_release
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
    write_release
    log "No $NODE_CONFIG: files updated, confettictl-setup.sh not run."
fi

echo
if [ "$STATUS" -eq 0 ]; then
    log "Update complete ($COMMIT)"
else
    log "Update applied with warnings (see above)"
fi
exit "$STATUS"
