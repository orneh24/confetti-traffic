#!/usr/bin/env python3
"""dev/regress.py - the regression suite, as one script.

Runs every check the regression-tester agent guards (R1-R27, the dynamic
tier and the wire contract) and prints one line per check. Details are
printed only for a failure, so a clean run is short.

    python3 dev/regress.py            # everything, including a live hub
    python3 dev/regress.py --static   # skip the live hub and node cycle
    python3 dev/regress.py -v         # also print details for passes

Exit status: 0 when nothing failed (some checks may be NOT RUN), 1 on any
failure. The live tier runs a scratch hub from a temp copy of hub/ on a
high port and two simulated nodes (dev/shims), then removes all of it.
Nothing is written to the project tree.

Each check says what it guards in one line; the reasoning behind each one is
the matching numbered constraint in CLAUDE.md.
"""
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

VERBOSE = "-v" in sys.argv
STATIC_ONLY = "--static" in sys.argv

APP = "hub/app/app.py"
SYSLOG = "hub/app/syslog_server.py"
DASH = "hub/templates/dashboard.html"
CYCLE = "node/scripts/confettictl-test-cycle.sh"
REGISTER = "node/scripts/confettictl-register.sh"
SETUP = "node/scripts/confettictl-setup.sh"
NODE_BUILD = "node/confettictl-build-template.sh"
HUB_BUILD = "hub/confettictl-build-template.sh"

TEST_TYPES = {"http", "ssh", "traceroute", "pmtu", "dns", "iperf3", "smb", "loss", "smtp"}
WIRE_FIELDS = {"target_hostname", "target_ip", "test_type", "success",
               "latency_ms", "output", "timestamp"}

results = []   # (status, id, desc, [detail lines])


class Skip(Exception):
    pass


def check(cid, desc):
    """Register and run a check. The function returns a list of problems
    (empty = pass) or raises Skip(reason)."""
    def wrap(fn):
        try:
            problems = fn() or []
            results.append(("FAIL" if problems else "PASS", cid, desc, problems))
        except Skip as e:
            results.append(("NOT RUN", cid, desc, [str(e)]))
        except Exception as e:  # a crashed check is a failure, never a pass
            results.append(("FAIL", cid, desc, ["check crashed: %r" % e]))
        return fn
    return wrap


# ---------------------------------------------------------------- helpers

_cache = {}


def read(path):
    if path not in _cache:
        with open(path, encoding="utf-8") as f:
            _cache[path] = f.read()
    return _cache[path]


def files(pattern, **kw):
    """glob with forward slashes, so paths match on Windows too."""
    return sorted(f.replace("\\", "/") for f in glob.glob(pattern, **kw))


def lines(path):
    return read(path).splitlines()


def grep(pattern, path, flags=0):
    """[(lineno, line)] for lines matching pattern."""
    path = path.replace("\\", "/")
    rx = re.compile(pattern, flags)
    return [(i, l) for i, l in enumerate(lines(path), 1) if rx.search(l)]


def at(path, hits):
    return ["%s:%d: %s" % (path, n, l.strip()) for n, l in hits]


def is_comment(line):
    return line.lstrip().startswith("#")


def git_files(*patterns):
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--"] + list(patterns),
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def py_func(path, name):
    """Body of a top-level Python function (or method), up to the next
    line at the same or lower indent."""
    ls = lines(path)
    for i, l in enumerate(ls):
        m = re.match(r"(\s*)def %s\(" % re.escape(name), l)
        if m:
            ind = len(m.group(1))
            body = [l]
            for l2 in ls[i + 1:]:
                if l2.strip() and len(l2) - len(l2.lstrip()) <= ind and not l2.lstrip().startswith(("#", ")")):
                    break
                body.append(l2)
            return "\n".join(body)
    return ""


def enclosing_def(path, lineno):
    for l in reversed(lines(path)[:lineno]):
        m = re.match(r"def (\w+)\(", l)
        if m:
            return m.group(1)
    return None


def sh_func(path, name):
    """Body of a shell function `name() {` up to the closing `}` at column 0."""
    body, inside = [], False
    for l in lines(path):
        if re.match(r"%s\(\)\s*\{" % re.escape(name), l):
            inside = True
        if inside:
            body.append(l)
            if l.startswith("}"):
                break
    return "\n".join(body)


def need(cond, msg, problems):
    if not cond:
        problems.append(msg)


# ============================================================ Tier 1 static

@check("R1", "hostnames unique per clone")
def _():
    p = []
    need(grep(r"hostname +TEXT PRIMARY KEY", APP), "endpoints.hostname is not the PRIMARY KEY", p)
    need(grep(r"confetti-template", NODE_BUILD), "template no longer ships as confetti-template", p)
    need(grep(r"/etc/hostname", SETUP), "confettictl-setup.sh no longer writes /etc/hostname", p)
    return p


@check("R2", "hub filters on received_at; timestamps leave via iso()")
def _():
    p = at(APP, grep(r"WHERE[^)]*\btimestamp\b|timestamp *(>=|<=|<|>) *datetime", APP))
    for n, l in grep(r"datetime\('now'", APP):
        if "received_at" not in l and "last_seen" not in l and not is_comment(l) \
                and not l.strip().startswith(("'", '"', "those")):
            p.append("%s:%d compares datetime('now') against something other than received_at/last_seen: %s"
                     % (APP, n, l.strip()))
    for n, l in grep(r"return jsonify\(\[dict\(r\) for r in rows\]\)", APP):
        if enclosing_def(APP, n) != "api_syslog_sources":
            p.append("%s:%d returns raw rows (no iso()) in %s()" % (APP, n, enclosing_def(APP, n)))
    need('d["received_at"] = iso(' in py_func(APP, "result_row"), "result_row() no longer applies iso()", p)
    for fn in ("api_results", "api_results_pair"):
        need("result_row(" in py_func(APP, fn), "%s() no longer goes through result_row()" % fn, p)
    need(grep(r"function parseTs", DASH), "dashboard parseTs() is gone", p)
    return p


@check("R3", "mesh SSH key comes from the hub, restricted to `echo ok`")
def _():
    p = []
    trust = "node/scripts/confettictl-trust-hub.sh"
    need(grep(r"^\s*rm .*dropbear_.*host_key", NODE_BUILD), "cleanup no longer deletes dropbear host keys", p)
    # Every node must hold the same key; a per-build keygen breaks the SSH
    # test between nodes installed separately.
    p += ["node build generates its own mesh key: " + x
          for x in at(NODE_BUILD, [h for h in grep(r"ssh-keygen", NODE_BUILD) if not is_comment(h[1])])]
    # The private key is served over HTTP: only safe with the forced command.
    need(grep(r'command=\\"echo ok\\",no-pty,no-port-forwarding', trust),
         "confettictl-trust-hub.sh no longer restricts the mesh key to command=\"echo ok\"", p)
    need(grep(r"echo ok", CYCLE), "confettictl-test-cycle.sh's SSH test no longer runs `echo ok`", p)
    # The management key must never be served privately.
    p += ["hub serves the private management key: " + x
          for x in at(APP, grep(r'"id_hub"', APP))]
    return p


