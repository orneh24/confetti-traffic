# /etc/profile.d/pervium-node-setup.sh — invite an unconfigured node to
# run its setup wizard at first interactive login. Guarded to interactive
# shells with a real tty so it never fires for scp/rsync/non-interactive SSH
# commands.

case "$-" in
    *i*)
        if [ -t 0 ] && [ ! -f /etc/pervium/.setup-done ]; then
            /usr/local/bin/pervium/node-setup.sh || true
        fi
        ;;
esac
