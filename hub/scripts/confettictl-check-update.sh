#!/bin/sh
# confettictl-check-update.sh — ask GitHub which commit main is at and leave
# it in /run/confetti-hub-latest for the login banner. Started in the
# background by confettid-hub's start_post, so it never delays the boot.
# Silent on every failure (no internet, no DNS, rate limit): the file is
# then simply absent and the banner says nothing. Opt out with
# HUB_UPDATE_CHECK=false in hub.env.

OUT="/run/confetti-hub-latest"
URL="https://api.github.com/repos/orneh24/confetti-traffic/commits/main"

rm -f "$OUT"
[ "${HUB_UPDATE_CHECK:-true}" = "false" ] && exit 0

# The sha media type makes GitHub return just the 40-character commit id.
_sha=$(wget -q -T 10 -O - --header 'Accept: application/vnd.github.sha' "$URL" 2>/dev/null | tr -cd '0-9a-f')
case "${#_sha}" in
    40) printf '%s\n' "$_sha" > "$OUT" ;;
esac
exit 0