@check("R3b", "hub management key is pinned on first use, never replaced by cron")
def _():
    p = []
    trust = "node/scripts/confettictl-trust-hub.sh"
    body = read(trust)
    need(re.search(r'MODE" = "auto" \] && \[ -f "\$PIN" \] && \[ "\$\(cat "\$PIN_URL"', body),
         "confettictl-trust-hub.sh --auto no longer keeps an existing pin for the same HUB_URL", p)
    # confettictl-register.sh runs every 5 minutes: it may only warn, or run --auto when
    # nothing is pinned yet.
    for n, l in grep(r"hub_key\.pub", REGISTER):
        if re.search(r">\s*/etc/confetti/hub_key\.pub", l):
            p.append("%s:%d confettictl-register.sh writes the pin: %s" % (REGISTER, n, l.strip()))
    for n, l in grep(r"trust-hub\.sh", REGISTER):
        if not is_comment(l) and "--auto" not in l:
            p.append("%s:%d confettictl-register.sh runs confettictl-trust-hub.sh without --auto: %s" % (REGISTER, n, l.strip()))
    return p


@check("R28", "derived hostname is ct-<group>-<random NODE_ID>, not the IP")
def _():
    p = []
    need(grep(r'DESIRED_HOSTNAME="\$\{HOSTNAME_PREFIX\}-\$\{_slug\}-\$\{NODE_ID\}"', SETUP),
         "confettictl-setup.sh no longer derives <prefix>-<group>-<NODE_ID>", p)
    need(grep(r"tr -dc 'a-z' < /dev/urandom.*head -c 2", SETUP)
         and grep(r"tr -dc '0-9' < /dev/urandom.*head -c 4", SETUP),
         "NODE_ID is no longer 2 random letters + 4 random digits", p)
    p += at(SETUP, [h for h in grep(r"DESIRED_HOSTNAME=.*MY_IP", SETUP) if not is_comment(h[1])])
    return p


@check("R4", "confettictl-setup.sh never copies scripts onto themselves")
def _():
    guard = grep(r'if \[ "\$SRC_DIR" != "\$SCRIPT_DIR" \]', SETUP)
    cps = grep(r'cp -f "\$SRC_DIR/', SETUP)
    if not guard:
        return ["no SRC_DIR != SCRIPT_DIR comparison before the script copy"]
    if not cps or cps[0][0] < guard[0][0]:
        return ["a cp of the scripts runs before the path comparison"]
    return []


@check("R5", "web server is the confettid-httpd OpenRC service")
def _():
    p = []
    hits = []
    for f in git_files("node/"):
        if os.path.isfile(f) and "rc-update add confettid-httpd" in read(f):
            hits.append(f)
    need(hits, "nothing runs rc-update add confettid-httpd", p)
    for f in git_files("node/scripts/"):
        p += at(f, grep(r"^[^#]*busybox httpd|^[^#]*\bhttpd -p", f))
    return p


@check("R6", "confettictl-test-cycle.sh takes a lock")
def _():
    p = []
    mk = grep(r'mkdir "\$LOCK_DIR"', CYCLE)
    trap = grep(r'trap .*LOCK_DIR.*EXIT INT TERM', CYCLE)
    first_test = [n for n, l in grep(r"run_\w+_test ", CYCLE) if not re.match(r"\s*run_\w+_test\(\)", l)]
    need(mk, "no mkdir $LOCK_DIR", p)
    need(trap, "lock not released on EXIT INT TERM", p)
    need(grep(r'LOCK_DIR.*-mmin', CYCLE), "stale lock no longer cleared on an age check", p)
    if mk and first_test and first_test[0] < mk[0][0]:
        p.append("a test runs (line %d) before the lock is taken (line %d)" % (first_test[0], mk[0][0]))
    return p


@check("R7", "empty (skipped) results are never appended")
def _():
    p = []
    body = sh_func(CYCLE, "append_result")
    need(re.search(r'\[ -z "\$1" \].*return', body), "append_result() no longer returns early on empty input", p)
    inside = False
    for n, l in enumerate(lines(CYCLE), 1):
        if re.match(r"append_result\(\)", l):
            inside = True
        elif inside and l.startswith("}"):
            inside = False
            continue
        if not inside and re.search(r'RESULTS="\$\{?RESULTS', l):
            p.append("%s:%d appends outside append_result(): %s" % (CYCLE, n, l.strip()))
    return p


@check("R8", "retention sweeps still fire")
def _():
    p = []
    need("prune_old_results(" in py_func(APP, "push_results"), "POST /results no longer calls prune_old_results", p)
    need("prune_stale_endpoints(" in py_func(APP, "list_endpoints"), "GET /endpoints no longer calls prune_stale_endpoints", p)
    return p


@check("R9", "latency_ms is never string-concatenated")
def _():
    p = []
    for f in files("node/scripts/*.sh"):
        p += at(f, grep(r"printf[^|]*%d0{3}", f))
        p += at(f, [h for h in grep(r"\$\{?[A-Za-z_][A-Za-z_0-9]*\}?0{3}", f) if not is_comment(h[1])])
    for n, l in grep(r"_latency=", CYCLE):
        v = l.split("_latency=", 1)[1].strip()
        if is_comment(l) or v.startswith(("$((", '"$((', "null", '"null"', "$(awk", '$(printf "%s"')):
            continue
        if re.match(r'"?\$\(\s*awk|"?\$\{?_\w+\}?"?$|\$\(printf', v):
            continue
        p.append("%s:%d unusual _latency= producer, check it: %s" % (CYCLE, n, l.strip()))
    return p


@check("R10", "traceroute stays rationed")
def _():
    p = []
    need(grep(r"traceroute -n -q 1 ", CYCLE), "traceroute no longer runs -q 1", p)
    need(grep(r"TRACEROUTE_MAX_HOPS:-10", CYCLE), "max hops no longer defaults to 10", p)
    need(grep(r"TRACEROUTE_INTERVAL:-300", CYCLE), "interval no longer defaults to 300", p)
    need(grep(r'TRACE_THIS_CYCLE" = "yes" \] \|\| \[ "\$_failed_now" = "yes"', CYCLE),
         "on-demand traceroute no longer gated on schedule-or-just-failed", p)
    return p


@check("R11", "confettictl-register.sh does not exit 0 after registering")
def _():
    f, p = False, []
    for n, l in enumerate(lines(REGISTER), 1):
        if "Registration successful" in l:
            f = True
        if 'update_script "confettictl-test-cycle.sh"' in l:
            f = False
        if f and re.match(r"exit ", l):
            p.append("%s:%d unconditional exit before self-update: %s" % (REGISTER, n, l.strip()))
    return p


@check("R12", "confettictl-setup.sh merges root's crontab, never replaces it")
def _():
    body = read(SETUP)
    s = body[body.find("# Install crontab"):]
    p = []
    need(s and "crontab -l" in s, "crontab -l no longer read first", p)
    need("grep -v '^# confetti'" in s, "prior confetti block no longer stripped", p)
    need('cat >> "$TMP_CRON"' in s, "new entries no longer appended to the merged copy", p)
    need("run-parts" in s, "surviving run-parts count no longer logged", p)
    if s and "crontab -l" in s and 'crontab "$TMP_CRON"' in s:
        need(s.find("crontab -l") < s.find('crontab "$TMP_CRON"'), "crontab installed before the old one is read", p)
    return p


