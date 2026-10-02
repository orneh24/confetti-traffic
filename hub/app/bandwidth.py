"""On-demand bandwidth tests, started from the dashboard.

Two kinds, one at a time mesh-wide (they saturate the path, and a second
test running alongside would only measure the first):

- node: the hub logs in to both nodes with its management key (the same
  one push-update uses). It starts a one-off iperf3 server on the target on
  BW_PORT -- not 5201, so it never collides with the scheduled iperf3 test
  -- then runs the client on the source twice: forward (source sends) and
  reverse (-R, target sends). Both nodes must be managed.
- browser: the dashboard's JavaScript talks to the node's /cgi-bin/confettictl-bw
  directly (node/web/cgi-bin/confettictl-bw), so the path measured is the viewer's
  own. The hub only hands out the slot and stores what the browser reports.

Results go in the bwtests table (last HISTORY_ROWS runs). "fwd" is always
from -> to, "rev" to -> from; for a browser test "from" is the node, so fwd
is the download and rev the upload.
"""

import json
import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone

from . import config
from . import nodemgmt

BW_PORT = 5202
# "[5]202", not "5202": pkill -f matches full command lines, and the remote
# shell running this pkill has the pattern in its own. The bracket form
# matches the iperf3 server's "5202" but not the literal "[5]202", so the
# session doesn't kill itself. Never send it in the same command as the
# server start, whose literal "iperf3 -s -p 5202" it would match.
KILL_SERVER = "pkill -f 'iperf3 -s -p [5]202' 2>/dev/null"
MAX_DURATION = 30
MAX_STREAMS = 8
HISTORY_ROWS = 200
PATH_PREFIX = "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; export PATH; "

_lock = threading.Lock()
# The one test allowed to run: {"id": int, "expires": monotonic seconds}.
# Expiry covers a browser that closed mid-test and never reported back.
_active = None


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    db = sqlite3.connect(config.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout={:d}".format(config.BUSY_TIMEOUT_MS))
    return db


def claim(db, kind, src, dst, duration, streams):
    """Insert a running row and take the slot; None if a test is running."""
    global _active
    with _lock:
        if _active and _active["expires"] > time.monotonic():
            return None
        cur = db.execute(
            """INSERT INTO bwtests (started_at, kind, src, dst, duration, streams, state)
               VALUES (?, ?, ?, ?, ?, ?, 'running')""",
            (_now(), kind, src, dst, duration, streams),
        )
        # Covers two directions plus iperf3/ssh startup and the browser's
        # round trip, generously; a stuck test frees the slot eventually.
        _active = {"id": cur.lastrowid, "expires": time.monotonic() + 2 * duration + 60}
        db.execute("DELETE FROM bwtests WHERE id <= ?", (cur.lastrowid - HISTORY_ROWS,))
        db.commit()
        return cur.lastrowid


def finish(db, test_id, state, fwd=None, rev=None, msg=""):
    global _active
    db.execute(
        """UPDATE bwtests SET state = ?, fwd_mbps = ?, rev_mbps = ?, msg = ?, finished_at = ?
           WHERE id = ? AND state = 'running'""",
        (state, fwd, rev, msg[:600], _now(), test_id),
    )
    db.commit()
    with _lock:
        if _active and _active["id"] == test_id:
            _active = None


def is_active(test_id):
    with _lock:
        return bool(_active and _active["id"] == test_id and _active["expires"] > time.monotonic())


def _ssh(ip, cmd, timeout):
    return subprocess.run(
        ["ssh", "-i", nodemgmt.key_path(),
         "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
         "-o", "ConnectTimeout=10", "root@" + ip, PATH_PREFIX + cmd],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _iperf(src_ip, dst_ip, duration, streams, reverse):
    """Mbit/s received, from iperf3's JSON; raises RuntimeError with a reason."""
    cmd = "iperf3 -c {} -p {} -t {:d} -P {:d} -J{}".format(
        dst_ip, BW_PORT, duration, streams, " -R" if reverse else "")
    proc = _ssh(src_ip, cmd, duration + 40)
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        raise RuntimeError("iperf3 gave no result: " +
                           (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()[-200:])
    if data.get("error"):
        raise RuntimeError("iperf3: " + str(data["error"]))
    return round(data["end"]["sum_received"]["bits_per_second"] / 1e6, 1)


def start_node_test(test_id, src_ip, dst_ip, duration, streams):
    threading.Thread(target=_run_node_test, name="bw-test", daemon=True,
                     args=(test_id, src_ip, dst_ip, duration, streams)).start()


def _run_node_test(test_id, src_ip, dst_ip, duration, streams):
    db = _connect()
    fwd = rev = None
    try:
        if not os.path.isfile(nodemgmt.key_path()):
            raise RuntimeError("hub has no management key")
        # A one-off server on the target, gone by itself after the window
        # even if the hub dies mid-test. All fds redirected so the SSH
        # session returns at once instead of waiting on the background job.
        # Separate calls: a command line holding both the kill and the start
        # would itself match the kill pattern.
        _ssh(dst_ip, KILL_SERVER + "; true", 20)
        srv = _ssh(dst_ip,
                   "nohup timeout {t} iperf3 -s -p {p} </dev/null >/dev/null 2>&1 & "
                   "sleep 1; echo started".format(p=BW_PORT, t=2 * duration + 40), 30)
        if b"started" not in srv.stdout:
            raise RuntimeError("could not start iperf3 on the target: " +
                               srv.stderr.decode("utf-8", "replace").strip()[-200:])
        fwd = _iperf(src_ip, dst_ip, duration, streams, reverse=False)
        rev = _iperf(src_ip, dst_ip, duration, streams, reverse=True)
        finish(db, test_id, "ok", fwd, rev)
    except (RuntimeError, subprocess.TimeoutExpired, OSError, KeyError) as exc:
        finish(db, test_id, "failed", fwd, rev, str(exc))
    finally:
        try:
            _ssh(dst_ip, KILL_SERVER + "; true", 20)
        except (subprocess.TimeoutExpired, OSError):
            pass
        db.close()
