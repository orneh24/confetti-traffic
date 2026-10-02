# Confetti Traffic

> **AI disclaimer:** This project was created using [Claude Code](https://claude.com/claude-code).

End-to-end connectivity testing between nodes on a network. It goes beyond
ICMP: it makes real TCP connections (HTTP, SSH, SMB, SMTP, iperf3) and
measures packet loss/jitter, path MTU, DNS and traceroute. Results show on a
web dashboard, optionally next to syslog from the network devices on the path.
A Timeline page groups failures, route changes, syslog and bandwidth tests into incidents, and a slider replays the mesh at any earlier moment (1 hour, 6 hours or 24 hours back).

![Dashboard with a synthetic 5-node mesh, one failing path selected, and its syslog correlation panel open](docs/img/dashboard-mock.jpg)

*Mock data from a synthetic 5-node mesh, not a real lab. See
[Running the hub locally](#running-the-hub-locally).*

![Animated tour of the hub's Dashboard, Syslog and Timeline pages](docs/img/hub-pages.gif)

*The three hub pages: Dashboard, Syslog and Timeline, then the dashboard in
the Confetti Night theme. Mock data from a synthetic 6-node mesh.*

## Tests

Every node tests every other node once a minute and reports to the hub. Each
matrix cell shows one letter per test: green passed, yellow slow, red failed,
grey no data; a muted dot means a mesh rule excludes the pair.

| | Test | What it checks | Runs |
|---|---|---|---|
| H | HTTP | Fetches a fixed 5-file site and checks every byte (catches rewriting) | always |
| S | SSH | Key login running `echo ok` | always |
| M | Path MTU | 1500-byte DF packet; steps down on failure | always |
| L | Loss | Loss and jitter (`fping`); only 100% loss fails | always |
| T | Traceroute | Hop path; hub flags path changes | 5 min, and after H/S fails |
| D | DNS | Name lookup on a given server | `DNS_SERVER` set |
| I | iperf3 | TCP throughput | enabled |
| B | SMB | 8 MB file download (sustained transfer) | enabled |
| E | SMTP | Mail conversation, never sends; shows command rewriting | enabled |

- **Enabled** tests: per node in its config, or mesh-wide in Mesh Settings.
- **Mesh Rules** exclude group pairs (both ways, all tests); the same group
  twice stops a group testing itself.
- **Static targets** (gateways, loopbacks, outside hosts) are added once on
  the hub, with the tests that apply, and every node tests them.
- **Bandwidth on demand:** node to node (`iperf3`, 1–8 streams) or node to
  your browser, both directions.

Details: [BUILD_GUIDE §6.1](docs/BUILD_GUIDE.md#61-test-types).

## Quick start

Two parts: install the hub first, then add nodes. To build it yourself step
by step instead, see [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md).

### 1. Install the hub

1. **Base VM.** Install Alpine on a new VM (`setup-alpine`). Put it on a
   segment that every node subnet and your workstation can reach.
2. **Run the installer** as root. It downloads the repo and starts
   `confettictl-install.sh`, which asks whether the VM becomes a hub or a node. Pick
   *hub*:

   ```sh
   wget -O- https://github.com/orneh24/confetti-traffic/archive/refs/heads/main.tar.gz | tar -xz -C /root && mv /root/confetti-traffic-main /root/confetti && sh /root/confetti/confettictl-install.sh
   ```

3. **Configure the network.** Log out and back in. Login script will prompt for config

   ```sh
   confettictl-set-static-ip <hub-ip>/<cidr> <gateway> [dns] [hostname]
   rc-service networking restart
   rc-service confettid-hub start
   ```

   Or set `guestinfo.hub.ip`, `guestinfo.hub.gateway` (and optionally
   `guestinfo.hub.dns`, `guestinfo.hub.hostname`) on the VM in vCenter
   before first boot, and the hub configures itself.
4. **Check** that `http://<hub-ip>/` loads.

### 2. Add nodes

There are two ways. Both give the same result: a node that registers with the
hub and shows up at `http://<hub-ip>/endpoints`. The hostname is set
automatically (`ct-<group>-<ab1234>`, e.g. `ct-site-a-xd2311`).

**Option A: straight from the hub (one line).** On a plain Alpine VM with
network access to the hub, as root. No template, no GitHub access needed:

```sh
wget -O /tmp/i.sh http://<hub-ip>/install.sh && sh /tmp/i.sh [group]
```

It downloads the node bundle from the hub, installs it, and asks for the
group if you did not pass one. Good for a few nodes, or where a VM can't be
cloned.

**Option B: vCenter template and guestinfo.** Best for many nodes.

1. On a second Alpine VM, run the same installer as in part 1 and pick
   *node*. The build cleans the VM for cloning when it finishes.
2. Shut it down and convert it to a vCenter template. Don't configure or test
   it first: that undoes the cleanup. Test on the first clone instead.
3. Clone the template once per network segment and put each clone on its
   segment's port group.
4. Before first boot, set `guestinfo.confetti.hub_url` and
   `guestinfo.confetti.group` on each clone (all keys are listed under
   [VMware guestinfo keys](#vmware-guestinfo-keys)). It then configures
   itself. Without them, log in and answer the `confettictl-node-setup.sh` prompt.

Every node fetches its SSH keys from the hub at setup. The hub's management
key is trusted on first use and lets the hub push updates from the dashboard.
Set `HUB_MANAGED=false` in a node's config to opt it out.

`confettictl-install.sh` refuses to run on a VM that is already a hub or node, because
re-running a build wipes its config or the hub's database. Pass `hub` or
`node` to skip the menu, and `-y` to skip the confirmation.

**Single VM, no cloning.** Run the installer on a fresh Alpine VM, then
finish in place: for a hub, step 3 above; for a node, log out and back in and
answer the `confettictl-node-setup.sh` prompt (or run `/usr/local/bin/confetti/confettictl-setup.sh`).
Ignore the node build's "convert to template" message. Fresh VM only: an
existing `/root/confetti` makes the `mv` put the new copy inside it.

### Updating

Update the hub first: run `confettictl-update` on it as root. It downloads the
latest code from GitHub, asks before changing anything, and keeps hub.env,
the database and the root password. It also rebuilds the node bundle the hub
serves.

Then update the nodes from the dashboard: the update button on a node's
row, or **update all**. The hub runs `confettictl-update` on each node over SSH,
one at a time, and the node downloads the new code from the hub. Each node's
build shows under its name, in yellow when it differs from what the hub
serves.
`confettictl-update` run on a node by hand does the same thing.

Details: [BUILD_GUIDE §6.3](docs/BUILD_GUIDE.md#63-updating).

### VMware guestinfo keys

Set these on the VM in vCenter (VM Options → Advanced → Configuration
Parameters, or PowerCLI `New-AdvancedSetting`) before first boot. Only the
two marked keys are required. All keys start with `guestinfo.`

| Key | Example | Notes |
|---|---|---|
| `confetti.hub_url` | `http://10.0.0.100` | **required** |
| `confetti.group` | `site-a` | **required**; groups nodes on the dashboard |
| `confetti.subnet` | `10.1.1.0/24` | default: from DHCP lease |
| `confetti.hostname` | `ct-site-a` | default: `ct-<group>-<ab1234>`; must be unique |
| `confetti.dns_server` | `10.0.0.53` | unset skips the DNS test |
| `confetti.dns_query` | `example.com` | name the DNS test looks up |
| `hub.ip` | `10.0.0.100/24` | unset: asked at login |
| `hub.gateway` | `10.0.0.1` | |
| `hub.dns` | `10.0.0.53` | needed for `confettictl-update` |
| `hub.hostname` | `confetti-hub` | re-read every boot |

`confetti.*` keys go on nodes, `hub.*` keys on the hub.

More: [`docs/QUICKSTART.md`](docs/QUICKSTART.md) (reference tables) and
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) (checklist with verification).

## What it tests

| Type | Label | Runs against |
|---|---|---|
| HTTP | H | every node pair, static targets |
| SSH | S | every node pair, static targets |
| Traceroute | T | every 5 min, and right after an HTTP or SSH failure |
| Path MTU | M | every node pair, static targets; catches paths that pass small packets but hang on large ones |
| DNS | D | one resolver per node, when `DNS_SERVER` is set |
| iperf3 | I | every node pair, when `ENABLE_IPERF=true` |
| SMB | B | every node pair, when `ENABLE_SMB=true` |
| Loss/jitter | L | every node pair, always on (`fping`) |
| SMTP | E | every node pair when `ENABLE_SMTP=true`, and static targets that list it; catches firewalls that rewrite SMTP instead of blocking it |

**Static targets** are addresses with no agent (gateways, loopbacks, outside
hosts). You add them once on the hub and every node tests them.

**Syslog correlation** is optional. The hub accepts RFC3164 syslog on
UDP/514. Each test result on the dashboard links to the syslog from ±5
minutes around it.

## Architecture

- **Hub**: Alpine VM, ~192 MB RAM. Collects and shows results; never tests.
  Flask + SQLite, served by waitress, with a syslog receiver and a Hub Health
  panel.
- **Nodes**: Alpine VMs, ~128 MB RAM, one per network segment. Cloned from
  one template. Cron runs the tests every 60 s and pushes results to the hub.
- **Names on the VMs**: OpenRC services start with `confettid-`
  (`confettid-hub` on the hub; `confettid-httpd`, `-smbd`, `-smtpd`,
  `-iperf3` on nodes). Scripts and commands start with `confettictl-`
  (`confettictl-update`, `confettictl-status`, `confettictl-trust-hub`).
  Everything else uses `confetti`: `/opt/confetti-hub`, `/etc/confetti`,
  `guestinfo.confetti.*`.

Full design and the constraints that must not regress:
[`CLAUDE.md`](CLAUDE.md). Open items and roadmap:
[`docs/ROADMAP.md`](docs/ROADMAP.md).

### Other hypervisors

Built and tested on vSphere, but any hypervisor that runs Alpine should work
(Proxmox/KVM, Hyper-V, VirtualBox, bare metal).

### Why not Docker?

The project measures a real network path. Containers on one host share a
kernel and a virtual bridge, so traffic never crosses the switches,
firewalls and tunnels the tests exist to check. PMTU, SMTP inspection and
loss would all pass trivially and prove nothing.

Docker has one narrow use here: the `golden-image-verifier` agent uses an
Alpine container to check package installs and daemon startup. For local work
without VMs, see [`dev/README.md`](dev/README.md): it runs the real scripts
against a real hub, with the network tools faked.

## Running the hub locally

```sh
cd hub
HUB_DB_PATH=/tmp/hub.db HUB_PORT=8099 HUB_SYSLOG_PORT=5514 python3 serve.py
```

Use `serve.py`, not `flask run`: it reads `HUB_PORT` and starts the syslog
listener. Ports below 1024 need root, hence the high ports.

## Docs

| File | Covers |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Reference: ports, files, config keys, admin commands |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Build order and checklist, with verification |
| [`docs/TOPOLOGY.md`](docs/TOPOLOGY.md) | System diagram |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Not yet built, not yet verified, decided against |
| [`CLAUDE.md`](CLAUDE.md) | Architecture, design decisions, constraints |
| [`dev/README.md`](dev/README.md) | Local hub and simulated mesh, no VMs |
| [`deploy/README.md`](deploy/README.md) | PowerCLI script to deploy a hub and N nodes |