@check("R13", "only confettictl-test-cycle.sh auto-updates (release-blocking)")
def _():
    calls = [(n, l) for n, l in grep(r'update_script "', REGISTER) if not is_comment(l)]
    names = [re.search(r'update_script "([^"]+)"', l).group(1) for _, l in calls]
    if names != ["confettictl-test-cycle.sh"]:
        return ["update_script calls: %s (want exactly confettictl-test-cycle.sh)" % names] + at(REGISTER, calls)
    return []


@check("R14", "Alpine package selection")
def _():
    p = []
    body = read(NODE_BUILD)
    m = re.search(r"apk add --no-cache[^\n]*\\\n((?:[^\n]*\\\n)*[^\n]*)", body)
    pkgs = set(re.findall(r"[a-z0-9][a-z0-9._-]+", re.sub(r"#[^\n]*", "", m.group(0)))) if m else set()
    for want in ("iputils-ping", "openssh-client", "samba-server", "samba-client", "opensmtpd"):
        need(want in pkgs, "package %s missing from apk add" % want, p)
    for bad in ("dropbear-ssh", "iputils", "samba", "opensmtpd-openrc"):
        need(bad not in pkgs, "package %s must not be installed" % bad, p)
    # The hub needs an ssh client (and ssh-keygen, which it pulls in) for
    # push-update and its keypairs. sshpass went with the password-based
    # push script.
    hm = re.search(r"apk add --no-cache[^\n]*\\\n((?:[^\n]*\\\n)*[^\n]*)", read(HUB_BUILD))
    hub_pkgs = set(re.findall(r"[a-z0-9][a-z0-9._-]+", hm.group(0))) if hm else set()
    need("openssh-client" in hub_pkgs, "hub: package openssh-client missing from apk add", p)
    need("sshpass" not in hub_pkgs, "hub: sshpass is back in apk add", p)
    p += at(NODE_BUILD, grep(r"^[^#]*dropbear-ssh", NODE_BUILD))
    p += at(NODE_BUILD, grep(r"^[^#]*opensmtpd-openrc", NODE_BUILD))
    return p


@check("R14b", "SMTP probe server can never send mail (release-blocking)")
def _():
    f = "node/services/smtpd.conf"
    p = at(f, [h for h in grep(r"relay", f) if not is_comment(h[1])])
    p += at(f, [h for h in grep(r"^\s*match\b.*\bfor any\b", f)])
    need(grep(r"^[^#]*relay", NODE_BUILD) or grep(r"grep.*relay", NODE_BUILD),
         "build-time grep for a relay action is gone", p)
    return p


@check("R15", "agent definitions parse")
def _():
    p = []
    models = {"sonnet", "opus", "haiku", "fable", "inherit"}
    for f in sorted(files(".claude/agents/*.md")):
        head = read(f).split("\n---", 1)[0]
        if not read(f).startswith("---"):
            p.append("%s: no front matter" % f)
            continue
        fm = dict(re.findall(r"^(\w+):\s*(.*)$", head, re.M))
        for k in ("name", "description"):
            need(fm.get(k), "%s: no %s" % (f, k), p)
        t = fm.get("tools")
        if t is not None and (t.startswith("[") or t == ""):
            p.append("%s: tools must be a comma-separated string" % f)
        if re.search(r"^tools:\s*$\n\s*-", head, re.M):
            p.append("%s: tools is a YAML list" % f)
        mo = fm.get("model")
        if mo and mo not in models and not mo.startswith("claude-"):
            p.append("%s: unknown model %r" % (f, mo))
    return p


@check("R16", "first boot stands down without guestinfo")
def _():
    f = "node/services/firstboot.initd"
    p = []
    need(grep(r'_guestinfo "confetti\.hub_url"', f), "hub_url not checked", p)
    need(grep(r'_guestinfo "confetti\.group"', f), "group not checked", p)
    for n, l in grep(r'"\$SETUP"', f):
        if "-x" in l or is_comment(l):
            continue
        need("< /dev/null" in l, "%s:%d runs confettictl-setup.sh without stdin from /dev/null" % (f, n), p)
    return p


@check("R17", "busy_timeout on both SQLite connections")
def _():
    p = []
    need("busy_timeout" in py_func(APP, "get_db") and "BUSY_TIMEOUT_MS" in py_func(APP, "get_db"),
         "get_db() no longer sets busy_timeout from config", p)
    need(re.search(r"busy_timeout.*BUSY_TIMEOUT_MS", py_func(SYSLOG, "__init__")),
         "syslog listener connection no longer sets busy_timeout", p)
    need(grep(r"BUSY_TIMEOUT_MS", "hub/app/config.py"), "config.BUSY_TIMEOUT_MS gone", p)
    return p


@check("R18", "syslog timestamps stored in SQLite format")
def _():
    p = []
    for f in (APP, SYSLOG):
        for n, l in grep(r'strftime\("([^"]*)"', f):
            fmt = re.search(r'strftime\("([^"]*)"', l).group(1)
            if "T" in fmt or "Z" in fmt:
                p.append("%s:%d stores ISO format: %s" % (f, n, l.strip()))
    need('"%Y-%m-%d %H:%M:%S"' in py_func(APP, "sqlite_now"), "sqlite_now() format changed", p)
    need('"%Y-%m-%d %H:%M:%S"' in py_func(SYSLOG, "insert"), "_Store.insert() format differs from sqlite_now()", p)
    need("iso(" in py_func(APP, "syslog_row"), "syslog_row() no longer applies iso()", p)
    return p


@check("R19", "explicit null does not discard the batch (static)")
def _():
    p = at(APP, grep(r'\.get\("(target_hostname|target_ip|test_type|output|timestamp)"', APP))
    need(grep(r"^def text\(", APP) or grep(r"^\s+def text\(", APP), "text() None-coercion helper gone", p)
    return p


@check("R20", "syslog listener does not set allow_reuse_address")
def _():
    return at(SYSLOG, [h for h in grep(r"allow_reuse_address", SYSLOG) if not is_comment(h[1])])


@check("R22", "correlation links: pinned window wiring (static)")
def _():
    p = []
    need(len(grep(r"var SYSLOG_PIN_MINUTES *=", DASH)) == 1, "SYSLOG_PIN_MINUTES not defined exactly once", p)
    body = read(DASH)
    m = re.search(r"function syslogUrl[\s\S]*?\n    \}", body)
    fn = m.group(0) if m else ""
    need("from=" in fn and "to=" in fn, "syslogUrl() no longer emits from= and to=", p)
    need("&host=" in body, "group link no longer appends &host=", p)
    need(len(grep(r"received_at \|\| ", DASH)) >= 2, "call sites no longer anchor on received_at || timestamp", p)
    need(re.search(r"var anchor = parseTs\(ts\)", fn), "syslogUrl() anchor no longer goes through parseTs()", p)
    need("sqlite_ts_arg(" in py_func(APP, "api_syslog"), "api_syslog no longer routes from/to through sqlite_ts_arg", p)
    return p


@check("R23", "login hook triple-guarded, both roles")
def _():
    p = []
    for f in ("node/services/confettictl-login-setup.sh", "hub/services/confettictl-login-setup.sh"):
        for pat, what in ((r'case "\$-" in', 'case "$-"'), (r"\[ -t 0 \]", "[ -t 0 ]"), (r"\.setup-done", ".setup-done")):
            n = len(grep(pat, f))
            need(n == 1, "%s: %s guard appears %d times (want 1)" % (f, what, n), p)
        need(grep(r"\*i\*\)", f), "%s: interactive guard not *i*)-anchored" % f, p)
    return p


