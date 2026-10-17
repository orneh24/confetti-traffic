"""Recent Changes, hub-side: a log of TRANSITIONS, not raw results.

This is a Python copy of computeRecentChanges() in templates/dashboard.html,
written for the console script (confettictl-changes, via GET /api/changes).
The dashboard keeps its own JS version. Change the rules in one place and you
must change the other; dev/regress.py has a fixture check for this side.

Pure stdlib, never raises: bad input degrades to "no changes".
"""

# Same labels as TYPE_NAMES in dashboard.html.
TYPE_NAMES = {
    "http": "HTTP", "ssh": "SSH", "traceroute": "Trace", "pmtu": "PMTU",
    "dns": "DNS", "smb": "SMB", "iperf3": "iperf", "loss": "Loss",
    "smtp": "SMTP",
}


def compute(rows, path_rows, group_of, excluded, limit=15):
    """Newest-first list of changes.

    rows       results: dicts with source, target, test_type, success, received_at
    path_rows  detected path changes: source, target, received_at, detail
    group_of   {hostname: group}; a host with no group is never excluded
    excluded   set of sorted (group, group) pairs (mesh rules)
    Kinds: "flip" (a pass/fail toggle), "all-down" (a batch where every test
    that ran flipped to FAIL, collapsed into one row), "all-up" (4+ tests
    flipped to PASS in one batch, collapsed into one row), "path".
    received_at stays in SQLite's format; sorting it as text is chronological.
    """
    try:
        def skip(src, dst):
            ga, gb = group_of.get(src), group_of.get(dst)
            return ga is not None and gb is not None and tuple(sorted((ga, gb))) in excluded

        by_pair_type, batch_types = {}, {}
        for r in rows:
            if skip(r["source"], r["target"]):
                continue
            by_pair_type.setdefault((r["source"], r["target"], r["test_type"]), []).append(r)
            batch_types.setdefault((r["source"], r["target"], r["received_at"]), set()).add(r["test_type"])

        changes, down_by_batch, up_by_batch = [], {}, {}
        for key, arr in by_pair_type.items():
            arr.sort(key=lambda x: x["received_at"])
            for i in range(1, len(arr)):
                if bool(arr[i]["success"]) == bool(arr[i - 1]["success"]):
                    continue
                flip = {"received_at": arr[i]["received_at"], "source": key[0], "target": key[1],
                        "kind": "flip", "test_type": key[2], "to": bool(arr[i]["success"])}
                batch = up_by_batch if flip["to"] else down_by_batch
                batch.setdefault((key[0], key[1], flip["received_at"]), []).append(flip)

        # More than 3 tests recovering in the same batch is one event, not a row per test.
        for flips in up_by_batch.values():
            if len(flips) > 3:
                changes.append({"received_at": flips[0]["received_at"], "source": flips[0]["source"],
                                "target": flips[0]["target"], "kind": "all-up", "count": len(flips)})
            else:
                changes.extend(flips)

        # Every test type that ran also flipped to FAIL: a target going dark.
        # One type alone is an ordinary flip; "ALL" needs 2+ to agree.
        for bkey, flips in down_by_batch.items():
            if len(flips) >= 2 and len(flips) == len(batch_types.get(bkey, ())):
                changes.append({"received_at": flips[0]["received_at"], "source": flips[0]["source"],
                                "target": flips[0]["target"], "kind": "all-down", "count": len(flips)})
            else:
                changes.extend(flips)

        for p in path_rows:
            if skip(p["source"], p["target"]):
                continue
            changes.append({"received_at": p["received_at"], "source": p["source"],
                            "target": p["target"], "kind": "path", "detail": p["detail"]})

        changes.sort(key=lambda c: c["received_at"], reverse=True)
        return changes[:limit]
    except Exception:
        return []


def text(c):
    """One change as plain text, e.g. 'SSH: PASS -> FAIL'."""
    try:
        if c["kind"] == "all-down":
            return "ALL tests FAILED (%d tests)" % c["count"]
        if c["kind"] == "all-up":
            return "%d tests PASSED again" % c["count"]
        if c["kind"] == "path":
            return "Traceroute path changed: %s" % c["detail"]
        name = TYPE_NAMES.get(c["test_type"], c["test_type"])
        return "%s: %s" % (name, "FAIL -> PASS" if c["to"] else "PASS -> FAIL")
    except Exception:
        return ""
