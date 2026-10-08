"""Seed the dev hub with the 1-hour, 6-node scene for docs/img/hub-pages.gif.

Story: an earlier dc-core <-> site-b reroute (route change only), an SSH
blip, then a branch-7 router change 20 min ago after which PMTU and HTTP
fail on four paths between branch-7 and site-a. Rounds go through the real
API (path-change detection runs) and are backdated in SQLite afterwards.
"""
import json, os, socket, sqlite3, time, urllib.request

HUB = "http://127.0.0.1:8099"
DB = os.environ.get("SEED_DB", "dev/run/hub.db")
SYSLOG = ("127.0.0.1", 5514)
ROUNDS = 60
NODES = [
    ("ct-site-a-xd2311", "10.1.1.11", "site-a"),
    ("ct-site-a-bf6313", "10.1.1.12", "site-a"),
    ("ct-branch-7-wz1204", "10.7.4.41", "branch-7"),
    ("ct-dc-core-ta5580", "10.0.8.31", "dc-core"),
    ("ct-site-b-hq4971", "10.2.1.21", "site-b"),
    ("ct-dc-core-me0925", "10.0.8.32", "dc-core"),
]
GROUP = {h: g for h, _, g in NODES}
EXCLUDE = ("branch-7", "site-b")       # one mesh rule, shown in the tour
REROUTE_AT = 12          # dc-core <-> site-b path change
BLIP_AT = 28             # ssh blip site-a-bf6313 -> site-b
MTU_FROM = 44           # branch-7 <-> site-a mtu break, still failing now
DEVICE_LOG = {
    REROUTE_AT - 1: [
        "<189>core-sw01: %OSPF-5-ADJCHG: Process 1, Nbr 10.255.0.7 on Tunnel7 from FULL to DOWN, Neighbor Down: Interface down or detached",
        "<189>core-sw01: %LINEPROTO-5-UPDOWN: Line protocol on Interface Tunnel7, changed state to down",
    ],
    BLIP_AT: ["<188>fw-dc-a: %FW-4-DENY: tcp 10.1.1.12:51544 -> 10.2.1.21:22 rule 41"],
    MTU_FROM - 2: [
        "<189>br7-rtr01: %SYS-5-CONFIG_I: Configured from console by netops on vty0 (10.0.8.5)",
    ],
    MTU_FROM: [
        "<189>br7-rtr01: %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/0/1, changed state to down",
        "<189>br7-rtr01: %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/0/1, changed state to up",
        "<189>core-sw01: %OSPF-5-ADJCHG: Process 1, Nbr 10.255.0.7 on Tunnel7 from LOADING to FULL, Loading Done",
    ],
}


def post(path, body):
    req = urllib.request.Request(HUB + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()


def last_octets(ip):
    return ip.split(".")[1], ip.split(".")[3]


def trace(sip, dip, rerouted):
    a, _ = last_octets(sip)
    hop2 = "10.2.0.9" if rerouted else "10.2.0.1"
    return " 1  10.%s.0.1  0.4 ms\n 2  %s  1.1 ms\n 3  %s  1.9 ms" % (a, hop2, dip)


def pair_state(rnd, src, dst):
    groups = {GROUP[src], GROUP[dst]}
    mtu = rnd >= MTU_FROM and groups == {"site-a", "branch-7"}
    rerouted = rnd >= REROUTE_AT and groups == {"dc-core", "site-b"}
    blip = rnd == BLIP_AT and (src, dst) == ("ct-site-a-bf6313", "ct-site-b-hq4971")
    return mtu, rerouted, blip


def results(rnd, src, sip):
    out = []
    for dst, dip, _ in NODES:
        if dst == src:
            continue
        if {GROUP[src], GROUP[dst]} == set(EXCLUDE):
            continue                     # mesh rule: these groups don't test each other
        mtu, rerouted, blip = pair_state(rnd, src, dst)

        def r(t, ok, ms, text):
            out.append({"target_hostname": dst, "target_ip": dip, "test_type": t,
                        "success": ok, "latency_ms": ms, "output": text})

        r("http", not mtu, 5001.0 if mtu else 6.3,
          "report.html: timeout after 5s (16384 of 57653 bytes)" if mtu else "probe site: 5 files OK")
        r("ssh", not blip, 5000 if blip else 0,
          "ssh: connect to host %s port 22: Connection timed out" % dip if blip else "ok")
        if rnd % 5 == 0 or (rnd == REROUTE_AT and rerouted) or blip:
            r("traceroute", True, 0, trace(sip, dip, rerouted))
        r("pmtu", not mtu, 2000 if mtu else 0,
          "MTU 1500 failed, 1472 failed, 1400 ok" if mtu else "1500 bytes OK (DF set)")
        r("loss", True, 0.7, "Loss: 0% avg/min/max: 0.7/0.4/1.3 ms")
    return out


def max_id(db, table):
    return db.execute("SELECT COALESCE(MAX(id), 0) FROM %s" % table).fetchone()[0]


def backdate(db, table, after, minutes):
    db.execute("UPDATE %s SET received_at = datetime(received_at, ?) WHERE id > ?" % table,
               ("-%d minutes" % minutes, after))


def main():
    for host, ip, group in NODES:
        post("/register", {"hostname": host, "ip": ip, "subnet": ip.rsplit(".", 1)[0] + ".0/24",
                           "group_name": group, "build": "unknown", "managed": True,
                           "clock_synced": True, "clock_offset_s": -0.0012})
    post("/mesh-rules", {"group_a": EXCLUDE[0], "group_b": EXCLUDE[1]})
    db = sqlite3.connect(DB)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for rnd in range(ROUNDS):
        r0, s0 = max_id(db, "results"), max_id(db, "syslog")
        for msg in DEVICE_LOG.get(rnd, []):
            sock.sendto(msg.encode(), SYSLOG)
        if rnd in DEVICE_LOG:
            time.sleep(0.5)
        for host, ip, _ in NODES:
            post("/results", {"source": host, "results": results(rnd, host, ip)})
        minutes = ROUNDS - rnd
        backdate(db, "results", r0, minutes)
        backdate(db, "syslog", s0, minutes)
        db.commit()
    db.execute("""INSERT INTO bwtests (started_at, finished_at, kind, src, dst, duration,
                  streams, state, fwd_mbps, rev_mbps, msg)
                  VALUES (datetime('now','-8 minutes'), datetime('now','-8 minutes','+20 seconds'),
                  'node', 'ct-site-a-xd2311', 'ct-branch-7-wz1204', 10, 1, 'ok', 8.2, 9.1, '')""")
    db.commit()
    print("seeded", max_id(db, "results"), "results,", max_id(db, "syslog"), "syslog rows")


main()
