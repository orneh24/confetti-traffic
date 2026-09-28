#!/bin/sh
# pervium-push-node-update.sh -- run pervium-update on the nodes, from the hub.
#
#   pervium-push-node-update.sh              nodes seen in the last 10 minutes
#   pervium-push-node-update.sh IP [IP ...]  only these nodes
#   pervium-push-node-update.sh -y ...       skip the confirmation
#   pervium-push-node-update.sh -m 30        nodes seen in the last 30 minutes
#
# Asks for the nodes' root password once and logs in with sshpass, one node
# at a time. Each node downloads the code from GitHub itself, so it needs DNS
# and internet access, same as running pervium-update on it by hand.
#
# Update the hub first (pervium-update on this VM): a node newer than its hub
# has test-cycle.sh reverted by self-update.
#
# Manual only. Never put this on cron: it replaces register.sh on every node,
# which is the unattended register.sh update constraint 13 forbids.
set -eu

AUTO_YES=""
MINUTES=10
while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) AUTO_YES="1" ;;
        -m) shift; MINUTES="${1:-}" ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        -*) echo "Unknown option: $1 (see -h)" >&2; exit 1 ;;
        *) break ;;
    esac
    shift
done
case "$MINUTES" in ''|*[!0-9]*) echo "-m needs a number of minutes" >&2; exit 1 ;; esac

for _cmd in ssh sshpass; do
    if ! command -v "$_cmd" >/dev/null 2>&1; then
        echo "$_cmd not found. Install it: apk add openssh-client sshpass" >&2
        exit 1
    fi
done

# -------------------------------------------------------------------
# Which nodes: the IPs given, or every endpoint seen recently.
# -------------------------------------------------------------------
if [ $# -gt 0 ]; then
    NODES="$*"
else
    HUB_PORT=$(sed -n 's/^HUB_PORT=//p' /opt/pervium-hub/hub.env 2>/dev/null | tr -d '"' | tail -n 1)
    _json=$(curl -fsS "http://127.0.0.1:${HUB_PORT:-80}/endpoints") || {
        echo "Could not read the node list from the hub (is pervium-hub running?)" >&2
        exit 1
    }
    NODES=$(printf '%s' "$_json" | python3 -c '
import json, sys
from datetime import datetime, timedelta, timezone
cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(sys.argv[1]))
for e in json.load(sys.stdin):
    seen = datetime.strptime(e["last_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if seen >= cutoff:
        print(e["ip"])
' "$MINUTES")
fi

if [ -z "$NODES" ]; then
    echo "No nodes seen in the last $MINUTES minutes. Give IPs as arguments instead."
    exit 1
fi

echo "Nodes to update:"
for _ip in $NODES; do echo "  $_ip"; done

if [ -z "$AUTO_YES" ]; then
    printf 'Run pervium-update on these nodes? [y/N] '
    read -r ANSWER || ANSWER=""
    case "$ANSWER" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 0 ;; esac
fi

printf 'Root password for the nodes: '
stty -echo 2>/dev/null || true
read -r NODE_PASSWORD || NODE_PASSWORD=""
stty echo 2>/dev/null || true
echo
if [ -z "$NODE_PASSWORD" ]; then
    echo "No password given." >&2
    exit 1
fi

# -------------------------------------------------------------------
# One node at a time. Nodes built before pervium-update existed fetch it
# first, the same one-liner the README gives. stdin is /dev/null so nothing
# on the node can stop and wait for input. PATH is set because an ssh
# command (no login shell) gets only /usr/bin:/bin from dropbear.
# -------------------------------------------------------------------
REMOTE='PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; export PATH; if command -v pervium-update >/dev/null 2>&1; then pervium-update -y; else curl -fsSLo /tmp/pervium-update https://raw.githubusercontent.com/orneh24/pervium/main/update.sh && sh /tmp/pervium-update -y; fi'

OK=""
FAILED=""
for _ip in $NODES; do
    echo
    echo "=== $_ip ==="
    _rc=0
    SSHPASS="$NODE_PASSWORD" sshpass -e ssh \
        -o StrictHostKeyChecking=accept-new \
        -o ConnectTimeout=10 \
        -o PubkeyAuthentication=no \
        "root@$_ip" "$REMOTE" < /dev/null || _rc=$?
    case "$_rc" in
        0)   OK="$OK $_ip"; continue ;;
        5)   echo "--- $_ip FAILED: wrong password" ;;
        255) echo "--- $_ip FAILED: could not connect (unreachable, or a rebuilt node with a new host key: ssh-keygen -R $_ip)" ;;
        *)   echo "--- $_ip FAILED: pervium-update exited $_rc (see output above)" ;;
    esac
    FAILED="$FAILED $_ip"
done
NODE_PASSWORD=""

echo
echo "Updated:${OK:- none}"
if [ -n "$FAILED" ]; then
    echo "Failed: $FAILED"
    exit 1
fi
