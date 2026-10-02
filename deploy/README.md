# Deploy tooling

`Deploy-Confetti.ps1` — PowerCLI script that clones a hub and N nodes from
existing vCenter templates and sets the guestinfo keys their firstboot
services read (see `CLAUDE.md`, "Per-VM configuration: guestinfo"). It only
does vSphere-side provisioning — everything after power-on is the zero-touch
firstboot path already built into the templates.

## Prerequisites

- The two golden templates already built (`hub/confettictl-build-template.sh`,
  `node/confettictl-build-template.sh`) and present in vCenter.
- An active PowerCLI session: `Connect-VIServer <vcenter>` before running
  the script — it does not handle credentials itself.

## Usage

```powershell
Connect-VIServer vcenter.lab.local

./Deploy-Confetti.ps1 `
    -HubTemplate confetti-hub-template `
    -NodeTemplate confetti-node-template `
    -PortGroup "VM Network" `
    -VMHost esxi01.lab.local -Datastore datastore1 `
    -HubIP 10.0.0.100/24 -HubGateway 10.0.0.1
```

Deploys the hub plus 3 nodes (`site-a`/`site-b`/`site-c` by default) on one
flat network. `-WhatIf` previews without touching vCenter;
`-WaitForRegistration` polls the hub afterward and reports which nodes came
up (best-effort — a slow node is reported, not treated as failure).
Add `-HubDns 10.0.0.53` so the hub can resolve names (`confettictl-update`
needs this), and `-HubHostname` to name the hub's guest OS.

Full parameter reference: `Get-Help ./Deploy-Confetti.ps1 -Full`.

## Multi-segment labs

This script deploys onto a single `-PortGroup` for every VM — the simple
case. A real topology is usually one node per network segment
(`CLAUDE.md`), which needs different portgroups per node; for that, either
run the script once per segment (`-NodeCount` matched to that segment), or
extend it to accept a portgroup per node the same way `-NodeGroups` already
works.
