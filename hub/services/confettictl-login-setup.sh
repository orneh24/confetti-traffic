# /etc/profile.d/confettictl-login-setup.sh — invite an unconfigured hub to run
# its setup wizard at first interactive login, then show the one-line node
# install command with this hub's real address. Guarded to interactive shells
# with a real tty so it never fires for scp/rsync/non-interactive SSH
# commands.

case "$-" in
    *i*)
        if [ -t 0 ]; then
            if [ ! -f /etc/confetti-hub/.setup-done ]; then
                /opt/confetti-hub/confettictl-hub-setup.sh || true
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
        fi
        ;;
esac
