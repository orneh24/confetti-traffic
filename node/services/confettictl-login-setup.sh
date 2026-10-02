# /etc/profile.d/confettictl-login-setup.sh — invite an unconfigured node to
# run its setup wizard at first interactive login. Guarded to interactive
# shells with a real tty so it never fires for scp/rsync/non-interactive SSH
# commands.

case "$-" in
    *i*)
        if [ -t 0 ] && [ ! -f /etc/confetti/.setup-done ]; then
            /usr/local/bin/confetti/confettictl-node-setup.sh || true
        fi
        ;;
esac
