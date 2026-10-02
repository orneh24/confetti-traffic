# /etc/profile.d/confettictl-login-status.sh — show the last test cycle plus a
# usage hint at interactive login. Same guard as
# confettictl-login-setup.sh (confettictl-login-setup.sh): interactive shells with a real
# tty only, so it never fires for scp/rsync/non-interactive SSH commands —
# see CLAUDE.md constraint 16.

case "$-" in
    *i*)
        if [ -t 0 ] && [ -f /etc/confetti/.setup-done ]; then
            echo
            echo "Last test cycle:"
            /usr/local/bin/confettictl-status 2>/dev/null || cat /run/confetti/last-cycle.txt 2>/dev/null
            echo
            echo "confettictl-status [-f|--follow] [-n N]   -- view this node's own test results"
            echo
        fi
        ;;
esac
