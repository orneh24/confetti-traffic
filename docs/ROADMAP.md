# Confetti Traffic — Roadmap and Open Items

What is designed but not built, what is still unverified, and what was
decided against. History lives in git; architecture in `CLAUDE.md`.

## Designed but not implemented

Nothing here works today. Checked against the code 2026-10-02.

- **`confettictl-set-static-ip` per interface.** It takes no interface argument, so
  configuring a second NIC overwrites the first. The node's no-DHCP fallback
  in `confettictl-setup.sh` has its own copy of the same logic, so a fix must
  cover both.
- **TODO: make the connectivity check configurable instead of always
  full-mesh.** Today every node tests every other node (http, ssh, pmtu,
  loss, plus the opt-in tests). Allow choosing which pairs or groups test
  each other.

## Not yet verified on real VMs

- **Hub as the lab's NTP source.** The hub build appends `allow all` and
  `local stratum 10 orphan` to `chrony.conf`, and `confettictl-setup.sh` points
  node chrony at the host in `HUB_URL` (`HUB_NTP=false` opts out). Checked
  for syntax only so far: confirm on real VMs that nodes reach the hub on
  UDP/123 and report `clock ok` on the dashboard.
- **Syslog on the real hub.** So far only run as a local Python process.
  Confirm the OpenRC service starts the listener, UDP/514 binds, and a real
  device's messages arrive.
- **Dashboard rendering.** R21/R22 in the regression suite cover `/api/time`
  and the syslog correlation links at the API level. That the clock indicator
  colours correctly and the links click through is hand-checked only.

## Decided against

- **ARP table on the dashboard.** ARP only shows a VM's own L2 segment; every
  tested pair crosses a router, so it would show one router MAC and nothing
  about the path.
- **Router config (networks, VLANs) on the dashboard.** Needs the hub to log
  in to every router, which this design avoids — it tests through devices and
  never manages them. Belongs in the separate router project.
- **An IP→device map for syslog.** Where a device's syslog hostname differs
  from a node's group, the filtered link comes back empty (see `CLAUDE.md`,
  Syslog). Fixing that needs device identity, which is out of scope here.
