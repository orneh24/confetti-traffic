# Pervium — Reference

Commands and tables for someone who already knows the setup. Deploy steps:
the [README quick start](../README.md#quick-start). Checklist with
verification: `DEPLOYMENT.md`. Design: `CLAUDE.md`.

The network between nodes is out of scope. This assumes it exists and is
reachable.

## Ports and services

| What | Where | Port |
|---|---|---|
| Dashboard / API | hub, `pervium-hub` (waitress) | 80 |
| Syslog receiver (optional, UDP) | hub, same process | 514 |
| HTTP test target | node, `pervium-httpd` | 80 |
| SSH test target | node, dropbear | 22 |
| SMB test target (opt-in) | node, `pervium-smbd` | 445 |
| SMTP test target (opt-in) | node, `pervium-smtpd` | 25 |
| iperf3 (opt-in) | node, `iperf3` | 5201 |

## Files

| | Hub | Node |
|---|---|---|
| Code | `/opt/pervium-hub/` | `/usr/local/bin/pervium/` |
| Config | `/opt/pervium-hub/hub.env` | `/etc/pervium/config` |
| Data | `/var/lib/pervium/hub.db` | — |
| Logs | `/var/log/pervium-hub.log` | `/var/log/pervium/` |
| Login-prompt stamp | `/etc/pervium-hub/.setup-done` | `/etc/pervium/.setup-done` |

The stamp file says why the login prompt stopped asking: `configured`,
`skipped`, `configured (guestinfo)` or `configured (existing config)`.
Delete it, or run `node-setup.sh --force` / `hub-setup.sh --force`, to be
asked again.

## Hub config (`hub.env`)

Restart the hub after editing: `rc-service pervium-hub restart`.

| Key | Default | Notes |
|---|---|---|
| `HUB_PORT` | 80 | |
| `HUB_DB_PATH` | `/var/lib/pervium/hub.db` | |
| `HUB_RESULT_RETENTION_HOURS` | 24 | old results pruned on each result push |
| `HUB_STALE_ENDPOINT_HOURS` | 6 | nodes unseen this long are dropped |
| `HUB_SYSLOG_ENABLED` | true | |
| `HUB_SYSLOG_BIND` | `0.0.0.0` | |
| `HUB_SYSLOG_PORT` | 514 | needs root; use >1024 for a manual `run.sh` |
| `HUB_SYSLOG_MAX_ROWS` | 300000 | syslog is capped by rows, not time |
| `HUB_BUSY_TIMEOUT_MS` | 5000 | |
| `HUB_PATH_CHANGE_ENABLED` | true | log traceroute path changes to syslog |
| `HUB_HEALTH_SERVICES` | `pervium-hub,chronyd,dropbear,open-vm-tools,lldpd` | shown in Hub Health |
| `HUB_HEALTH_SERVICE_TIMEOUT_S` | 3 | time limit for each service check in Hub Health |
| `HUB_PUSH_TIMEOUT_S` | 600 | time limit for one node's push-update |
| `HUB_PUSH_SEEN_MINUTES` | 10 | push only to nodes seen this recently |

`HUB_KEY_DIR` and `HUB_BUNDLE_DIR` exist for local test runs only. The
service and the build use the fixed paths `/etc/pervium-hub/keys` and
`/opt/pervium-hub/bundle`.

The root password (`lab123`) is set at build time. Override it with
`PERVIUM_ROOT_PASSWORD` when running either `build-template.sh`.

## Node config (`/etc/pervium/config`)

| Key | Required | Notes |
|---|---|---|
| `HUB_URL` | yes | no trailing slash |
| `GROUP_NAME` | yes | label that groups nodes on the dashboard |
| `SUBNET` | yes | filled in from the DHCP lease by `setup.sh` |
| `NODE_HOSTNAME` | no | if empty: `<HOSTNAME_PREFIX>-<group>-<NODE_ID>` |
| `HOSTNAME_PREFIX` | no | default `pv` |
| `NODE_ID` | no | two random letters + four random digits (e.g. `xd2311`), generated once by `setup.sh` |
| `HUB_MANAGED` | no | default true; false removes the hub's management key (no push-update) |
| `DNS_SERVER` | no | empty skips the DNS test |
| `DNS_QUERY` | no | default `example.com` |
| `ENABLE_IPERF` / `ENABLE_SMB` / `ENABLE_SMTP` | no | default false; overridden by the dashboard's Mesh Settings when set there |
| `HUB_SETTINGS` | no | default true; false ignores the dashboard's Mesh Settings |
| `AGENT_AUTOUPDATE` | no | default true |

If `HUB_URL`, `GROUP_NAME` or `SUBNET` is empty, `register.sh` exits and the
node never appears on the hub. There is no other error.

After editing, re-run `/usr/local/bin/pervium/setup.sh`. It keeps the
config and starts any service you enabled.

## Verify

```sh
curl http://<hub-ip>/api/health         # always 200; read the body
curl http://<hub-ip>/api/time           # clock (chrony) state
curl http://<hub-ip>/endpoints          # registered nodes
curl 'http://<hub-ip>/api/results?minutes=5'
curl 'http://<hub-ip>/api/syslog?minutes=5'   # [] is fine; an error means the listener is down
```

Dashboard: `http://<hub-ip>/`. Syslog viewer: `http://<hub-ip>/syslog`. Timeline: `http://<hub-ip>/timeline`.

## Routine admin

**Static targets** (no agent to install):

```sh
curl -X POST http://<hub-ip>/targets -H 'Content-Type: application/json' \
  -d '{"name":"gw-a","ip":"10.1.1.1","tests":["traceroute","pmtu"]}'
curl http://<hub-ip>/targets
curl -X DELETE http://<hub-ip>/targets/gw-a
```

Test names: `http ssh traceroute pmtu dns iperf3 smb loss smtp`. List only
what the target answers; a loopback has no web server.

**Send a device's syslog to the hub:** UDP/514, RFC3164. Point the device's
NTP at a real server, not the hub; the hub serves time to nobody.

**A node stopped reporting:** it turns amber in the Endpoints list after 5
minutes, and its matrix cells go grey (no data, not failure). Check the
node's `/var/log/pervium/` before the network.

**Remove a dead node:** `curl -X DELETE http://<hub-ip>/endpoints/<hostname>`

**See one node's results from the node itself:** `test-status` (`-f` to
follow, `-n N` for history).

**Update to the latest code:** first run `pervium-update` on the hub, which
downloads from GitHub. Then use the dashboard's update button per node, or
**update all**: the hub pushes its own build to each node over SSH. It keeps
configs, the database and the root password. The dashboard shows the
commit each node runs under its name, and `cat /etc/pervium-release` shows it on a VM.
Details: BUILD_GUIDE §6.3.

**Add a node without a template:** on a plain Alpine VM,
`wget -O /tmp/i.sh http://<hub-ip>/install.sh && sh /tmp/i.sh [group]`.

## Traps

| Trap | Symptom |
|---|---|
| Node template configured or tested before sealing | every clone starts with the same hostname, and the login prompt never appears |
| Two nodes with the same hostname | one overwrites the other on the hub |
| Static target lists a test it can't answer | that cell is always red |
| Node updated before the hub | `pervium-update` warns; the node's `test-cycle.sh` goes back to the hub's copy within 5 minutes |
| Hub set up without a DNS server (it is optional in `hub-setup.sh`) | `pervium-update` can't download; add a `nameserver` line to `/etc/resolv.conf` |