@check("R24", "every interactive read is EOF-guarded")
def _():
    p = []
    for f in (SETUP, "node/scripts/confettictl-node-setup.sh", "hub/scripts/confettictl-hub-setup.sh",
              "node/scripts/confettictl-trust-hub.sh", "confettictl-update.sh"):
        for n, l in grep(r"\bread -r\b", f):
            if is_comment(l):
                continue
            if re.search(r'read -r (\w+)\s*\|\|\s*\1=""', l) or re.search(r"if ! read -r \w+", l):
                continue
            p.append("%s:%d bare read: %s" % (f, n, l.strip()))
    return p


@check("R25", "golden-image cleanup clears the login stamp, both roles")
def _():
    p = []
    need(grep(r"^\s*rm -f .*/etc/confetti-hub/\.setup-done", HUB_BUILD), "hub cleanup no longer removes .setup-done", p)
    body = read(NODE_BUILD)
    m = re.search(r"rm -f /etc/confetti/config[^\n]*\\\n[^\n]*", body)
    need(m and ".setup-done" in m.group(0), "node cleanup no longer removes .setup-done", p)
    need(m and "config.bak-*" in m.group(0), "node cleanup no longer removes config.bak-*", p)
    return p


@check("R26", "confettictl-build-template.sh --update exits before cleanup (release-blocking)")
def _():
    p = []
    for f in (HUB_BUILD, NODE_BUILD):
        ls = lines(f)
        cleanup = [n for n, l in enumerate(ls, 1) if "Clean up for template conversion" in l]
        exit_at = None
        for n, l in enumerate(ls, 1):
            if re.search(r'UPDATE_MODE" = "yes" \]; then', l):
                for k in range(n, min(n + 3, len(ls))):
                    if re.match(r"    exit 0", ls[k]):
                        exit_at = k + 1
        if not cleanup:
            p.append("%s: cleanup header not found" % f)
        elif not exit_at or exit_at > cleanup[0]:
            p.append("%s: no UPDATE_MODE exit 0 before cleanup (line %s)" % (f, cleanup[0]))

        def guarded(pat):
            for n, l in enumerate(ls, 1):
                if re.search(pat, l) and not is_comment(l):
                    return any("UPDATE_MODE" in x for x in ls[max(0, n - 7):n])
            return False
        need(guarded(r"chpasswd"), "%s: chpasswd not guarded by UPDATE_MODE" % f, p)
    hb = lines(HUB_BUILD)
    env = [n for n, l in enumerate(hb, 1) if re.match(r'cat > "\$HUB_INSTALL_DIR/hub\.env"', l)]
    need(env and any("UPDATE_MODE" in x for x in hb[max(0, env[0] - 7):env[0]]),
         "hub.env heredoc not guarded by UPDATE_MODE", p)
    nb = lines(NODE_BUILD)
    idx = [n for n, l in enumerate(nb, 1) if "index.html" in l and not is_comment(l)]
    need(idx and any("UPDATE_MODE" in x for x in nb[max(0, idx[0] - 10):idx[0]]),
         "node placeholder index.html not guarded by UPDATE_MODE", p)
    p += at(NODE_BUILD, [h for h in grep(r'^[^#]*\bcp\b.*\$\{?INSTALL_DIR\}?/[\w-]+\.sh', NODE_BUILD)])
    for f in ("node/services/crontab", SETUP):
        p += ["confettictl-update scheduled (constraint 13): " + x
              for x in at(f, [h for h in grep(r"update\.sh|confettictl-update", f) if not is_comment(h[1])])]
    return p


@check("R27", "terminal output is plain ASCII; apk --no-progress")
def _():
    p = []
    for f in git_files("*.sh"):
        for n, l in grep(r"\bapk (add|update|upgrade|del)\b", f):
            if "--no-progress" not in l and not is_comment(l) \
                    and not re.match(r"\s*(echo|printf|log)\b", l):
                p.append("%s:%d apk without --no-progress" % (f, n))
    out = re.compile(r"^\s*(log|echo|printf|einfo|ewarn|eerror|ebegin|eend|die|sys\.stderr\.write|print)\b"
                     r"|^\s*[|+].*[|+]\s*$")
    for f in git_files("confettictl-install.sh", "confettictl-update.sh", "hub", "node"):
        if re.search(r"(\.sh|\.initd|\.py)$", f):
            for n, l in enumerate(lines(f), 1):
                if out.search(l) and any(ord(c) > 127 for c in l):
                    p.append("%s:%d non-ASCII terminal output" % (f, n))
    return p


@check("R31", "shared blocks match across dashboard, syslog and timeline pages")
def _():
    # CLAUDE.md: themes, the theme picker, confettiBlast, the header confetti
    # and the footer buttons live inline in all three pages, so a change made
    # in one page only is easy to miss. Page-specific CSS (variable sets,
    # Neon box selectors) is deliberately not compared.
    p = []
    pages = ["hub/templates/%s.html" % n for n in ("dashboard", "syslog", "timeline")]
    base = pages[0]

    # 1. The head <script> (themes list, picker, shuffle, confettiBlast).
    #    Comment wording may differ; code may not.
    def head_script(f):
        m = re.search(r"<head>.*?<script>\n(.*?)</script>", read(f), re.S)
        return [l.rstrip() for l in (m.group(1) if m else "").splitlines()
                if l.strip() and not l.lstrip().startswith("//")]
    ref = head_script(base)
    need(ref, "%s: no head <script> found" % base, p)
    for f in pages[1:]:
        cur = head_script(f)
        if cur != ref:
            n = next((i for i, (a, b) in enumerate(zip(ref, cur)) if a != b), min(len(ref), len(cur)))
            p.append("%s: head <script> differs from %s (first at code line %d)" % (f, base, n + 1))

    # 2. Every theme has a block in every page, with the same core colours.
    #    --gray is excluded on purpose: a fill on the dashboard, a text grey
    #    on the other two.
    core = ("--bg", "--bg-card", "--bg-hover", "--border", "--text", "--text-dim",
            "--yellow", "--red", "--green", "--blue", "--cyan",
            "--green-bg", "--red-bg", "--yellow-bg")
    def theme_blocks(f):
        out = {}
        for m in re.finditer(r'^:root(?:\[data-theme="([\w-]+)"\])? \{\n(.*?)^\}', read(f), re.M | re.S):
            out.setdefault(m.group(1) or "dark", dict(re.findall(r"(--[\w-]+):\s*([^;]+);", m.group(2))))
        return out
    blocks = {f: theme_blocks(f) for f in pages}
    names = ["dark"] + re.findall(r"\['([\w-]+)', '", read(base).split("var THEMES", 1)[-1].split("];", 1)[0])
    for name in dict.fromkeys(names):
        for f in pages:
            need(name in blocks[f], "%s: no :root block for theme '%s'" % (f, name), p)
        for v in core:
            vals = {f: blocks[f].get(name, {}).get(v) for f in pages}
            if len(set(vals.values())) > 1:
                p.append("theme '%s' %s differs: %s" % (name, v, ", ".join(
                    "%s=%s" % (f.rsplit("/", 1)[-1], vals[f]) for f in pages)))

    # 3. The header confetti mask: one shared rule (selector is .header on
    #    the dashboard, header on the others).
    def confetti_rule(f):
        m = re.search(r'^:root:not\(\[data-theme="neon"\]\) \.?header::before \{\n(.*?)^\}', read(f), re.M | re.S)
        return m.group(1) if m else None
    ref = confetti_rule(base)
    need(ref, "%s: header confetti rule not found" % base, p)
    for f in pages[1:]:
        need(confetti_rule(f) == ref, "%s: header confetti rule differs from %s" % (f, base), p)

    # 4. The footer buttons.
    for f in pages:
        m = re.search(r'<div class="page-footer">(.*?)</div>', read(f), re.S)
        foot = m.group(1) if m else ""
        need("https://isitdns.com/" in foot, "%s: footer has no 'Is it DNS..?' link" % f, p)
        need("confettiBlast(this)" in foot, "%s: footer has no Confetti! button" % f, p)
    return p


