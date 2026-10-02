# Confetti Traffic — Roadmap and Open Items

What is designed but not built, what is still unverified, and what was
decided against. History lives in git; architecture in `CLAUDE.md`.

## Designed but not implemented

Nothing here works today. Checked against the code 2026-09-27.

- **Hub as the lab's NTP source.** `chronyd` runs on the hub and `/api/time`
  reports its state, but no `chrony.conf` is written, there is no access list,
  and `node/scripts/confettictl-setup.sh` does not point nodes at the hub. The hub keeps
  its own clock and serves time to nobody. If built, it belongs in `confettictl-setup.sh`
  beside the other config writes.
- **Node clock state.** chrony is installed on nodes, but nothing checks or
  reports whether they are synced. Tolerable because the hub stamps
  `received_at` itself (constraint 2).
- **`confettictl-set-static-ip` per interface.** It takes no interface argument, so
  configuring a second NIC overwrites the first.
- **`net.ipv4.ip_forward=0` pinned in `/etc/sysctl.d/`.** Alpine defaults to
  0, but the build does not assert it.
- **Time-based syslog pruning.** Syslog is row-capped only
  (`HUB_SYSLOG_MAX_ROWS`). Results do have time-based retention (constraint 8).
- **TODO: make the connectivity check configurable instead of always
  full-mesh.** Today every node tests every other node (http, ssh, pmtu,
  loss, plus the opt-in tests). Allow choosing which pairs or groups test
  each other.

## Not yet verified on real VMs

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
