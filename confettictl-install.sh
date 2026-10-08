#!/bin/sh
# confettictl-install.sh — entry point for a freshly downloaded confetti repo on a
# fresh Alpine base VM. Asks whether this VM becomes a Hub or a Node, then
# either runs or names the matching confettictl-build-template.sh.
#
# Usage:
#   sh confettictl-install.sh              interactive: asks role, confirms before running
#   sh confettictl-install.sh hub|node     skips the role menu
#   sh confettictl-install.sh hub -y       skips the menu and the run confirmation too
#
# Deliberately refuses to run on a VM that's already been built into a role
# (see the guard below) — both confettictl-build-template.sh scripts are destructive if
# re-run on a configured system: they wipe /etc/confetti/config and the
# hostname, or the hub's results database, as their last step. Their only
# existing protection against that is self-deleting after a successful run,
# and that protection disappears the moment the repo is re-downloaded.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

log() {
    printf '[install] %s\n' "$1"
}

die() {
    printf '[install] FATAL: %s\n' "$1" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "Must run as root"

# -------------------------------------------------------------------
# Refuse on an already-built VM
# -------------------------------------------------------------------
if [ -f /usr/local/bin/confetti/confettictl-setup.sh ]; then
    die "This VM is already a configured node (/usr/local/bin/confetti/confettictl-setup.sh exists). Re-running confettictl-build-template.sh here would wipe its config and hostname. To update its code, run: sh $SCRIPT_DIR/confettictl-update.sh"
fi
if [ -d /opt/confetti-hub ]; then
    die "This VM is already a hub (/opt/confetti-hub exists). Re-running confettictl-build-template.sh here would wipe the results database. To update its code, run: sh $SCRIPT_DIR/confettictl-update.sh"
fi

# The project's earlier names. A Confetti Traffic build next to one of these would run
# two sets of services fighting over port 80, cron and the SMB/SMTP daemons.
# The paths all changed with each rename, so there is no in-place upgrade.
for _old in /usr/local/bin/pervium /opt/pervium-hub /usr/local/bin/mesh-flux /opt/mesh-flux-hub /usr/local/bin/mesh-probe /opt/mesh-probe-hub; do
    if [ -e "$_old" ]; then
        die "This VM has an install from before the project was renamed ($_old). Rebuild it from a fresh Alpine VM instead."
    fi
done

# -------------------------------------------------------------------
# Role selection
# -------------------------------------------------------------------
ROLE="${1:-}"

if [ -z "$ROLE" ]; then
    echo "=== confetti install ==="
    echo
    echo "This VM will become a:"
    echo "  1) Hub  -- infrastructure only, one per lab"
    echo "  2) Node -- one per network segment under test"
    echo
    printf 'Choice [1/2]: '
    if ! read -r ROLE; then
        echo
        echo "No input (stdin closed) -- nothing run. To build directly:"
        echo "  sh $SCRIPT_DIR/hub/confettictl-build-template.sh"
        echo "  sh $SCRIPT_DIR/node/confettictl-build-template.sh"
        exit 0
    fi
fi

case "$ROLE" in
    1|[hH]*) ROLE="hub" ;;
    2|[nN]*) ROLE="node" ;;
    *)
        die "Not a valid choice: '$ROLE' -- run this again and pick hub or node"
        ;;
esac

BUILD_SCRIPT="$SCRIPT_DIR/$ROLE/confettictl-build-template.sh"
[ -f "$BUILD_SCRIPT" ] || die "$BUILD_SCRIPT not found -- is this a full copy of the repo?"

echo
log "Role: $ROLE"
log "Next step: sh $BUILD_SCRIPT"
echo

# -------------------------------------------------------------------
# Confirm before running -- default is No. confettictl-build-template.sh installs
# packages and services system-wide and is not meant to be re-run once a
# VM is configured (see the guard above); running it should always be a
# deliberate, visible step, never a silent default.
# -------------------------------------------------------------------
AUTO_YES="${2:-}"
if [ "$AUTO_YES" = "-y" ] || [ "$AUTO_YES" = "--yes" ]; then
    RUNNOW="y"
else
    echo "This installs packages and configures this VM as a $ROLE. It is"
    echo "destructive to run again on an already-configured VM."
    printf 'Run it now? [y/N] '
    if ! read -r RUNNOW; then
        echo
        RUNNOW=""
    fi
fi

case "$RUNNOW" in
    [yY]*)
        # Node template: offer to bake the hub URL in, so clones ask only
        # for the group. Not with -y or without a keyboard.
        if [ "$ROLE" = "node" ] && [ -z "${CONFETTI_HUB_URL:-}" ] && [ -t 0 ] \
           && [ "$AUTO_YES" != "-y" ] && [ "$AUTO_YES" != "--yes" ]; then
            printf 'Hub IP address to store in the template, e.g. 10.0.0.100 (blank = ask on each clone): '
            read -r CONFETTI_HUB_URL || CONFETTI_HUB_URL=""
        fi
        # A bare address becomes http://<address>; a full URL is kept as typed.
        case "${CONFETTI_HUB_URL:-}" in
            ""|*://*) ;;
            *) CONFETTI_HUB_URL="http://${CONFETTI_HUB_URL}" ;;
        esac
        export CONFETTI_HUB_URL="${CONFETTI_HUB_URL:-}"
        log "Running $BUILD_SCRIPT ..."
        sh "$BUILD_SCRIPT"
        ;;
    *)
        log "Not run. When ready:"
        log "  sh $BUILD_SCRIPT"
        exit 0
        ;;
esac

# -------------------------------------------------------------------
# Offer to configure this VM in place, so a single VM goes from base
# Alpine to working in one run instead of needing a log out and back in.
# Runs the same wizard the login prompt would, so nothing new happens here.
# Only with a real keyboard: a scripted run leaves it to the login prompt
# or guestinfo, as before.
#
# Hub: run its wizard straight away. Its own first question ("Configure a
# static IP now? [Y/n]") is the offer, so asking here too would ask twice.
# Node: ask first, default no. Nodes are usually cloned from this VM as a
# template, and configuring it would undo the build's template cleanup;
# the node wizard's own question defaults to yes, so it can't be the offer.
# -------------------------------------------------------------------
if [ -t 0 ]; then
    if [ "$ROLE" = "hub" ]; then
        SETUP_CMD="/opt/confetti-hub/confettictl-hub-setup.sh"
        CONFIGURE="y"
    else
        SETUP_CMD="/usr/local/bin/confetti/confettictl-node-setup.sh"
        echo
        printf 'Configure this node now? Say no if you will turn it into a template. [y/N] '
        if ! read -r CONFIGURE; then
            echo
            CONFIGURE="n"
        fi
    fi
    if [ -f "$SETUP_CMD" ]; then
        echo
        case "$CONFIGURE" in
            [yY]*) sh "$SETUP_CMD" || log "Setup did not finish. Log out and back in to try again." ;;
            *)     log "Not configured. Log in again (or run $SETUP_CMD) when ready." ;;
        esac
    fi
fi
