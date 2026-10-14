#!/bin/sh
# confettictl-changes.sh — the dashboard's "Recent Changes" on the console.
#
# Follows by default (like tail -f); -o prints once and exits.
# Lists pass/fail flips, "ALL tests FAILED" and traceroute path changes, oldest
# first, newest at the bottom. Reads this hub's own /api/changes, so it needs
# only curl and works from the hub console or over SSH.

set -u

MINUTES=60
COUNT=15
FOLLOW="yes"
IPS=""
INTERVAL=2

usage() {
    cat <<EOF
Usage: confettictl-changes [-o] [-n N] [-m MINUTES] [-s SEC] [-i] [-h]

  (no args)     Show the last 15 changes from the last hour, then keep running
                and print each new change as it appears (every ${INTERVAL} s).
  -o, --once    Print and exit, do not follow.
  -n N          Show up to N changes (default 15, max 200).
  -m MINUTES    Look back this many minutes (default 60).
  -s SEC        Seconds between checks while following (default 2).
  -i            Show IP addresses instead of host names.
  -h, --help    This help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -f|--follow) FOLLOW="yes" ;;   # the default; kept so old habits work
        -o|--once) FOLLOW="no" ;;
        -n) shift; COUNT="${1:-}" ;;
        -m) shift; MINUTES="${1:-}" ;;
        -s) shift; INTERVAL="${1:-}" ;;
        -i) IPS="&ip=1" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
    shift
done

case "$COUNT$MINUTES$INTERVAL" in
    ""|*[!0-9]*) echo "-n, -m and -s need a number." >&2; exit 1 ;;
esac
[ "$INTERVAL" -ge 1 ] || { echo "-s needs at least 1." >&2; exit 1; }

PORT=$(sed -n 's/^HUB_PORT=//p' /opt/confetti-hub/hub.env 2>/dev/null | tr -d '"' | tail -n 1)
# CHANGES_BASE_URL is for the dev hub; on a real hub the local port is right.
URL="${CHANGES_BASE_URL:-http://127.0.0.1:${PORT:-80}}/api/changes?format=text&minutes=${MINUTES}&limit=${COUNT}${IPS}"

fetch() {
    curl -sf --max-time 10 "$URL"
}

if [ "$FOLLOW" != "yes" ]; then
    _out=$(fetch) || { echo "The hub did not answer at $URL" >&2; exit 1; }
    if [ -n "$_out" ]; then
        printf '%s\n' "$_out"
    else
        echo "No changes in the last ${MINUTES} minutes."
    fi
    exit 0
fi

# Follow: lines already printed are remembered, so a change shows once. Whole
# lines are compared because several changes can share a second.
# The hub answers an empty 304 while nothing new was posted (if_id with the
# X-Results-Id of the last answer), so a short interval costs it almost nothing.
_seen=$(mktemp) || exit 1
_hdr=$(mktemp) || exit 1
trap 'rm -f "$_seen" "$_hdr"' EXIT
trap 'exit 0' INT TERM
_last=""
echo "Following changes (every ${INTERVAL} s, Ctrl-C to stop)."
while true; do
    if _out=$(curl -sf --max-time 10 -D "$_hdr" "${URL}${_last:+&if_id=$_last}"); then
        _id=$(sed -n 's/^[Xx]-[Rr]esults-[Ii]d: *//p' "$_hdr" | tr -d '\r' | tail -n 1)
        [ -n "$_id" ] && _last="$_id"
        if [ -n "$_out" ]; then
            printf '%s\n' "$_out" | grep -vxF -f "$_seen" || true
            printf '%s\n' "$_out" >> "$_seen"
        fi
    else
        echo "The hub did not answer at $URL" >&2
    fi
    sleep "$INTERVAL"
done