# ============================================================ Tier 2 static

@check("T2-sh", "sh -n on every shell script and initd")
def _():
    targets = (["confettictl-install.sh", "confettictl-update.sh", HUB_BUILD, NODE_BUILD, "hub/confettictl-run.sh",
              "node/services/confettictl-login-setup.sh", "hub/services/confettictl-login-setup.sh"]
             + files("node/scripts/*.sh") + files("hub/scripts/*.sh")
             + files("node/services/*.initd") + files("hub/services/*.initd"))
    p = []
    for f in targets:
        r = subprocess.run(["sh", "-n", f], capture_output=True, text=True)
        if r.returncode:
            p.append("%s: %s" % (f, r.stderr.strip()))
    return p


@check("T2-bash", "no bashisms in node scripts")
def _():
    p = []
    for f in files("node/scripts/*.sh"):
        p += at(f, [h for h in grep(r"\[\[|^\s*local\s|<\(|\$RANDOM|\$\{[A-Za-z_]+,,", f) if not is_comment(h[1])])
    return p


@check("T2-sc", "ShellCheck (POSIX sh), known false positives allowlisted")
def _():
    sc = shutil.which("shellcheck") or next(iter(files(os.path.expanduser(
        "~/AppData/Local/Microsoft/WinGet/Packages/koalaman.shellcheck_*/shellcheck.exe"))), None)
    if not sc:
        raise Skip("shellcheck not found")
    targets = git_files("*.sh", "*.initd", "dev/shims/*")
    out = subprocess.run([sc, "-s", "sh", "-S", "warning", "-f", "gcc"] + targets,
                         capture_output=True, text=True).stdout.replace("\r", "")
    p = []
    for row in out.splitlines():
        m = re.match(r"(.+?):(\d+):\d+: \w+: (.*) \[(SC\d+)\]$", row)
        if not m:
            continue
        f, l, msg, code = m.group(1).replace("\\", "/"), int(m.group(2)), m.group(3), m.group(4)
        if code == "SC2034" and re.search(r"/services/.*\.initd$", f):
            continue
        if code in ("SC1113", "SC2096") and re.search(r"/services/confettictl-login-.*\.sh$", f):
            continue
        if code == "SC2163" and f == "hub/confettictl-run.sh":
            continue
        if code == "SC1010" and "-M do" in lines(f)[l - 1]:
            continue
        p.append("%s:%d %s %s" % (f, l, code, msg))
    return p


@check("T2-crlf", "no CRLF on disk in LF-pinned files")
def _():
    fs = git_files("*.sh", "*.initd", "*.py", "dev/shims/*", "node/services/crontab",
                   "node/services/*.conf", "node/config.sample", "hub/requirements.txt")
    return ["CRLF " + f for f in fs if b"\r" in open(f, "rb").read()]


# ============================================================ Tier 3

@check("T3-fields", "wire contract: fields emitted = fields consumed")
def _():
    emitted = set(re.findall(r'"([a-z_]+)":', read(CYCLE))) & (WIRE_FIELDS | {"source", "results"})
    emitted -= {"source", "results"}
    consumed = set(re.findall(r'r\.get\("([a-z_]+)"|text\(r, "([a-z_]+)"', read(APP)) and
                   [a or b for a, b in re.findall(r'r\.get\("([a-z_]+)"|text\(r, "([a-z_]+)"', read(APP))])
    p = []
    if emitted != WIRE_FIELDS:
        p.append("emitted fields differ: missing %s" % sorted(WIRE_FIELDS - emitted))
    if not WIRE_FIELDS <= consumed:
        p.append("hub no longer reads %s (if the access form changed, read push_results)"
                 % sorted(WIRE_FIELDS - consumed))
    return p


@check("T3-types", "test types agree: emitter, VALID_TESTS, TYPE_LABELS")
def _():
    p = []
    emitted = set(re.findall(r'"test_type":"([a-z0-9]+)"', read(CYCLE)))
    valid = set(re.findall(r'"(\w+)"', grep(r"^VALID_TESTS", APP)[0][1]))
    dash = read(DASH)
    labels = set(re.findall(r"(\w+):", re.search(r"var TYPE_LABELS = \{([\s\S]*?)\}", dash).group(1)))
    coarse = set(re.findall(r"(\w+):", re.search(r"var COARSE_TIMING = \{([^}]*)\}", dash).group(1)))
    pair = set(re.findall(r'"(\w+)"', re.search(r"var PAIR_TEST_TYPES = \[([^\]]*)\]", dash).group(1)))
    for name, s in (("confettictl-test-cycle.sh", emitted), ("VALID_TESTS", valid), ("TYPE_LABELS", labels)):
        if s != TEST_TYPES:
            p.append("%s: %s (want %s)" % (name, sorted(s), sorted(TEST_TYPES)))
    need("loss" not in coarse, "loss must not be in COARSE_TIMING", p)
    need("smtp" in coarse, "smtp must be in COARSE_TIMING", p)
    need("dns" not in pair, "PAIR_TEST_TYPES must omit dns", p)
    need(grep(r"Built from TYPE_LABELS", DASH), "legend no longer generated from TYPE_LABELS", p)
    return p


def py_text_between(text, start, end):
    i = text.find(start)
    j = text.find(end, i + 1) if i >= 0 else -1
    return text[i:j] if i >= 0 and j > i else ""


@check("R32", "flapping: same threshold on dashboard and node, flap_note never fails a cycle")
def _():
    p = []
    dash = re.search(r"var FLAP_MIN_FLIPS = (\d+)", read(DASH))
    node = re.search(r"^FLAP_MIN_FLIPS=(\d+)", read(CYCLE), re.M)
    need(dash and node and dash.group(1) == node.group(1),
         "FLAP_MIN_FLIPS differs: dashboard %s, node %s" % (dash and dash.group(1), node and node.group(1)), p)
    for fn in ("flap_note", "result_cell"):
        need(re.search(r"return 0\s*\n\}", sh_func(CYCLE, fn)),
             "%s must end with 'return 0' (a cycle must never fail on the console table)" % fn, p)
    calls = re.findall(r'result_cell "\$\w+" (?:bool|loss)(?: "[^"]+")?\)', read(CYCLE))
    need(len(calls) == 8 and all('"' in c.split(" ", 3)[-1] for c in calls),
         "all 8 console cells (4 mesh, 4 static) must pass a flap key to result_cell; found %d calls" % len(calls), p)
    need(grep(r"case \"\$ROWS\" in", CYCLE) and grep(r"= flapping", CYCLE),
         "console footer note for ~ is gone", p)
    need(grep(r"flapLookup\[src", DASH), "renderIndicators no longer reads flapLookup", p)
    need("ruleFor(" in py_text_between(read(DASH), "function flapMap", "function changeText"),
         "flapMap no longer skips excluded pairs", p)
    return p


