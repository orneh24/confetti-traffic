# /etc/profile.d/confettictl-login-setup.sh — invite an unconfigured node to
# run its setup wizard at first interactive login, and tell a configured one
# how to re-run it. Guarded to interactive shells with a real tty so it never
# fires for scp/rsync/non-interactive SSH commands.

case "$-" in
    *i*)
        if [ -t 0 ]; then
            if [ ! -f /etc/confetti/.setup-done ]; then
                /usr/local/bin/confetti/confettictl-node-setup.sh || true
            else
                echo "To re-run setup:"
                echo "  /usr/local/bin/confetti/confettictl-node-setup.sh --force"
                echo
            fi
        fi
        ;;
esac
