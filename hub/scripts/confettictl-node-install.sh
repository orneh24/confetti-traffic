#!/bin/sh
# confettictl-node-install.sh -- served by the hub at /confettictl-install.sh. Turns a plain Alpine
# VM into a confetti node using only this hub: no GitHub, no repo copy.
#
#   wget -O /tmp/i.sh http://<hub>/install.sh && sh /tmp/i.sh [group]
#
# Download first, then run -- don't pipe it into sh: confettictl-setup.sh prompts for
# whatever it still needs, and a piped script's stdin is the script itself.
#
# It downloads the hub's node bundle, runs node/confettictl-build-template.sh --update
# (the build's install steps without the template cleanup, which would wipe
# the config and zero-fill the disk), records the build, then runs confettictl-setup.sh
# with HUB_URL already set. For golden templates use the repo's confettictl-install.sh.

set -eu

# Filled in by the hub when it serves this file.
HUB_URL="@HUB_URL@"

log() { printf '[node-install] %s\n' "$1"; }
die() { printf '[node-install] FATAL: %s\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Must run as root"
[ -f /etc/alpine-release ] || die "This is not Alpine Linux"
# A configured node, not just installed files: an install that failed
# halfway (package mirror down, say) leaves confettictl-setup.sh behind, and must be
# re-runnable. Re-running the install steps is harmless -- they are the
# same --update steps confettictl-update uses.
[ -f /etc/confetti/config ] && die "Already a configured confetti node. Update it from the hub dashboard or with confettictl-update."
[ -d /opt/confetti-hub ] && die "This VM is a confetti hub"
case "$HUB_URL" in
    http://*|https://*) ;;
    *) die "Hub URL was not filled in -- download this from http://<hub>/install.sh" ;;
esac

GROUP="${1:-}"

TMP=$(mktemp -d /tmp/confetti-install.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

# BusyBox wget: curl is not on a plain Alpine VM yet (the build adds it).
log "Downloading node bundle from $HUB_URL"
wget -q -O "$TMP/bundle.tar.gz" "${HUB_URL}/node/bundle.tar.gz" || die "Download failed"
tar -xzf "$TMP/bundle.tar.gz" -C "$TMP" || die "Bundle is not a valid tarball"
SRC="$TMP/confetti"
[ -f "$SRC/node/confettictl-build-template.sh" ] || die "Bundle has no node/confettictl-build-template.sh"
sh -n "$SRC/node/confettictl-build-template.sh" || die "Bundle scripts do not parse"

log "Installing node files and packages"
sh "$SRC/node/confettictl-build-template.sh" --update || die "confettictl-build-template.sh failed (see above)"

COMMIT=$(sed -n 's/^commit=//p' "$SRC/RELEASE" 2>/dev/null | head -n 1 | tr -cd '0-9a-z')
cat > /etc/confetti-release <<EOF
commit=${COMMIT:-unknown}
source=${HUB_URL}/node/bundle.tar.gz
updated=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

log "Configuring (confettictl-setup.sh)"
if HUB_URL="$HUB_URL" GROUP_NAME="$GROUP" /usr/local/bin/confetti/confettictl-setup.sh; then
    # The same stamps firstboot.initd writes, so the login wizard doesn't
    # offer to configure a node that already is.
    date -u '+%Y-%m-%dT%H:%M:%SZ' > /etc/confetti/.firstboot-done
    date -u '+%Y-%m-%dT%H:%M:%SZ configured (installed from hub)' > /etc/confetti/.setup-done
    log "Done: $(hostname) is a confetti node of $HUB_URL"
else
    die "confettictl-setup.sh failed (see above). Fix it and run /usr/local/bin/confetti/confettictl-setup.sh again."
fi
