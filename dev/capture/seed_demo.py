"""Seed the dev hub with the synthetic 5-node README scene.

Rounds are POSTed through the real API (so path-change detection runs), then
backdated in SQLite so the dashboard history and timeline have depth.
"""
import json, os, socket, sqlite3, time, urllib.request

HUB = "http://127.0.0.1:8099"
DB = os.environ.get("SEED_DB", "dev/run/hub.db")
SYSLOG = ("127.0.0.1", 5514)
ROUNDS = 20              # one per minute, oldest first
NODES = [("node-%d" % i, "10.%d.1.10" % i, "site-" + "abcde"[i - 1]) for i in range(1, 6)]
BROKEN = ("node-3", "node-5")
BROKEN_FROM = ROUNDS - 2                 # last two rounds fail
FLAP = ("node-1", "node-4", 7)           # one earlier SSH blip, recovered
# Flapping tests (5+ flips in the hour shows the stripes and "~"): (src, dst, test, failing rounds).
FLAPS = [
    ("node-2", "node-4", "ssh", (8, 10, 12, 14)),
    ("node-1", "node-2", "http", (9, 11, 13, 15)),
    ("node-4", "node-1", "ssh", (6, 8, 10, 12, 14)),
    ("node-5", "node-2", "smb", (10, 12, 14, 16)),
]


def post(path, body):
    req = urllib.request.Request(HUB + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()


def trace(si, di, broken):
    if broken:
        return (" 1  10.%d.1.1  0.41 ms\n 2  10.0.45.%d  1.92 ms\n 3  *\n 4  *" % (si, si))
    return (" 1  10.%d.1.1  0.38 ms\n 2  10.0.35.%d  1.12 ms\n 3  10.%d.1.10  1.64 ms"
            % (si, si, di))


def results(rnd, src, sip):
    si = int(sip.split(".")[1])
    out = []
    for dst, dip, _ in NODES:
        if dst == src:
            continue
        di = int(dip.split(".")[1])
        broken = (src, dst) == BROKEN and rnd >= BROKEN_FROM
        def flaps(t):
            return any((src, dst, t) == f[:3] and rnd in f[3] for f in FLAPS)

        blip = (src, dst) == FLAP[:2] and rnd == FLAP[2]
        flap = blip or any((src, dst) == f[:2] and rnd in f[3] for f in FLAPS)
        ok = not broken

        def r(t, success, ms, text):
            out.append({"target_hostname": dst, "target_ip": dip, "test_type": t,
                        "success": success, "latency_ms": ms, "output": text})

        hok = ok and not flaps("http")
        r("http", hok, 4.2 + si * 0.3 if hok else 5001.0,
          "probe site: 5 files OK" if hok else "index.html: timeout after 5s")
        sok = ok and not (blip or flaps("ssh"))
        r("ssh", sok, 0 if sok else 5000,
          "ok" if sok else "ssh: connect to host %s port 22: Connection timed out" % dip)
        if rnd % 5 == 0 or broken or flap:
            r("traceroute", ok, 0 if ok else 20000, trace(si, di, broken))
        r("pmtu", ok, 0 if ok else 2000,
          "1500 bytes OK (DF set)" if ok else "no reply at 1472/1400/1200/576 bytes")
        mok = ok and not flaps("smb")
        r("smb", mok, 1000 if mok else 10000,
          "probe.bin 8388608 bytes OK" if mok else "smbclient: NT_STATUS_IO_TIMEOUT")
        r("smtp", ok, 0 if ok else 5000,
          "220 banner, 250 EHLO, RCPT 250" if ok else "no banner within 5s")
        r("loss", ok, 0.6 if ok else None,
          "Loss: 0%% avg/min/max: 0.6%d/0.41/1.2 ms" % si if ok else "Loss: 100% (no replies)")
    if src == "node-1":
        out.append({"target_hostname": "10.0.0.53", "target_ip": "10.0.0.53", "test_type": "dns",
                    "success": True, "latency_ms": 0, "output": "example.com -> 93.184.216.34"})
    return out


def max_id(db, table):
    return db.execute("SELECT COALESCE(MAX(id), 0) FROM %s" % table).fetchone()[0]


def backdate(db, table, after, minutes):
    db.execute("UPDATE %s SET received_at = datetime(received_at, ?) WHERE id > ?" % table,
               ("-%d minutes" % minutes, after))


def seed_lldp():
    for i in range(1, 6):
        post("/lldp", {"source": "node-%d" % i, "neighbors": [{
            "local_port": "eth0", "chassis_id": "00:1b:54:00:00:%02x" % i,
            "port_id": "Gi1/0/%d" % (i + 2), "port_descr": "GigabitEthernet1/0/%d" % (i + 2),
            "sys_name": "access-sw%d" % ((i + 1) // 2), "sys_descr": "Demo access switch",
            "mgmt_ip": "10.0.0.%d" % (10 + (i + 1) // 2)}]})


def hub_build():
    """The build this hub serves, so seeded nodes read as up to date (a node
    reporting a different build gets an orange Hub arrow)."""
    try:
        return json.load(urllib.request.urlopen(HUB + "/node/release"))["commit"] or "unknown"
    except Exception:
        return "unknown"


def main():
    for host, ip, group in NODES:
        post("/register", {"hostname": host, "ip": ip, "subnet": ip.rsplit(".", 1)[0] + ".0/24",
                           "group_name": group, "build": hub_build(), "managed": True,
                           "clock_synced": True, "clock_offset_s": -0.0012})
    seed_lldp()
    # A group set on the hub, so the matrix header and Endpoints list show the pencil mark.
    post("/api/nodes/node-4/group", {"group": "edge"})
    db = sqlite3.connect(DB)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for rnd in range(ROUNDS):
        r0, s0 = max_id(db, "results"), max_id(db, "syslog")
        for host, ip, _ in NODES:
            post("/results", {"source": host, "results": results(rnd, host, ip)})
        if rnd == BROKEN_FROM:
            for msg in [
                "<189>site-a: Oct  2 06:30:01: %SYS-5-CONFIG_I: Configured from console by admin on vty0 (10.1.1.50)",
                "<189>site-e: Oct  2 06:31:10: %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet2, changed state to down",
                "<187>site-e: Oct  2 06:31:10: %LINK-3-UPDOWN: Interface GigabitEthernet2, changed state to down",
                "<189>site-c: Oct  2 06:31:12: %OSPF-5-ADJCHG: Process 1, Nbr 10.0.35.5 on GigabitEthernet3 from FULL to DOWN, Neighbor Down: Dead timer expired",
                "<189>site-c: Oct  2 06:31:12: %BFD-5-STATECHANGE: neighbor 10.0.35.5 Down BFD adjacency down",
            ]:
                sock.sendto(msg.encode(), SYSLOG)
            time.sleep(1)
        minutes = ROUNDS - rnd
        backdate(db, "results", r0, minutes)
        backdate(db, "syslog", s0, minutes)
        db.commit()
    print("seeded", max_id(db, "results"), "results,", max_id(db, "syslog"), "syslog rows")


main()