@check("R32-run", "flap_note: flags the 5th flip, stays quiet when steady, history capped at 60")
def _():
    if not shutil.which("sh") or not shutil.which("jq"):
        raise Skip("needs sh and jq on PATH")
    tmp = tempfile.mkdtemp(prefix="confetti-flap-").replace("\\", "/")
    try:
        script = ("FLAP_DIR=%s\nFLAP_MIN_FLIPS=%s\n%s\n"
                  "for s in true false true false true false; do flap_note flip \"{\\\"success\\\":$s}\"; echo '|'; done\n"
                  "for i in 1 2 3 4 5 6 7 8; do flap_note steady '{\"success\":true}'; echo '|'; done\n"
                  "i=0; while [ $i -lt 70 ]; do flap_note cap \"{\\\"success\\\":$((i %% 2 == 0))}\" >/dev/null; i=$((i+1)); done\n"
                  % (tmp, re.search(r"^FLAP_MIN_FLIPS=(\d+)", read(CYCLE), re.M).group(1), sh_func(CYCLE, "flap_note")))
        out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=60)
        marks = [m.strip() for m in out.stdout.split("|")][:-1]
        p = []
        need(out.returncode == 0, "flap_note script exited %d: %s" % (out.returncode, out.stderr[:200]), p)
        need(marks[:6] == ["", "", "", "", "", "~"], "alternating samples gave %s, want ~ only on the 6th" % marks[:6], p)
        need(set(marks[6:]) == {""}, "steady passes were flagged: %s" % marks[6:], p)
        cap = open(tmp + "/cap").read().strip() if os.path.exists(tmp + "/cap") else ""
        need(len(cap) == 60, "history is %d long, want 60" % len(cap), p)
        return p
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ live tier

