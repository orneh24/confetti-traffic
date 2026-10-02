# Dev/demo toolkit

Runs a real hub plus a small simulated mesh, entirely on the workstation —
for hub/dashboard work and for exercising node-script changes without a
vCenter lab. Everything here is dev tooling, not something that ships to a
VM; see `CLAUDE.md` for the actual project.

## 1. Start the hub

```sh
dev/confettictl-hub-start.sh          # http://127.0.0.1:8099, backgrounded, pidfile
dev/confettictl-hub-stop.sh
```

Populates `hub/agent/` from `node/scripts/{register,test-cycle}.sh` (gitignored,
build-time-only in production — this just mirrors what `confettictl-build-template.sh`
does) and runs `hub/serve.py` with `HUB_DB_PATH`/`HUB_PORT`/`HUB_SYSLOG_PORT`
pointed at `dev/run/`. Override any of those env vars before calling it.
Log and db land in `dev/run/`, gitignored.

`confettictl-status.sh` is deliberately **not** copied into `hub/agent/` — it isn't
in the hub's `AGENT_SCRIPTS` manifest and never self-updates (see CLAUDE.md,
"Agent self-update").

## 2. Run simulated nodes — the real scripts, unmodified logic

```sh
dev/confettictl-run-node-cycle.sh dev-node-a 10.99.1.11 site-a
dev/confettictl-run-node-cycle.sh dev-node-b 10.99.1.12 site-a
dev/confettictl-run-node-cycle.sh dev-node-c 10.99.1.13 site-b
```

Each call runs the actual `confettictl-register.sh` then `confettictl-test-cycle.sh` against the
local hub, so this is the tool to reach for when you've changed either
script and want to see it work end to end — including the console table,
`/run/confetti/last-cycle.txt`-equivalent snapshot, and `confettictl-status.sh`,
all exercised for real.

One workstation plays many nodes: identity comes from a `hostname` shim
(`dev/shims/hostname`, driven by `DEV_HOSTNAME`), the same thing real
node scripts call — nothing about the scripts themselves changes.

Two edits, and only two, are made to scratch copies before running (same
precedent `dev/regress.py` uses for its own live-hub runs):
`CONFIG` in both scripts, and — `confettictl-test-cycle.sh` only — `LOCK_DIR` and
`TRACEROUTE_STAMP`. All three are OS-root paths (`/etc/confetti/...`,
`/run/...`) that don't exist off a real Alpine node. `SNAPSHOT_FILE` needs no
edit — it already honors an env override, which this also happens to prove.

`--loop` keeps a node running a cycle every 60s (Ctrl-C to stop) instead of
once — useful for leaving a mesh live in a side terminal during a coding
session. `-h` for the rest of the flags (group, `ENABLE_SMB`/`ENABLE_SMTP`/
`ENABLE_IPERF`/`DNS_SERVER`, `DEV_FAIL_HOSTS`).

### What's real vs. what's shimmed

`dev/shims/` stands in for `ping`, `ssh`, `traceroute`, `dig`, `iperf3`,
`smbclient`, `fping`, `nc` and `ip` — every external binary these scripts
shell out to, matching exactly the call shape each script actually uses (see
each shim's own header comment). `curl` and `jq` are the real thing.

**HTTP is the one test type that reads FAIL here, always.** `run_http_test`
talks to a real socket via `curl` — there's no PATH trick for that — and
nothing is listening on any of these fictional IPs. This is a known,
accepted limitation, not a bug: every other test type (SSH, PMTU, loss,
traceroute, SMB, SMTP, iperf3, DNS) is genuinely exercised through the real
script logic and reads OK.

`DEV_FAIL_HOSTS` (comma-separated IP substrings, exported before calling
`confettictl-run-node-cycle.sh`) makes the ssh/ping/fping shims report failure for a
matching target — the one knob for putting a deliberately broken path (red
cells, a failure-triggered traceroute, a losing loss/jitter row) into the
demo mesh:

```sh
DEV_FAIL_HOSTS=10.99.1.13 dev/confettictl-run-node-cycle.sh dev-node-a 10.99.1.11 site-a
```

## 3. Look at it

`http://127.0.0.1:8099/` — dashboard. `http://127.0.0.1:8099/syslog` — syslog
viewer. `http://127.0.0.1:8099/timeline` — incident timeline. To send it a test message, use the Python one-liner in
`docs/BUILD_GUIDE.md` §6.4 with the port changed to `HUB_SYSLOG_PORT`. Reset
by deleting `dev/run/` and starting over.

## Running the hub by hand

`dev/confettictl-hub-start.sh` is the easy path. For the manual `serve.py` command, see
the main README, "Running the hub locally". `hub/confettictl-run.sh` does the same and
also loads `hub/hub.env` if present.

In the Claude desktop app, `.claude/launch.json` defines the same dev hub as
`confetti-hub` (port 8099, same DB and syslog port as `dev/confettictl-hub-start.sh`) for
its preview pane, run in the foreground under Git Bash's `sh.exe`.

Importing `app.app` runs `init_db()` at import time, so any script that
imports it creates `hub.db` in the current directory unless `HUB_DB_PATH` is
set. Set it.

## When to use which

- **Changed the hub API, schema, or dashboard?** `dev/confettictl-hub-start.sh`, then
  `dev/confettictl-run-node-cycle.sh` a couple of nodes to get real data on screen.
- **Changed `confettictl-register.sh` or `confettictl-test-cycle.sh`?** `dev/confettictl-run-node-cycle.sh` is
  the point — it's the real script, so a syntax slip or a wire-contract
  break shows up exactly as it would on a real node.
- **Verifying a change before handing it off?** Run `python3 dev/regress.py`
  (the regression suite: every CLAUDE.md constraint plus a live hub and node
  round trip, about 20 s; `--static` skips the live part). The
  `regression-tester` agent runs the same script and explains failures.
