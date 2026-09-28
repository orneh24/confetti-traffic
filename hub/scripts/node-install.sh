#!/bin/sh
# node-install.sh -- served by the hub at /install.sh. Turns a plain Alpine
# VM into a pervium node using only this hub: no GitHub, no repo copy.
#
#   wget -O /tmp/i.sh http://<hub>/install.sh && sh /tmp/i.sh [group]
#
# Download first, then run -- don't pipe it into sh: setup.sh prompts for
# whatever it still needs, and a piped script's stdin is the script itself.
#
# It downloads the hub's node bundle, runs node/build-template.sh --update
# (the build's install steps without the template cleanup, which would wipe
# the config and zero-fill the disk), records the build, then runs setup.sh
# with HUB_URL already set. For golden templates use the repo's install.sh.

set -eu

# Filled in by the hub when it serves this file.
HUB_URL="@HUB_URL@"

log() { printf '[node-install] %s\n' "$1"; }
die() { printf '[node-install] FATAL: %s\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Must run as root"
[ -f /etc/alpine-release ] || die "This is not Alpine Linux"
[ -f /usr/local/bin/pervium/setup.sh ] && die "Already a pervium node. Update it from the hub dashboard or with pervium-update."
[ -d /opt/pervium-hub ] && die "This VM is a pervium hub"
case "$HUB_URL" in
    http://*|https://*) ;;
    *) die "Hub URL was not filled in -- download this from http://<hub>/install.sh" ;;
esac

GROUP="${1:-}"

TMP=$(mktemp -d /tmp/pervium-install.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

# BusyBox wget: curl is not on a plain Alpine VM yet (the build adds it).
log "Downloading node bundle from $HUB_URL"
wget -q -O "$TMP/bundle.tar.gz" "${HUB_URL}/node/bundle.tar.gz" || die "Download failed"
tar -xzf "$TMP/bundle.tar.gz" -C "$TMP" || die "Bundle is not a valid tarball"
SRC="$TMP/pervium"
[ -f "$SRC/node/build-template.sh" ] || die "Bundle has no node/build-template.sh"
sh -n "$SRC/node/build-template.sh" || die "Bundle scripts do not parse"

log "Installing node files and packages"
sh "$SRC/node/build-template.sh" --update || die "build-template.sh failed (see above)"

COMMIT=$(sed -n 's/^commit=//p' "$SRC/RELEASE" 2>/dev/null | head -n 1 | tr -cd '0-9a-z')
cat > /etc/pervium-release <<EOF
commit=${COMMIT:-unknown}
source=${HUB_URL}/node/bundle.tar.gz
updated=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

log "Configuring (setup.sh)"
if HUB_URL="$HUB_URL" GROUP_NAME="$GROUP" /usr/local/bin/pervium/setup.sh; then
    # The same stamps firstboot.initd writes, so the login wizard doesn't
    # offer to configure a node that already is.
    date -u '+%Y-%m-%dT%H:%M:%SZ' > /etc/pervium/.firstboot-done
    date -u '+%Y-%m-%dT%H:%M:%SZ configured (installed from hub)' > /etc/pervium/.setup-done
    log "Done: $(hostname) is a pervium node of $HUB_URL"
else
    die "setup.sh failed (see above). Fix it and run /usr/local/bin/pervium/setup.sh again."
fi
