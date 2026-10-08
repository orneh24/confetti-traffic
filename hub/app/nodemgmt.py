"""Push-update: run confettictl-update on nodes over SSH, one at a time.

The dashboard queues a node (or all of them); a single background thread
works through the queue, so "update all" goes one node after another and a
slow node never has two updates running at once. State lives in the
endpoints table (update_state / update_msg / update_at) so the dashboard
just reads /endpoints to show progress.

The node side is confettictl-update.sh: it downloads this hub's node bundle, applies it
and re-runs confettictl-setup.sh. The SSH login uses the hub's management key, which
nodes pin on first use (node/scripts/confettictl-trust-hub.sh).

Host keys are not checked (StrictHostKeyChecking=no, like confettictl-test-cycle.sh's
SSH test): nodes are DHCP and get rebuilt, so a known_hosts file would
churn into failures. An impostor at a node's address gains nothing from
the connection -- key auth never exposes the private key -- beyond being
told to run confettictl-update.
"""

import os
import queue
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone

from . import config

REMOTE_CMD = ("PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
              "export PATH; confettictl-update -y")

# Group rename: the new group arrives on stdin, never on the command line, so
# no quoting of operator input can reach a root shell. confettictl-setup.sh
# derives ct-<group>-<NODE_ID>, renames the node and has the hub drop the old
# name. A name set explicitly (NODE_HOSTNAME) is left alone; checked first so
# a refused rename changes nothing.
REMOTE_RENAME_CMD = (
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; export PATH; "
    "C=/etc/confetti/config; read -r G; "
    "if grep -q '^NODE_HOSTNAME=.' $C; then "
    "echo 'hostname is set in the node config; not renamed'; exit 3; fi; "
    "sed -i '/^GROUP_NAME=/d' $C && printf 'GROUP_NAME=%s\\n' \"$G\" >> $C && "
    "/usr/local/bin/confetti/confettictl-setup.sh >/dev/null 2>&1; "
    "R=$?; echo \"hostname: $(hostname)\"; exit $R"
)

_queue = queue.Queue()
_lock = threading.Lock()
_thread = None


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    db = sqlite3.connect(config.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout={:d}".format(config.BUSY_TIMEOUT_MS))
    return db


def _set_state(db, hostname, state, msg=""):
    db.execute(
        "UPDATE endpoints SET update_state = ?, update_msg = ?, update_at = ? WHERE hostname = ?",
        (state, msg, _now(), hostname),
    )
    db.commit()


def key_path():
    return os.path.join(config.KEY_DIR, "id_hub")


def eligible(row):
    """None if this endpoint row can be pushed to, else the reason it can't."""
    if row["managed"] != "true":
        return "not managed by the hub" if row["managed"] == "false" else "node does not report hub management"
    if not row["recent"]:
        return "not seen in the last {} minutes".format(config.PUSH_SEEN_MINUTES)
    if row["update_state"] in ("queued", "running"):
        return "update already " + row["update_state"]
    return None


def enqueue(db, hostname, group=None):
    """Mark queued and hand to the worker. Caller has checked eligible().

    With a group, the job renames the node to that group instead of updating.
    """
    _set_state(db, hostname, "queued")
    _ensure_worker()
    _queue.put((hostname, group))


def _ensure_worker():
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name="push-update", daemon=True)
            _thread.start()


def _worker():
    while True:
        hostname, group = _queue.get()
        try:
            _run(hostname, group)
        except Exception as exc:  # never let one node kill the worker
            try:
                db = _connect()
                _set_state(db, hostname, "failed", "hub error: {}".format(exc))
                db.close()
            except sqlite3.Error:
                pass


def _tail(text, limit=600):
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _run(hostname, group=None):
    db = _connect()
    try:
        row = db.execute("SELECT ip FROM endpoints WHERE hostname = ?", (hostname,)).fetchone()
        if row is None:
            return  # deleted while queued
        if not os.path.isfile(key_path()):
            _set_state(db, hostname, "failed", "hub has no management key ({})".format(key_path()))
            return
        _set_state(db, hostname, "running")
        cmd = [
            "ssh", "-i", key_path(),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=10",
            "root@" + row["ip"], REMOTE_RENAME_CMD if group else REMOTE_CMD,
        ]
        try:
            proc = subprocess.run(cmd, input=(group + "\n").encode() if group else b"",
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=config.PUSH_TIMEOUT_S)
        except FileNotFoundError:
            _set_state(db, hostname, "failed", "ssh not installed on the hub")
            return
        except subprocess.TimeoutExpired:
            _set_state(db, hostname, "failed", "timed out after {}s".format(config.PUSH_TIMEOUT_S))
            return
        out = _tail(proc.stdout.decode("utf-8", "replace"))
        if proc.returncode == 0:
            _set_state(db, hostname, "ok", out)
        elif proc.returncode == 255:
            _set_state(db, hostname, "failed",
                       "SSH to {} failed (hub key not pinned on the node?): {}".format(row["ip"], out))
        else:
            _set_state(db, hostname, "failed", "exit {}: {}".format(proc.returncode, out))
    finally:
        db.close()
