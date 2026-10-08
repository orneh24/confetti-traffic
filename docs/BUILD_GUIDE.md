# Confetti Traffic — Build Guide

Detail behind each step of the [README quick start](../README.md#quick-start)
and the `DEPLOYMENT.md` checklist. You build one Alpine base VM, clone it,
turn one clone into the hub and one into the node template, then clone the
template once per network segment.

`confettictl-install.sh` and the two `confettictl-build-template.sh` scripts do all the package,
service and file setup. This guide covers what they can't: the VM itself,
the Alpine install, and configuring the clones.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Create the base VM](#2-create-the-base-vm)
3. [Install Alpine](#3-install-alpine)
4. [Build the hub and the node template](#4-build-the-hub-and-the-node-template)
5. [Deploy nodes](#5-deploy-nodes)
6. [Ongoing operation](#6-ongoing-operation)
7. [Troubleshooting](#7-troubleshooting)
8. [No GitHub access](#8-no-github-access)

---

## 1. Prerequisites

- vCenter / ESXi access to create VMs, templates and port groups
- The Alpine **Virtual** ISO (`alpine-virt-<version>-x86_64.iso`) from
  [alpinelinux.org/downloads](https://alpinelinux.org/downloads/)
- A hub subnet that every node subnet can reach, and the hub's static IP
- A port group per node subnet
- Internet access from each VM while it is built (Alpine mirror, GitHub)
- Console access to the VMs (vCenter web console or VMRC)

---

## 2. Create the base VM

| Setting | Value |
|---|---|
| Guest OS | Linux, Other 5.x or later Linux (64-bit) |
| vCPU | 1 |
| RAM | 256 MB |
| Disk | 2 GB, thin provisioned |
| NIC | VMXNET3, on a network with DHCP |
| SCSI controller | VMware Paravirtual |

If your vCenter has no "Other 5.x or later" option, pick "Other Linux
(64-bit)". vCenter then warns that Paravirtual is "not recommended". Ignore
it: Alpine's kernel has the driver. LSI Logic Parallel also works.

256 MB fits either role. After cloning you can drop nodes to 128 MB and the
hub to 192 MB.

---

## 3. Install Alpine

Boot the ISO, log in as `root` (no password) and run `setup-alpine`:

| Prompt | Answer |
|---|---|
| Keyboard layout | your layout |
| Hostname | `confetti` (each clone renames itself) |
| Network interface | `eth0`, `dhcp` |
| Root password | anything; the build sets it to `confetti` (see below) |
| Timezone | `UTC` or your lab's timezone |
| Proxy | `none`, unless your lab needs one |
| NTP client | `chrony` |
| Mirror | `f` (fastest) |
| SSH server | `dropbear` |
| Disk | `sda`, mode `sys`, erase `y` |

`sys` installs to disk. The other modes run from RAM.

Reboot, disconnect the ISO in vCenter, log in and check the network:

```sh
ip addr show eth0
ping -c 2 alpinelinux.org
```

The build scripts set the root password to `confetti`. To use your own, run
the build with `CONFETTI_ROOT_PASSWORD=<password>` set.

Now clone the VM twice (hub and node template).

---

## 4. Build the hub and the node template

On each clone, run as root:

```sh
wget -O /tmp/oi.sh https://github.com/orneh24/confetti-traffic/raw/main/online-install.sh && sh /tmp/oi.sh
```

`online-install.sh` downloads the repo to `/root/confetti` and runs
`confettictl-install.sh` from it.

Pick **hub** on one clone and **node** on the other. For the node, the
installer asks for the hub URL (e.g. `http://10.0.0.100`) and stores it in
the template as `/etc/confetti/template-hub-url`, so clones ask only for the
group. Leave it blank to be asked on each clone, or set `CONFETTI_HUB_URL`
for an unattended build. Guestinfo and the environment still override it. The build enables the
community repository, installs packages, installs the services and cleans
the VM for cloning. It takes a few minutes; zeroing free space at the end is
the slow part.

Some package choices matter (for example, `iputils-ping` instead of
BusyBox ping, which the PMTU test needs). `CLAUDE.md` constraint 14 explains
them. `node/confettictl-build-template.sh` checks the important ones and warns if they
are wrong.

### 4.1 Hub

When the build finishes, `confettictl-install.sh` runs `confettictl-hub-setup.sh` (or log out and back in if you skipped it). It asks for the static IP and gateway, plus
an optional DNS server and hostname. Then it restarts networking and starts
the hub. Type the IP with its prefix (e.g. `10.0.0.100/24`); the gateway
then defaults to the subnet's first address (`10.0.0.1`), and you can type
another one instead. Give it a DNS server if you can: without one the hub can't resolve
names, so `confettictl-update` can't download. To do it by hand instead:

```sh
confettictl-set-static-ip <hub-ip>/<cidr> <gateway> [dns] [hostname]
rc-service networking restart
rc-service confettid-hub start
```

Or set `guestinfo.hub.ip` (e.g. `10.0.0.100/24`) and `guestinfo.hub.gateway`
on the VM, plus optionally `guestinfo.hub.dns` and `guestinfo.hub.hostname`,
and reboot. The `confettid-hub-firstboot` service applies them. It uses the
network keys only once, but re-reads `guestinfo.hub.hostname` on every boot:
to rename the hub later, change that key and reboot.

Open `http://<hub-ip>/` to check. Settings live in
`/opt/confetti-hub/hub.env`; restart the hub after editing it.

A lab normally has one hub, so you don't need to make it a template.

### 4.2 Node template

The build leaves the node clean: no config, hostname `confetti-template`,
no SSH host keys, no login stamp. Shut it down and convert it to a template:

```sh
rm -rf /root/confetti   # optional
poweroff
```

Name the template something like `confetti-node-template-v1`.

**Don't run `confettictl-setup.sh` or answer the login prompt on the template.** That
writes a config, hostname, SSH host keys and login stamp, and every clone
would inherit them. Test on the first clone instead.

---

## 5. Deploy nodes

### 5.1 Clone and connect

1. Clone the template.
2. Before booting, set the NIC to the port group of the segment this node
   tests. The node needs DHCP on that segment.
3. Optional: lower RAM to 128 MB.

### 5.2 Configure: guestinfo (recommended)

Set the keys on the VM before first boot. On boot, the
`confettid-firstboot` service runs `confettictl-setup.sh` with them, and the node
configures and registers itself with no console session.

The keys are listed in the [README](../README.md#vmware-guestinfo-keys-optional).
Only `hub_url` and `group` are required. In the vSphere Client: VM →
**Edit Settings** → **VM Options** → **Advanced** → **Edit Configuration** →
add one row per key.

With PowerCLI:

```powershell
$vm = Get-VM "ct-site-a"
$vm | New-AdvancedSetting -Name guestinfo.confetti.hub_url -Value "http://10.0.0.100" -Confirm:$false
$vm | New-AdvancedSetting -Name guestinfo.confetti.group   -Value "site-a"            -Confirm:$false
```

To change a key later, use `Get-AdvancedSetting | Set-AdvancedSetting`;
`New-AdvancedSetting` fails if the key exists. Then reboot the node: at boot,
`confettid-firstboot` compares the keys with `/etc/confetti/config` and, if any
differ, re-runs `confettictl-setup.sh`. A new `group` renames the node (`ct-<group>-<ab1234>`),
and the old name is removed from the hub. To deploy a whole lab at once,
use `deploy/Deploy-Confetti.ps1` (see `deploy/README.md`).

With govc:

```sh
govc vm.change -vm ct-site-a \
  -e guestinfo.confetti.hub_url=http://10.0.0.100 \
  -e guestinfo.confetti.group=site-a
```

To check from inside the guest: `vmware-rpctool "info-get guestinfo.confetti.group"`.
`No value found` just means the key isn't set.

The first-boot service logs to `/var/log/confetti/firstboot.log`. With no
keys set it does nothing, and the login prompt takes over. To run it again:

```sh
rm /etc/confetti/.firstboot-done /etc/confetti/.setup-done /etc/confetti/config
rc-service confettid-firstboot start
```

### 5.3 Configure: at login

Boot the clone and log in. `confettictl-node-setup.sh` asks
`Configure this node now? [Y/n]` and runs `confettictl-setup.sh`, which asks for anything
not already set. You can also run `/usr/local/bin/confetti/confettictl-setup.sh`
yourself at any time.

The prompt appears only in an interactive login on a real terminal, never
for `ssh host cmd` or scp. If you decline, you can choose not to be asked
again; `confettictl-node-setup.sh --force` asks again later.

Each value comes from guestinfo first, then an environment variable, then a
prompt. `SUBNET` is taken from the DHCP lease before prompting. The hostname
is `ct-<group>-<ab1234>` (e.g. `ct-site-a-xd2311`) unless you set one. The
random part is generated once and kept in the config as `NODE_ID`, so the
name never changes on reboot or a new DHCP lease.

### 5.4 What `confettictl-setup.sh` does

It writes `/etc/confetti/config`, sets the hostname, starts the services,
adds the cron jobs (every 60 s for tests, every 5 min for registration),
fetches the SSH keys from the hub and registers with the hub. It is safe to
re-run: it keeps an existing config.

**SSH keys from the hub** (`confettictl-trust-hub.sh`):

- The mesh test key is used by every node's SSH test. The node trusts it only
  to run `echo ok`, so it's harmless even though it travels over plain HTTP.
- The hub's management key lets the hub log in as root to push updates. It
  is pinned the first time, and never replaced automatically after that. If
  the hub is rebuilt, `register.log` warns that the key changed. Run
  `confettictl-trust-hub` on the node to trust the new one, after checking the
  fingerprint it shows against the hub's
  (`ssh-keygen -lf /etc/confetti-hub/keys/id_hub.pub` on the hub).

`HUB_MANAGED=false` in the config removes the management key, and the hub
then won't push to that node.

**Time from the hub.** Setup writes the node's `/etc/chrony/chrony.conf` with
the hub (taken from `HUB_URL`) as its only time server. The hub serves NTP on
UDP/123, and with no internet it serves its own clock, so the whole lab still
agrees on one time. Each node reports its sync state when it registers, shown
under its name on the dashboard. `HUB_NTP=false` in the config leaves
`chrony.conf` alone. Both builds also pin IP forwarding off
(`/etc/sysctl.d/99-confetti.conf`).

### 5.5 Alternative: install a node straight from the hub

No template and no GitHub needed. On a plain Alpine VM (after
`setup-alpine`), as root:

```sh
wget -O /tmp/i.sh http://<hub-ip>/install.sh && sh /tmp/i.sh [group]
```

It downloads the node bundle from the hub, installs the packages and scripts,
and runs `confettictl-setup.sh` with the hub URL already filled in. It asks only for what
is still missing, such as the group if you didn't pass it. Don't pipe it into
`sh`, because the prompts need the terminal.

### 5.6 Check

The node appears on the dashboard within seconds, and results within a
minute. On the node:

```sh
hostname                                   # e.g. ct-site-a-xd2311
confettictl-status                                # last cycle's results (-f to follow)
tail -f /var/log/confetti/test-cycle.log
```

---

## 6. Ongoing operation

### 6.1 Test types

| Label | Test | Runs |
|---|---|---|
| H | HTTP fetch of the probe site (5 files, checked byte for byte); static targets: `/` answers | always |
| S | SSH login with the mesh key from the hub (runs `echo ok` only) | always |
| T | traceroute | every `TRACEROUTE_INTERVAL` (300 s), and right after H or S fails |
| M | path MTU, DF bit set | always |
| D | DNS lookup of `DNS_QUERY` | when `DNS_SERVER` is set |
| I | iperf3 throughput | when `ENABLE_IPERF=true` |
| B | SMB download of a probe file | when `ENABLE_SMB=true` |
| L | packet loss and jitter (`fping`) | always |
| E | SMTP conversation, never sends mail | mesh: when `ENABLE_SMTP=true`; static targets: always |

**H (HTTP)** fetches a small fixed website every node serves at
`http://<node>/probe/`, in the order a browser would: `index.html`,
`style.css`, `app.js`, `about.html`, then the large `report.html` (about
57 KB). Each file must answer 200 and match the node's own copy byte for
byte. The output names the first file that failed:
- `content changed (30000 of 57653 bytes)` means the page was cut short, or
  something on the path rewrote it.
- `HTTP 404` on `index.html` usually means the peer runs an older build
  without the site. Push the current build to it.

A node whose own build has no probe site yet falls back to checking that `/`
answers. Don't edit the probe files on a single node: every peer would then
fail against it.

**M (path MTU)** sends a full-size packet (1472-byte payload, 1500 total)
with DF set. Every other test uses small packets, so a tunnel that drops
large packets looks green everywhere else. On failure it steps down through
smaller sizes and reports, for example,
`PMTU below 1500; largest passing 1428 bytes`. If nothing gets through at
any size, it reports `path down, not an MTU issue`.

**E (SMTP)** catches a firewall that *rewrites* traffic instead of blocking
it. SMTP inspection engines replace capability words they don't know with
`X`s, so `250-XXXXXXXX` in the output means something is editing the
session. The test passes on the greeting and `EHLO` reply only; a real relay
rejecting the probe address with `550` is normal. See `CLAUDE.md`
constraint 21 for why this can never send mail.

**T (traceroute)** runs rarely because a dead path is slow to trace. It
uses one probe per hop and at most 10 hops, so it can't overrun the
60-second cycle when the network breaks.

**Bandwidth on demand.** The dashboard's **Bandwidth Test** panel measures
throughput when you ask. It isn't part of the minute-by-minute tests. Like
Static Targets and Mesh Settings, it starts folded: press **Expand**, and
the dashboard remembers that in your browser.

- **Two nodes:** pick From and To, a duration (5–30 s) and 1–8 TCP streams.
  The hub runs `iperf3` on both nodes over SSH: From sends, then To sends.
  Both nodes must be managed by the hub.
- **A node and this browser:** pick a node. Your browser downloads from it,
  then uploads to it, directly rather than through the hub. Your PC must be
  able to reach the node's IP address.
- **Limits:** one test at a time across the whole mesh, and a second request
  is refused until the first finishes. A test saturates the path for its
  duration in each direction, so avoid running it on a busy production link.
- **Results:** every run is listed under the panel (the last 200), with
  Mbit/s for each direction. Hover over a failed run to see why it failed.

**Mesh rules.** By default every node tests every other node. The
**Mesh Rules** part of the dashboard's Mesh Settings panel excludes pairs of groups: type or pick two
groups and press add. Nodes in those groups stop testing each other, both
ways and for every test, from their next cycle (about a minute). The same
group twice stops nodes in one group testing each other. An excluded pair
shows as a muted dot in the matrix and isn't counted as passing or failing.
Static targets are not affected. Remove the rule to go back to full mesh.

**Flapping and groups.** A matrix cell with a dashed outline has flipped
between pass and fail 5 or more times in the last hour (Modern layout: the
"Flapping (1 h)" tile lists them). The node's console table and
`confettictl-status` show the same as a `~` after the H, S, M or L cell, with
a footer note (counted over the last 60 cycles). Recent Changes has a
**Pair** button that cycles name / IP / name + IP. In the Endpoints list,
click a node's group to set its group on the hub (empty clears it): it beats
the group the node reports, mesh rules follow it, and the node itself is not
changed. An overridden group shows a pencil mark and appears under the IP in
the matrix headers.

**Colour themes.** The menu at the right of each page's header picks one of
eight themes: Dark, Light, Dracula, Monokai (military green), High
Contrast, Terminal green, Confetti Night and Neon Streamers. **Shuffle**
changes to a different theme every 5–10 minutes, with a confetti rain each time. The choice is saved in your
browser and shared by all three pages. Every theme has confetti in its
header in its own colours, except Neon Streamers, which has glowing streaks.

**Layouts.** On the dashboard, a second menu beside the theme picks the
layout. **Classic** is the original. **Modern** adds a menu down the left
side, summary tiles along the top (failing paths, tests passing, endpoints,
path changes, hub state) and rounded panels in two columns; Test Detail opens
on the right when you click a matrix cell. Modern uses whichever colour
theme you pick. **Retro 95** turns every panel into a Windows 95 window on a
teal desktop, with a taskbar and a Start menu (which also holds **Is it
DNS..?**, **Confetti!** and a way back to Classic). It has its own colours,
so the theme menu is greyed out while it's on. **Amber CRT** is an amber
terminal screen with scanlines. It also has its own colours; a failing test
shows as an inverted block so it stands out without a second colour. The
Syslog and Timeline pages have one layout.

### 6.2 Static targets

Addresses with no agent (a gateway, a loopback, an outside host). Add them
once on the hub; every node tests them from its next cycle. List only the
tests the target can answer.

```sh
curl -X POST http://<hub-ip>/targets -H 'Content-Type: application/json' \
  -d '{"name":"gw-a","ip":"10.1.1.1","tests":["traceroute","pmtu"],"note":"site-a gateway"}'
curl -s http://<hub-ip>/targets
curl -X DELETE http://<hub-ip>/targets/gw-a
```

Test names: `http ssh traceroute pmtu dns iperf3 smb loss smtp`. An unknown
name gets a 400.

### 6.3 Updating

**1. The hub, from GitHub.** Run as root on the hub:

```sh
confettictl-update          # asks before changing anything; -y skips that
```

It downloads the repo, shows the installed and new commit, and runs the
build again in `--update` mode: new packages, new code and service files,
with none of the build's cleanup. It keeps `hub.env`, the database, the
hub's SSH keys and the root password, then restarts the hub. It also
rebuilds the node bundle the hub serves at `/node/bundle.tar.gz`.
A hub update overwrites any hand edits in `/opt/confetti-hub/agent/`.

**2. The nodes, from the hub.** On the dashboard, use the update button on a
node's row, or **update all** in the endpoints header. The hub logs in to
each node with its management key, one at a time, and runs
`confettictl-update -y`. The node downloads the bundle from the hub, never from
GitHub, and then re-runs `confettictl-setup.sh`. That registers with the hub, so you see
straight away whether the new `confettictl-register.sh` works.

- **Build:** the small line under each node's name shows the commit it runs.
  It is yellow when the node differs from what the hub serves.
- **Status mark:** after a push, a mark shows the result. Hover over it for
  the output.
- **Skipped nodes:** a node is skipped if it has `HUB_MANAGED=false`, hasn't
  registered in the last 10 minutes, or is already updating.
- **Never automate it:** push by hand only, never on a schedule
  (constraint 13 in CLAUDE.md).

`confettictl-update` run by hand on a node does the same download from its hub.
`cat /etc/confetti-release` shows the commit a VM is on.

The dashboard's push buttons have no password yet: anyone who can reach the
dashboard can push. Keep the hub on a management segment.

The hub's download needs DNS and a route to GitHub. A hub set up without a DNS
server has an empty `/etc/resolv.conf` (the build clears it). This includes
hubs set up before `confettictl-hub-setup.sh` asked for one. Add one first:
`echo 'nameserver <dns-ip>' > /etc/resolv.conf`. No GitHub access at all:
see §8.

Don't update the node *template* in place. Booting it creates SSH host keys
that every later clone would share; rebuild it instead (§4).

**Only `confettictl-test-cycle.sh`, between updates.** The hub serves `confettictl-test-cycle.sh`
from `/opt/confetti-hub/agent/`. Edit it there, and every node picks it up
at its next registration (within 5 minutes). A node only accepts the new
version if its checksum matches, it passes `sh -n`, and a real test cycle
succeeds. Otherwise it keeps the old one. Watch
`/var/log/confetti/register.log`. To stop a node updating, set
`AGENT_AUTOUPDATE=false` in its config.

Only `confettictl-test-cycle.sh` updates itself. `confettictl-register.sh`, `confettictl-setup.sh` and
`confettictl-status.sh` change only through `confettictl-update`, run by hand
(`CLAUDE.md` constraint 13).

> **The hub API has no authentication.** Anyone who can reach it can post
> results, add targets or change the script every node runs. Keep the hub on
> an isolated lab network.

### 6.4 Syslog

Point devices at `<hub-ip>`, UDP 514, RFC3164. For example (syntax varies by
vendor):

```
logging host <hub-ip>
logging trap informational
service timestamps log datetime msec show-timezone
```

To test from the hub itself (BusyBox `logger` can't send to the network):

```sh
python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'<190>1: SW-TEST: %SYS-5-CONFIG_I: hello from the hub', ('127.0.0.1', 514))"
curl -s 'http://localhost/api/syslog?minutes=5'
```

You should get one row with host `SW-TEST`. If `/var/log/confetti-hub.log`
doesn't show `[syslog] listening on ...:514`, the port was taken or the hub
isn't running as root. The hub keeps collecting results either way.

On `http://<hub-ip>/syslog` you can filter by time, sender, severity and
text. `severity=4` means warning or worse. Lines the hub couldn't parse have
no severity and always show.

The header shows the hub clock's state: green when synced, amber when
running on its own clock or >100 ms off, red when unsynced. The ±5 min
links from the dashboard depend on this clock.

On the dashboard, each test result links to syslog from ±5 min around it,
and each pair has links filtered by group. Those filter on the hostname the
device puts in its messages. If a group link is empty but the plain link
shows the message, the device logs under a different name than the group.

When a pair is failing, its detail panel also shows **Related events**: what
the devices in the pair's groups logged within 5 minutes of when the pair
started failing, plus any traceroute path change. **Copy summary** copies a
plain-text summary of the pair (each test, the path change, related syslog,
times in UTC and links back), ready to paste into a ticket.

Keep in mind:

- UDP syslog is lossy and anyone on the network can fake it. Use it for
  troubleshooting, not as an audit trail.
- It is capped at `HUB_SYSLOG_MAX_ROWS` (300000) rows. A chatty device
  shortens the history. An optional age limit, `HUB_SYSLOG_RETENTION_HOURS`
  in `hub.env` (0 = off), also applies.
- `HUB_SYSLOG_ENABLED=false` in `hub.env` turns it off.

---

## 7. Troubleshooting

### Node can't reach the hub

```sh
ip addr show eth0
ip route
ping -c 2 <gateway-ip>
ping -c 2 <hub-ip>
curl -v http://<hub-ip>/ 2>&1 | head -20
```

Usual causes: wrong port group, no route between the subnets, or the hub
isn't running (`rc-service confettid-hub status` on the hub).

### No DHCP address

```sh
udhcpc -i eth0
cat /etc/network/interfaces
```

Usual causes: no DHCP pool on the subnet, or wrong port group. If the subnet
really has no DHCP, run `confettictl-setup.sh` at the console: it asks for a static IP (with its prefix), and
offers the subnet's first address as the gateway.
The zero-touch path can't ask, so it leaves the node unconfigured.

### Tests failing

Run a cycle by hand, or test one service against a peer:

```sh
/usr/local/bin/confetti/confettictl-test-cycle.sh
curl -s http://<peer-ip>/
ssh -i /etc/confetti/id_confetti root@<peer-ip> echo ok
iperf3 -c <peer-ip> -t 2
smbclient -N //<peer-ip>/labshare -c 'get probe.bin /dev/null'
fping -c 5 <peer-ip>
nc <peer-ip> 25          # wait for the 220 line, then type EHLO test, then QUIT
traceroute <peer-ip>
```

A pair with no results at all may be excluded on purpose: check the Mesh
Rules panel (or `curl http://<hub>/mesh-rules`).

Usual causes: the service isn't running on the peer (dropbear,
`confettid-httpd`, `iperf3`, `confettid-smbd`, `confettid-smtpd`), or a
firewall on the path blocks the port. If only SSH fails everywhere, check
that the node has the mesh key (`ls /etc/confetti/id_confetti`). It comes
from the hub at setup, and `confettictl-register.sh` retries every 5 minutes if the hub
was down.

### Push-update fails

Hover over the red mark next to the node's build (under its name on the
dashboard) to see the output.
"SSH ... failed" usually means the node hasn't pinned this hub's key:

- On the node: `ls /etc/confetti/hub_key.pub`, and look for key warnings in
  `/var/log/confetti/register.log`.
- To trust the hub's current key: `confettictl-trust-hub` on the node.

### Dashboard doesn't load

On the hub:

```sh
rc-service confettid-hub status
tail -50 /var/log/confetti-hub.log
netstat -tlnp | grep ':80 '
```

To see startup errors directly, stop the service and run it in the
foreground: `rc-service confettid-hub stop; cd /opt/confetti-hub && sh confettictl-run.sh`.

If the log warns that waitress is missing, the hub fell back to Flask's
single-threaded server and will be slow. Install it with
`apk add py3-waitress`.

### Services not running after a clone

```sh
rc-update show default
rc-status -a
rc default          # start everything in the default runlevel
```

OpenRC service errors go to `/var/log/messages`.

### Alpine basics

- The shell is BusyBox `ash`, not bash.
- Packages: `apk update`, `apk add <pkg>`, `apk del <pkg>`, `apk search <term>`.
- Services: `rc-service <svc> start|stop|restart|status`,
  `rc-update add|del <svc> default`.

---

## 8. No GitHub access

If a VM can reach the Alpine mirror but not GitHub, copy the repo over with
scp instead of the download command.

A fresh Alpine install with dropbear has no `scp` binary, so install one on
the VM first:

```sh
apk add --no-cache openssh-client-default
```

Then copy from your workstation with `scp -O`. The `-O` matters: modern scp
uses SFTP by default, and dropbear has no SFTP server.

```sh
scp -O -r confetti root@<vm-ip>:/root/
```

Then run `sh /root/confetti/confettictl-install.sh` on the VM.

To update an installed VM the same way, copy the repo over and run
`sh /root/confetti/confettictl-update.sh`. It uses the copy instead of downloading.
Remove any older `/root/confetti` first, or scp puts the new copy inside it.
