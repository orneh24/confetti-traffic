# /etc/profile.d/confettictl-login-setup.sh — invite an unconfigured hub to run
# its setup wizard at first interactive login. Guarded to interactive shells
# with a real tty so it never fires for scp/rsync/non-interactive SSH
# commands.

case "$-" in
    *i*)
        if [ -t 0 ] && [ ! -f /etc/confetti-hub/.setup-done ]; then
            /opt/confetti-hub/confettictl-hub-setup.sh || true
        fi
        ;;
esac
