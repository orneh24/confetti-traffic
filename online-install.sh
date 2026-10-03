#!/bin/sh
# online-install.sh — one-step start for a fresh Alpine VM. Downloads the repo
# from GitHub to /root/confetti and runs confettictl-install.sh from it.
#
# Usage (as root):
#   wget -O /tmp/oi.sh https://github.com/orneh24/confetti-traffic/raw/main/online-install.sh && sh /tmp/oi.sh [hub|node] [-y]
#
# Arguments are passed through to confettictl-install.sh.
#
# Save it to a file and run it; do not pipe it into sh. confettictl-install.sh
# and the setup after it ask questions, and a piped script's stdin is the pipe,
# not the keyboard.

set -eu

GITHUB_URL="https://github.com/orneh24/confetti-traffic/archive/refs/heads/main.tar.gz"
DEST="/root/confetti"

log() {
    printf '[online-install] %s\n' "$1"
}

die() {
    printf '[online-install] FATAL: %s\n' "$1" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "Must run as root"

# Unpack into a temp dir first, so a failed download leaves any earlier
# /root/confetti untouched.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "Downloading $GITHUB_URL"
wget -q -O "$TMP/repo.tar.gz" "$GITHUB_URL" || die "Download failed. Check DNS and internet access."
tar -xzf "$TMP/repo.tar.gz" -C "$TMP" || die "Could not unpack the download."
[ -f "$TMP/confetti-traffic-main/confettictl-install.sh" ] || die "Download does not look like the confetti repo."

# A second run replaces the old copy instead of nesting inside it. This is
# only the downloaded source; confettictl-install.sh itself refuses to run on
# a VM that is already a hub or node.
if [ -e "$DEST" ]; then
    log "Replacing existing $DEST"
    rm -rf "$DEST"
fi
mv "$TMP/confetti-traffic-main" "$DEST"
log "Repo is in $DEST"

sh "$DEST/confettictl-install.sh" "$@"
