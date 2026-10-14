# /etc/profile.d/confettictl-login-setup.sh — invite an unconfigured hub to run
# its setup wizard at first interactive login, tell a configured one how to
# re-run it, then show the one-line node
# install command with this hub's real address. Guarded to interactive shells
# with a real tty so it never fires for scp/rsync/non-interactive SSH
# commands.

case "$-" in
    *i*)
        if [ -t 0 ]; then
            if [ ! -f /etc/confetti-hub/.setup-done ]; then
                /opt/confetti-hub/confettictl-hub-setup.sh || true
            else
                # Already configured: say how to run the wizard again.
                echo "To re-run setup:"
                echo "  /opt/confetti-hub/confettictl-hub-setup.sh --force"
                echo
            fi
            # Read after the wizard, so a just-set static IP is the one shown.
            _ct_ip=$(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4; exit}' | cut -d/ -f1)
            _ct_port=$(sed -n 's/^HUB_PORT=//p' /opt/confetti-hub/hub.env 2>/dev/null | tr -d '"' | tail -n 1)
            case "$_ct_port" in ""|80) _ct_port="" ;; *) _ct_port=":$_ct_port" ;; esac
            if [ -n "$_ct_ip" ]; then
                echo "Install a node from this hub (on a plain Alpine VM):"
                echo "  wget -O /tmp/i.sh http://${_ct_ip}${_ct_port}/install.sh && sh /tmp/i.sh [group]"
                echo
            fi
            unset _ct_ip _ct_port
            # Installed build, and a newer one if the start-up check found it
            # (confettictl-check-update.sh). Only says "new" when the installed
            # commit is known and is not a prefix of the latest.
            _ct_cur=$(sed -n 's/^commit=//p' /etc/confetti-release 2>/dev/null | head -n 1 | tr -cd '0-9a-z')
            _ct_new=$(head -n 1 /run/confetti-hub-latest 2>/dev/null | tr -cd '0-9a-f')
            echo "Installed build: $(printf '%.7s' "${_ct_cur:-unknown}")"
            if [ -n "$_ct_new" ] && [ -n "$_ct_cur" ] && [ "$_ct_cur" != "unknown" ]; then
                case "$_ct_new" in
                    "$_ct_cur"*) ;;
                    *) echo "New version available: $(printf '%.7s' "$_ct_new")  -> run: confettictl-update" ;;
                esac
            fi
            echo
            unset _ct_cur _ct_new
        fi
        ;;
esac
