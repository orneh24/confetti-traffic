#!/bin/sh
# confettictl-hub-setup.sh — interactive first-time configuration for the confetti hub.
#
# Run automatically at first interactive login (see services/confettictl-login-setup.sh)
# when the hub hasn't been configured yet, or by hand at any time. Safe to
# re-run; does nothing once configured unless you pass --force.
#
# Sets the static IP (plus optional DNS server and hostname), restarts
# networking and starts confettid-hub -- every
# step between a finished build and a working dashboard. hub.env defaults are
# sane enough not to need a prompt; edit it by hand afterward if they don't
# suit.

set -eu

CONF_DIR="/etc/confetti-hub"
STAMP="${CONF_DIR}/.setup-done"

mkdir -p "$CONF_DIR"

if [ -f "$STAMP" ] && [ "${1:-}" != "--force" ]; then
    echo "Hub already configured ($(cat "$STAMP"))."
    echo "Re-run with --force to reconfigure."
    exit 0
fi

echo "=== confetti hub setup ==="
echo

CURRENT_IP=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | head -1)
echo "Current address: ${CURRENT_IP:-none}"
echo

# `if ! read` vs `read -r VAR || VAR=""`: use the former wherever a default
# would otherwise fire on EOF (a closed/non-tty stdin reads as an empty
# string, which `||` can't tell apart from a bare Enter) -- ANSWER below
# defaults to yes, so EOF must not be read as consent. `||` stays correct
# everywhere empty-and-EOF should mean the same thing, as with SKIP,
# GATEWAY and CONFIRM below. GATEWAY has a default, but nothing is applied
# until CONFIRM says yes, and CONFIRM defaults to no.
printf 'Configure a static IP now? [Y/n] '
if ! read -r ANSWER; then
    echo
    echo "No input (stdin closed) -- nothing changed."
    exit 0
fi
case "$ANSWER" in
    [nN]*)
        printf "Skip and don't ask again at login? [y/N] "
        read -r SKIP || SKIP=""
        case "$SKIP" in
            [yY]*)
                date -u '+%Y-%m-%dT%H:%M:%SZ skipped' > "$STAMP"
                echo "Won't ask again. Run 'confettictl-hub-setup.sh --force' any time to configure."
                ;;
            *)
                echo "Skipped for now -- you'll be asked again at next login."
                ;;
        esac
        exit 0
        ;;
esac

# Checks an IP/prefix and prints the subnet's first address (network + 1),
# the default offered for the gateway: 172.16.200.214/16 -> 172.16.0.1.
# Exits 1 if the input is not IP/prefix. Prints nothing for /31 and /32,
# which have no separate gateway address. Integer arithmetic, since BusyBox
# awk has no bitwise AND. node/scripts/confettictl-setup.sh has an identical copy.
first_host() {
    awk -v cidr="$1" 'BEGIN {
        if (split(cidr, p, "/") != 2 || p[2] !~ /^[0-9]+$/ || p[2] > 32) exit 1
        if (split(p[1], o, ".") != 4) exit 1
        for (i = 1; i <= 4; i++) if (o[i] !~ /^[0-9]+$/ || o[i] > 255) exit 1
        if (p[2] > 30) exit 0
        ip = o[1]*16777216 + o[2]*65536 + o[3]*256 + o[4]
        d = 2 ^ (32 - p[2])
        gw = int(ip / d) * d + 1
        printf "%d.%d.%d.%d", int(gw/16777216)%256, int(gw/65536)%256, int(gw/256)%256, gw%256
    }'
}

# Asked again until it has a /prefix: the gateway default depends on it.
# EOF stops the loop (`if ! read`), so a closed stdin cannot spin here.
while :; do
    printf 'Static IP/CIDR (e.g. 10.0.0.100/24): '
    if ! read -r IP_CIDR; then IP_CIDR=""; break; fi
    [ -z "$IP_CIDR" ] && break
    if GW_DEFAULT=$(first_host "$IP_CIDR"); then break; fi
    case "$IP_CIDR" in
        */*) echo "Not a valid IP/prefix -- e.g. 10.0.0.100/24." ;;
        *)   echo "Include the prefix length -- e.g. ${IP_CIDR}/24." ;;
    esac
done

GW_DEFAULT="${GW_DEFAULT:-}"
if [ -n "$GW_DEFAULT" ]; then
    printf 'Gateway [%s]: ' "$GW_DEFAULT"
else
    printf 'Gateway (e.g. 10.0.0.1): '
fi
read -r GATEWAY || GATEWAY=""
[ -n "$GATEWAY" ] || GATEWAY="$GW_DEFAULT"

if [ -z "$IP_CIDR" ] || [ -z "$GATEWAY" ]; then
    echo "Both values are required -- aborting, nothing changed."
    exit 1
fi

# Both optional. Without DNS the hub can't resolve anything -- the build
# empties resolv.conf -- so confettictl-update can't reach GitHub and a chrony
# pool hostname won't resolve.
printf 'DNS server (e.g. 10.0.0.53, blank to skip): '
read -r DNS || DNS=""
DEFAULT_HOSTNAME=confetti-hub
printf 'Hostname [%s]: ' "$DEFAULT_HOSTNAME"
read -r NEW_HOSTNAME || NEW_HOSTNAME=""
[ -n "$NEW_HOSTNAME" ] || NEW_HOSTNAME="$DEFAULT_HOSTNAME"

case "$NEW_HOSTNAME" in
    *[!A-Za-z0-9-]*|-*)
        echo "Hostname may only contain letters, digits and '-' -- aborting, nothing changed."
        exit 1
        ;;
esac

echo
echo "About to set: ${IP_CIDR} via ${GATEWAY}"
echo "  DNS:      ${DNS:-none (confettictl-update and NTP by name will not work)}"
echo "  Hostname: ${NEW_HOSTNAME}"
printf 'Apply now? [y/N] '
read -r CONFIRM || CONFIRM=""
case "$CONFIRM" in
    [yY]*) ;;
    *)
        echo "Cancelled -- nothing changed."
        exit 0
        ;;
esac

_was_running=""
rc-service confettid-hub status >/dev/null 2>&1 && _was_running="1"

confettictl-set-static-ip "$IP_CIDR" "$GATEWAY" "$DNS" "$NEW_HOSTNAME"
rc-service networking restart

date -u '+%Y-%m-%dT%H:%M:%SZ configured' > "$STAMP"

# A running hub is restarted by the networking restart itself (it depends on
# net), and OpenRC finishes that in the background. Wait for it: starting it
# here as well races that restart and fails on OpenRC's lock ("Call to flock
# failed"). A hub that was not running (first setup: the build only enables
# it at boot) is started here, so the dashboard is up without a reboot. Not
# fatal either way -- the IP is set and stamped, and the fix is the same
# command by hand.
echo
if [ -n "$_was_running" ]; then
    _i=0
    while [ "$_i" -lt 30 ] && ! rc-service confettid-hub status >/dev/null 2>&1; do
        sleep 1
        _i=$((_i + 1))
    done
fi
if rc-service confettid-hub status >/dev/null 2>&1 || rc-service confettid-hub start; then
    echo "Hub running. Dashboard: http://${IP_CIDR%/*}/"
else
    echo "Static IP set, but confettid-hub failed to start."
    echo "Check: rc-service confettid-hub status"
fi
echo "Edit /opt/confetti-hub/hub.env if the defaults don't suit, then:"
echo "  rc-service confettid-hub restart"