def http(method, url, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_live():
    tmp = tempfile.mkdtemp(prefix="confetti-regress-")
    hub_dir = os.path.join(tmp, "hub")
    shutil.copytree("hub", hub_dir, ignore=shutil.ignore_patterns("__pycache__", "agent", "*.db*"))
    os.makedirs(os.path.join(hub_dir, "agent"))
    for s in (REGISTER, CYCLE):
        shutil.copy(s, os.path.join(hub_dir, "agent"))
    port, sport = free_port(), free_port()
    db = os.path.join(tmp, "hub.db")
    env = dict(os.environ, HUB_DB_PATH=db, HUB_PORT=str(port), HUB_SYSLOG_PORT=str(sport),
               PYTHONDONTWRITEBYTECODE="1")
    log = open(os.path.join(tmp, "hub.log"), "w")
    proc = subprocess.Popen([sys.executable, "serve.py"], cwd=hub_dir, env=env, stdout=log, stderr=log)
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(50):
            try:
                if http("GET", base + "/api/time")[0] == 200:
                    break
            except Exception:
                time.sleep(0.2)
        else:
            for cid, desc in LIVE:
                results.append(("NOT RUN", cid, desc, ["scratch hub did not start; see its log"]))
            return
        live_checks(base, db, tmp)
    finally:
        proc.kill()
        proc.wait()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


LIVE = [("T2-live", "real node cycle posts to a live hub"),
        ("R2-live", "timestamps leave the hub as ISO-8601 Z"),
        ("R9-live", "hub still rejects latency_ms 0000"),
        ("R33-live", "group override beats register, drives mesh rules, dies with the endpoint"),
        ("R18-live", "syslog window and filter input"),
        ("R19-live", "null row keeps the batch; bad bodies get 400"),
        ("R21", "/api/time answers 200 on every chrony failure"),
        ("R22-live", "correlation window round trip"),
        ("R29-live", "every hub page answers 200 and links to the others")]


def live_checks(base, db, tmp):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    @check("T2-live", "real node cycle posts to a live hub")
    def _():
        if not shutil.which("sh") or not shutil.which("curl") or not shutil.which("jq"):
            raise Skip("needs sh, curl and jq on PATH")
        p = []
        for name, ip in (("rt-node-a", "10.99.1.11"), ("rt-node-b", "10.99.1.12")):
            nd = os.path.join(tmp, "nodes", name).replace("\\", "/")
            os.makedirs(nd + "/run")
            with open(nd + "/config", "w", newline="\n") as f:
                f.write("HUB_URL=%s\nGROUP_NAME=rt\nSUBNET=10.99.1.0/24\nENABLE_SMB=true\n"
                        "ENABLE_SMTP=true\nDNS_SERVER=10.99.1.53\nDNS_QUERY=example.com\n"
                        "CONSOLE_OUTPUT=false\nAGENT_AUTOUPDATE=false\n" % base)
            # Only the OS-root paths are redirected; script logic is unmodified.
            subs = {REGISTER: [("CONFIG", nd + "/config")],
                    CYCLE: [("CONFIG", nd + "/config"), ("LOCK_DIR", nd + "/run/lock"),
                            ("TRACEROUTE_STAMP", nd + "/run/last-traceroute")]}
            for src, pairs in subs.items():
                text = read(src)
                for var, val in pairs:
                    text, k = re.subn(r'^%s="/[^"]*"' % var, '%s="%s"' % (var, val), text, count=1, flags=re.M)
                    need(k == 1, "%s: could not redirect %s" % (src, var), p)
                with open(nd + "/" + os.path.basename(src), "w", newline="\n") as f:
                    f.write(text)
            env = dict(os.environ, PATH=os.path.join(ROOT, "dev", "shims") + os.pathsep + os.environ["PATH"],
                       DEV_HOSTNAME=name, DEV_IP=ip, SNAPSHOT_FILE=nd + "/run/last-cycle.txt")
            for script in ("confettictl-register.sh", "confettictl-register.sh", "confettictl-test-cycle.sh"):
                r = subprocess.run(["sh", nd + "/" + script], env=env, capture_output=True, text=True, timeout=240)
                if script == "confettictl-test-cycle.sh" and r.returncode:
                    p.append("%s confettictl-test-cycle.sh exit %d: %s" % (name, r.returncode, (r.stdout + r.stderr)[-400:]))
        code, body = http("GET", base + "/api/results?minutes=10")
        rows = json.loads(body) if code == 200 else []
        for name in ("rt-node-a", "rt-node-b"):
            mine = [r for r in rows if r.get("source_hostname") == name or r.get("source") == name]
            need(mine, "no results from %s reached the hub (strict JSON parse or push failed)" % name, p)
        bad = {r.get("test_type") for r in rows} - TEST_TYPES
        need(not bad, "unknown test types stored: %s" % sorted(bad), p)
        return p

    @check("R2-live", "timestamps leave the hub as ISO-8601 Z")
    def _():
        p = []
        rows = json.loads(http("GET", base + "/api/results?minutes=10")[1])
        eps = json.loads(http("GET", base + "/endpoints")[1])
        if not rows or not eps:
            raise Skip("no results/endpoints from the node cycle")
        need(all(r["received_at"].endswith("Z") for r in rows), "/api/results received_at not ISO-Z", p)
        need(all(e["last_seen"].endswith("Z") for e in eps), "/endpoints last_seen not ISO-Z", p)
        r0 = rows[0]
        src = r0.get("source_hostname") or r0.get("source")
        pair = json.loads(http("GET", "%s/api/results/%s/%s" % (base, src, r0["target_hostname"]))[1])
        need(pair and all(r["received_at"].endswith("Z") for r in pair), "pair route received_at not ISO-Z", p)
        return p

    @check("R9-live", "hub still rejects latency_ms 0000")
    def _():
        raw = (b'{"source":"rt9","results":[{"target_hostname":"a","target_ip":"1",'
               b'"test_type":"ssh","success":true,"latency_ms":0000}]}')
        code = http("POST", base + "/results", raw=raw)[0]
        return [] if code == 400 else ["latency_ms:0000 returned %d, want 400" % code]

    @check("R19-live", "null row keeps the batch; bad bodies get 400")
    def _():
        p = []
        batch = {"source": "rt19", "results": [
            {"target_hostname": "a", "target_ip": "1", "test_type": "ssh", "success": True},
            {"target_hostname": None, "target_ip": None, "test_type": "http", "success": False},
            {"target_hostname": "c", "target_ip": "3", "test_type": "pmtu", "success": True}]}
        code = http("POST", base + "/results", batch)[0]
        need(code == 200, "null-row batch returned %d, want 200" % code, p)
        rows = json.loads(http("GET", base + "/api/results?minutes=10")[1])
        n = len([r for r in rows if (r.get("source_hostname") or r.get("source")) == "rt19"])
        need(n == 3, "null-row batch stored %d rows, want 3" % n, p)
        for raw in (b"[]", b'{"results":"nope"}', b"[42]", b"{not json"):
            c = http("POST", base + "/results", raw=raw)[0]
            need(c == 400, "body %r returned %d, want 400" % (raw, c), p)
        return p

    @check("R30-live", "mesh rules filter /endpoints?for= and fail open to full mesh")
    def _():
        p = []
        hosts = (("rt30a", "rt30-g1"), ("rt30b", "rt30-g1"), ("rt30c", "rt30-g2"))
        for h, g in hosts:
            http("POST", base + "/register", {"hostname": h, "ip": "10.30.0.1",
                                              "subnet": "10.30.0.0/24", "group_name": g})

        def names(q):
            code, body = http("GET", base + "/endpoints" + q)
            rows = json.loads(body) if code == 200 else None
            need(isinstance(rows, list), "/endpoints%s is not a bare array" % q, p)
            return {r["hostname"] for r in rows or []} & {"rt30a", "rt30b", "rt30c"}

        code = http("POST", base + "/mesh-rules", {"group_a": "rt30-g2", "group_b": "rt30-g1"})[0]
        need(code == 200, "POST /mesh-rules returned %d" % code, p)
        need(names("?for=rt30a") == {"rt30a", "rt30b"}, "?for=rt30a still lists the excluded group", p)
        need(names("?for=rt30c") == {"rt30c"}, "?for=rt30c lists peers from the excluded group", p)
        need(len(names("")) == 3, "/endpoints without for= is filtered", p)
        need(len(names("?for=nobody-here")) == 3, "unknown for= host is filtered (must be full mesh)", p)
        for raw in (b"[]", b'{"group_a":"","group_b":"x"}', b'{"group_a":1,"group_b":"x"}',
                    json.dumps({"group_a": "x" * 65, "group_b": "y"}).encode(), b"{not json"):
            c = http("POST", base + "/mesh-rules", raw=raw)[0]
            need(c == 400, "POST /mesh-rules %r returned %d, want 400" % (raw[:40], c), p)
        c = http("DELETE", base + "/mesh-rules?a=rt30-g1&b=rt30-g2")[0]
        need(c == 200, "DELETE /mesh-rules returned %d" % c, p)
        need(names("?for=rt30a") == {"rt30a", "rt30b", "rt30c"}, "rule removal did not restore full mesh", p)
        c = http("DELETE", base + "/mesh-rules?a=rt30-g1&b=rt30-g2")[0]
        need(c == 404, "deleting a missing rule returned %d, want 404" % c, p)
        for h, _g in hosts:
            http("DELETE", base + "/endpoints/" + h)
        return p

    @check("R33-live", "group override beats register, drives mesh rules, dies with the endpoint")
    def _():
        p = []
        hosts = ("rt33a", "rt33b")

        def reg(h, g):
            http("POST", base + "/register", {"hostname": h, "ip": "10.33.0.1",
                                              "subnet": "10.33.0.0/24", "group_name": g})

        def row(h):
            rows = json.loads(http("GET", base + "/endpoints")[1])
            return next((r for r in rows if r["hostname"] == h), {})

        def peers(h):
            rows = json.loads(http("GET", base + "/endpoints?for=" + h)[1])
            return {r["hostname"] for r in rows} & set(hosts)

        for h in hosts:
            reg(h, "rt33-g1")
        c = http("POST", base + "/api/nodes/rt33b/group", {"group": "rt33-g2"})[0]
        need(c == 200, "POST group override returned %d" % c, p)
        r = row("rt33b")
        need((r.get("group_name"), r.get("group_overridden"), r.get("group_registered")) ==
             ("rt33-g2", True, "rt33-g1"), "override not applied in /endpoints: %s" % r, p)
        reg("rt33b", "rt33-g1")
        need(row("rt33b").get("group_name") == "rt33-g2", "a re-register overwrote the override", p)
        # Mesh rules read the overridden group: same registered group, so only the override can exclude.
        http("POST", base + "/mesh-rules", {"group_a": "rt33-g1", "group_b": "rt33-g2"})
        need(peers("rt33a") == {"rt33a"}, "mesh rule did not follow the override", p)
        http("DELETE", base + "/mesh-rules?a=rt33-g1&b=rt33-g2")
        for raw in (b"[]", b"{not json", json.dumps({"group": "x" * 65}).encode(),
                    json.dumps({"group": "bad\x07group"}).encode()):
            c = http("POST", base + "/api/nodes/rt33b/group", raw=raw)[0]
            need(c == 400, "bad group body %r returned %d, want 400" % (raw[:30], c), p)
        need(row("rt33b").get("group_name") == "rt33-g2", "a rejected request changed the override", p)
        c = http("POST", base + "/api/nodes/rt33-nobody/group", {"group": "x"})[0]
        need(c == 404, "unknown host returned %d, want 404" % c, p)
        http("POST", base + "/api/nodes/rt33b/group", {"group": ""})
        r = row("rt33b")
        need((r.get("group_name"), r.get("group_overridden")) == ("rt33-g1", False),
             "an empty group did not clear the override: %s" % r, p)
        http("POST", base + "/api/nodes/rt33b/group", {"group": "rt33-g2"})
        http("DELETE", base + "/endpoints/rt33b")
        reg("rt33b", "rt33-g1")
        need(row("rt33b").get("group_overridden") is False, "override survived DELETE /endpoints", p)
        for h in hosts:
            http("DELETE", base + "/endpoints/" + h)
        return p

    @check("R18-live", "syslog window and filter input")
    def _():
        p = []
        http("GET", base + "/api/syslog?minutes=5")
        q = "from=1970-01-01T00:00:00Z&to=1970-01-02T00:00:00Z"
        con = sqlite3.connect(db)
        now = datetime.now(timezone.utc)
        con.execute("INSERT INTO syslog (received_at,source_ip,host,message) VALUES (?,?,?,?)",
                    (now.strftime("%Y-%m-%d %H:%M:%S"), "10.0.0.9", "RT18", "now"))
        con.commit()
        con.close()
        rows = json.loads(http("GET", base + "/api/syslog?minutes=5")[1])
        need(rows and rows[0]["received_at"].endswith("Z"), "/api/syslog received_at not ISO-Z", p)
        n = len(json.loads(http("GET", base + "/api/syslog?" + q)[1]))
        need(n == 0, "a 1970 window returned %d rows (format bug)" % n, p)
        for a in ("severity=xyz", "severity=all", "minutes=abc", "limit=abc", "from=garbage"):
            c = http("GET", base + "/api/syslog?" + a)[0]
            need(c == 200, "/api/syslog?%s returned %d" % (a, c), p)
        return p

    @check("R22-live", "correlation window round trip")
    def _():
        pin = int(re.search(r"SYSLOG_PIN_MINUTES *= *(\d+)", read(DASH)).group(1))
        now = datetime.now(timezone.utc)
        con = sqlite3.connect(db)
        con.execute("DELETE FROM syslog")
        con.executemany("INSERT INTO syslog (received_at,source_ip,host,message) VALUES (?,?,?,?)",
                        [(now.strftime("%Y-%m-%d %H:%M:%S"), "10.0.0.1", "SW1", "inside"),
                         ((now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"), "10.0.0.2", "SW2", "outside")])
        con.commit()
        con.close()
        z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
        frm, to = z(now - timedelta(minutes=pin)), z(now + timedelta(minutes=pin))
        shifted = now - timedelta(minutes=pin) + timedelta(hours=2)
        offset = urllib.request.quote(shifted.strftime("%Y-%m-%dT%H:%M:%S") + "+02:00")
        n = lambda qs: len(json.loads(http("GET", base + "/api/syslog?" + qs)[1]))
        got = [n("from=%s&to=%s" % (frm, to)), n("from=%s&to=%s&host=SW1" % (frm, to)),
               n("from=%s&to=%s&host=SW2" % (frm, to)), n("from=%s&to=%s" % (z(shifted), to)),
               n("from=%s&to=%s" % (offset, to))]
        return [] if got == [1, 1, 0, 0, 1] else ["counts %s, want [1, 1, 0, 0, 1]" % got]

    @check("R29-live", "every hub page answers 200 and links to the others")
    def _():
        pages = {"/": ("/syslog", "/timeline"), "/syslog": ("/", "/timeline"), "/timeline": ("/", "/syslog")}
        p = []
        for path, links in pages.items():
            code, body = http("GET", base + path)
            if code != 200:
                p.append("%s answered %s" % (path, code))
                continue
            for link in links:
                if 'href="%s"' % link not in body:
                    p.append("%s has no nav link to %s" % (path, link))
        return p

    @check("R21", "/api/time answers 200 on every chrony failure")
    def _():
        sys.path.insert(0, os.path.join(tmp, "hub"))
        os.environ.update(HUB_SYSLOG_ENABLED="false", HUB_DB_PATH=os.path.join(tmp, "r21.db"))
        from app.app import app
        import app.app as A

        good = ("Reference ID    : C0A80001 (10.0.0.1)\nStratum         : 3\n"
                "System time     : 0.000000012 seconds fast of NTP time\nLeap status     : Normal\n")
        slow = good.replace("seconds fast", "seconds slow")
        unsync = good.replace(": Normal", ": Not synchronised")

        class P:
            def __init__(s, rc, out="", err=""):
                s.returncode, s.stdout, s.stderr = rc, out, err

        def raiser(e):
            def f(*a, **k):
                raise e
            return f

        def hit(which, run):
            A.shutil.which = lambda n: which
            A.subprocess.run = run
            r = app.test_client().get("/api/time")
            return r.status_code, r.get_json()

        cases = [("absent", None, lambda *a, **k: P(0, good)),
                 ("timeout", "/c", raiser(subprocess.TimeoutExpired("chronyc", 2))),
                 ("unrunnable", "/c", raiser(OSError("nope"))),
                 ("daemon down", "/c", lambda *a, **k: P(1, "", "506 Cannot talk to daemon")),
                 ("unrecognised", "/c", lambda *a, **k: P(0, "hello")),
                 ("disciplined", "/c", lambda *a, **k: P(0, good)),
                 ("slow", "/c", lambda *a, **k: P(0, slow)),
                 ("unsynced", "/c", lambda *a, **k: P(0, unsync))]
        real_which, real_run = A.shutil.which, A.subprocess.run
        p = []
        try:
            for name, which, run in cases:
                code, j = hit(which, run)
                if code != 200:
                    p.append("%s: HTTP %d" % (name, code))
                    continue
                need((j.get("utc") or "").endswith("Z"), "%s: utc not ISO-Z" % name, p)
                need(j.get("chrony") is not None or j.get("reason"), "%s: null chrony, no reason" % name, p)
                need(j.get("chrony") is None or not j.get("reason"), "%s: tracking AND reason" % name, p)
            g = hit("/c", lambda *a, **k: P(0, good))[1]["chrony"]
            s = hit("/c", lambda *a, **k: P(0, slow))[1]["chrony"]
            u = hit("/c", lambda *a, **k: P(0, unsync))[1]["chrony"]
            need(g["stratum"] == 3, "stratum not parsed", p)
            need(g["synced"] is True, "Leap Normal not synced", p)
            need(g["system_offset_s"] > 0, "fast must be positive", p)
            need(s["system_offset_s"] < 0, "slow must be negative", p)
            need(u["synced"] is False, "Not synchronised must not be synced", p)
            need(A.parse_chrony_tracking("hello") is None, "garbage must parse to None", p)
        finally:
            A.shutil.which, A.subprocess.run = real_which, real_run
        return p


# ============================================================ run

def tree_state():
    return (sorted(files("**/__pycache__", recursive=True)), os.path.isdir("hub/agent"))


before = tree_state()
if STATIC_ONLY:
    for cid, desc in LIVE:
        results.append(("NOT RUN", cid, desc, ["--static"]))
else:
    try:
        run_live()
    except Exception as e:
        results.append(("FAIL", "live", "live tier", ["crashed: %r" % e]))
after = tree_state()
if after != before:
    results.append(("FAIL", "clean", "run left files in the tree",
                    ["before %s, after %s" % (before, after)]))

fails = [r for r in results if r[0] == "FAIL"]
gaps = [r for r in results if r[0] == "NOT RUN"]
for status, cid, desc, detail in results:
    print("%-8s %-9s %s" % (status, cid, desc))
    if status != "PASS" or VERBOSE:
        for d in detail:
            print("           " + d)
verdict = "BLOCKED" if fails else ("CLEAR WITH GAPS" if gaps else "CLEAR")
print("\n%s - %d checks, %d failed, %d not run" % (verdict, len(results), len(fails), len(gaps)))
sys.exit(1 if fails else 0)
