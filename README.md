# Confetti Traffic

> **AI disclaimer:** This project was created using [Claude Code](https://claude.com/claude-code) for training/labbing purposes - use freely, but at own risk :-)

**Menu**

- [Tests](#tests)
- [Quick start](#quick-start)
  - [Install the hub](#1-install-the-hub)
  - [Add nodes](#2-add-nodes)
  - [Updating](#updating)
- [Advanced deployment](#advanced-deployment)
  - [Zero-touch deployment with guestinfo](#zero-touch-deployment-with-guestinfo)
  - [Install notes](#install-notes)
- [Architecture](#architecture)
  - [Other hypervisors](#other-hypervisors)
  - [Why not Docker?](#why-not-docker)
- [Running the hub locally](#running-the-hub-locally)
- [Docs](#docs)

End-to-end connectivity testing between nodes on a network. It goes beyond
ICMP: it makes real TCP connections (HTTP, SSH, SMB, SMTP, iperf3) and
measures packet loss/jitter, path MTU, DNS and traceroute. Results show on a
web dashboard, optionally next to syslog from the network devices on the path.
A Timeline page groups failures, route changes, syslog and bandwidth tests into incidents, and a slider replays the mesh at any earlier moment (1 hour, 6 hours or 24 hours back).

![Animated tour of the hub's Dashboard, Syslog and Timeline pages](docs/img/hub-pages.gif)

*The three hub pages: Dashboard, Syslog and Timeline, then the dashboard in
the Confetti Night theme. Mock data from a synthetic 6-node mesh, not a real
lab. See [Running the hub locally](#running-the-hub-locally).*

## Tests

Every node tests every other node once a minute. Each matrix cell shows one
letter per test: green pass, yellow slow, red fail, grey no data. A dashed outline means
flapping (5+ pass/fail flips in the last hour).

| Test | Checks | Runs |
|---|---|---|
| **H** HTTP | 5-file site, byte for byte | always |
| **S** SSH | key login | always |
| **M** Path MTU | 1500-byte DF packet | always |
| **L** Loss | loss and jitter | always |
| **T** Traceroute | hop path changes | 5 min, and after H/S fails |
| **D** DNS | name lookup | `DNS_SERVER` set |
| **I** iperf3 | TCP throughput | opt-in |
| **B** SMB | 8 MB download | opt-in |
| **E** SMTP | mail rewriting (never sends) | opt-in |

Static targets (gateways, loopbacks, outside hosts) get the tests that apply
to them. Optional syslog from network devices (UDP/514) is linked from each
result, and a failing pair lists what the devices logged.

Opt-in tests, mesh rules, static targets and on-demand bandwidth tests:
[BUILD_GUIDE §6](docs/BUILD_GUIDE.md#6-ongoing-operation).

## Quick start

Install the hub first, then add nodes. Step-by-step detail:
[`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md).

### 1. Install the hub

1. Install Alpine on a new VM (`setup-alpine`), on a segment that every node
   subnet and your workstation can reach.
2. As root, run the installer and pick *hub*:

   ```sh
   wget -O /tmp/oi.sh https://github.com/orneh24/confetti-traffic/raw/main/online-install.sh && sh /tmp/oi.sh
   ```

3. When it offers to set the static IP, answer yes and give the IP with its
   prefix, the gateway, and optionally a DNS server and hostname. Skipped it?
   It asks again at your next login. Ignore the "convert to template"
   message at the end.
4. Check that `http://<hub-ip>/` loads.

### 2. Add nodes

**A few nodes: install straight from the hub.** On a plain Alpine VM, as root:

```sh
wget -O /tmp/i.sh http://<hub-ip>/install.sh && sh /tmp/i.sh [group]
```

**Many nodes: clone a template.**

1. On a second Alpine VM, run the same installer as for the hub and pick
   *node*. Enter the hub URL when asked (e.g. `http://10.0.0.100`); it is
   stored in the template.
2. Shut it down and convert it to a vCenter template. Don't configure or test
   it first: that undoes the cleanup.
3. Clone it once per network segment, boot each clone, log in and answer the
   setup prompt. Only the group is asked.

Each node names itself `ct-<group>-<ab1234>` and shows up on the dashboard.
For fully automatic clones, see
[Zero-touch deployment](#zero-touch-deployment-with-guestinfo).

### Updating

Run `confettictl-update` on the hub as root, then update the nodes from the
dashboard (a node's update button, or **update all**). Details:
[BUILD_GUIDE §6.3](docs/BUILD_GUIDE.md#63-updating).

## Advanced deployment

### Zero-touch deployment with guestinfo

For bulk or scripted deployments, set guestinfo keys on each VM in vCenter
before first boot (VM Options → Advanced → Configuration Parameters, or
PowerCLI `New-AdvancedSetting`), and the VM configures itself with no login.

- **Nodes:** set `guestinfo.confetti.hub_url` and `guestinfo.confetti.group`
  on each clone. Guestinfo wins over the hub URL stored in the template.
- **Hub:** set `guestinfo.hub.ip` and `guestinfo.hub.gateway` (optionally
  `.dns` and `.hostname`).

| Key | Example | Notes |
|---|---|---|
| `guestinfo.confetti.hub_url` | `http://10.0.0.100` | **required** for zero-touch |
| `guestinfo.confetti.group` | `site-a` | **required** for zero-touch |
| `guestinfo.confetti.subnet` | `10.1.1.0/24` | default: from DHCP lease |
| `guestinfo.confetti.hostname` | `ct-site-a` | default: `ct-<group>-<ab1234>`; must be unique |
| `guestinfo.confetti.dns_server` | `10.0.0.53` | unset skips the DNS test |
| `guestinfo.confetti.dns_query` | `example.com` | name the DNS test looks up |
| `guestinfo.hub.ip` | `10.0.0.100/24` | unset: asked at login |
| `guestinfo.hub.gateway` | `10.0.0.1` | |
| `guestinfo.hub.dns` | `10.0.0.53` | needed for `confettictl-update` |
| `guestinfo.hub.hostname` | `confetti-hub` | re-read every boot |

### Install notes

- `online-install.sh` downloads the repo to `/root/confetti` and runs
  `confettictl-install.sh`. Pass `hub` or `node` to skip the menu and `-y` to
  skip the confirmation. For an unattended node template, set
  `CONFETTI_HUB_URL=http://10.0.0.100`.
- The installer refuses to run on a VM that is already a hub or node:
  re-running wipes its config or the hub's database.
- **Single node VM, no cloning:** answer *yes* when the installer asks to
  configure the VM now, or run `confettictl-node-setup.sh` later.
- Every node fetches its SSH keys from the hub at setup. The hub's management
  key is trusted on first use and lets the hub push updates. Set
  `HUB_MANAGED=false` in a node's config to opt out.

More: [`docs/QUICKSTART.md`](docs/QUICKSTART.md) (reference tables) and
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) (checklist with verification).

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
