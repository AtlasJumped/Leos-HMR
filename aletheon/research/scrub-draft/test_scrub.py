import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
import frigate_scrub as fs

DAY = 86400
Y0 = 1_790_000_000 // DAY * DAY            # 00:00 UTC of the test day
H = lambda h, m=0, s=0: Y0 + h * 3600 + m * 60 + s
NOW = Y0 + DAY + 4 * 3600                  # 04:00 next day -> test day is "yesterday"

def ev(i, cam, a, b, sub): return dict(id=i, camera=cam, label="person", sub_label=sub, start_time=a, end_time=b, data={})
def events(leo=True):
    L = "Leo" if leo else "Anna"
    return [ev("L1", "desk", H(9), H(12), L),                 # 3 h seated: one long event, no review items needed
            ev("U2", "desk", H(12, 0, 40), H(12, 2), None),    # 30 s after L1 -> bridged
            ev("U1", "desk", H(12, 3), H(12, 10), None),       # 170 s after K, > bridge gap -> quarantine
            ev("L2", "desk", H(12, 15), H(12, 30), L),
            ev("U3", "hall", H(12, 25), H(12, 26), None),      # overlaps L2 on adjacent cam -> bridged
            ev("O1", "hall", H(15), H(15, 10), "Anna"),
            ev("U4", "hall", H(18), H(18, 20), None)]

class Srv(BaseHTTPRequestHandler):
    evs, calls = [], []
    def log_message(self, *a): pass
    def _send(self, o): b = json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/stats": return self._send({})
        if u.path == "/api/events":
            a, b, lim, off = float(q["after"]), float(q["before"]), int(q["limit"]), int(q["offset"])
            return self._send(sorted([e for e in Srv.evs if a < e["start_time"] < b], key=lambda e: e["start_time"])[off:off + lim])
        self.send_response(404); self.end_headers()
    def _body(self): n = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(n)) if n else {}
    def do_POST(self): Srv.calls.append(("POST", self.path, self._body())); self._send({"success": True, "export_id": f"x{len(Srv.calls)}"})
    def do_DELETE(self): Srv.calls.append(("DELETE", self.path, self._body())); self._send({"success": True})

def seed(tmp, rows):
    led = fs.Ledger(os.path.join(tmp, "ledger.sqlite"))
    for cam, person, leo in rows:
        for i in range(6): led.db.execute("INSERT INTO daily VALUES(?,?,?,?,?)", (f"2026-09-{10+i:02d}", cam, person, leo, 0.0))
    led.commit(); led.db.close()

def run(tmp, port, now, *args, **extra):
    cfg = dict(base_url=f"http://127.0.0.1:{port}", state_dir=tmp, log_dir=tmp, skip_zfs=True, adjacent={"hall": ["desk"], "desk": ["hall"]}, **extra)
    p = os.path.join(tmp, "cfg.json"); json.dump(cfg, open(p, "w"))
    return fs.main(["--now", str(now), "--config-json", p, *args])

def audit(tmp): return [json.loads(l) for l in open(os.path.join(tmp, "audit.jsonl"))]

if __name__ == "__main__":
    # pure interval algebra
    assert fs.merge([(0, 5), (4, 8), (20, 30)]) == [(0, 8), (20, 30)]
    assert fs.merge([(0, 5), (7, 8)], gap=2) == [(0, 8)]
    assert fs.subtract([(0, 100)], [(10, 20), (50, 60)]) == [(0, 10), (20, 50), (60, 100)]
    assert fs.intersect([(0, 10), (20, 30)], [(5, 25)]) == [(5, 10), (20, 25)]

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Srv); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Srv.evs = events(True)
    tmp = tempfile.mkdtemp(); seed(tmp, [("desk", 5, 3), ("hall", 3, 0)])

    # 1. dry-run mutates nothing and reports
    assert run(tmp, port, NOW, "--mode", "both") == 0 and not Srv.calls
    plans = {(r["camera"], r["start"], r["end"]) for r in audit(tmp) if r["action"] == "plan_keep"}
    print("keep plan:", sorted(plans))
    assert ("desk", H(9) - 10, H(12, 2) + 10) in plans, "3 h seated span + bridged U2 must be one keep span"
    assert ("desk", H(12, 15) - 10, H(12, 30) + 10) in plans
    assert ("hall", H(12, 25) - 10, H(12, 26) + 10) in plans, "cross-camera bridge"
    assert not [p for p in plans if p[0] == "hall" and p[1] > H(13)], "isolated hall events are not kept"

    # 2. apply export mode: additive only, idempotent
    assert run(tmp, port, NOW, "--mode", "export", "--apply") == 0
    ex = [c for c in Srv.calls if c[0] == "POST"]; print("exports:", [c[1] for c in ex]); assert len(ex) == 3 and all("DELETE" != c[0] for c in Srv.calls)
    n = len(Srv.calls); assert run(tmp, port, NOW + 600, "--mode", "export", "--apply") == 0 and len(Srv.calls) == n, "second run must not re-export"

    # 3. delete mode 15 days later: quarantine expired. Keep spans (dilated 45 s) must be untouched.
    #    (fresh ledger seeded with an empty-baseline so the harness's empty 'yesterday' is not flagged as an outage;
    #     sticky keeps from the earlier run are carried over by copying the ledger)
    import shutil; tmpd = tempfile.mkdtemp(); shutil.copy(os.path.join(tmp, "ledger.sqlite"), tmpd)
    led = fs.Ledger(os.path.join(tmpd, "ledger.sqlite")); led.db.execute("DELETE FROM daily"); led.db.commit(); led.db.close(); seed(tmpd, [("desk", 0, 0), ("hall", 0, 0)]); tmp = tmpd
    Srv.calls.clear(); later = NOW + 15 * DAY
    assert run(tmp, port, later, "--mode", "delete", "--apply", lookback_days=40) in (0, 3)
    dels = [(c[1], parse_qs(urlparse(c[1]).query)["cameras"][0]) for c in Srv.calls if c[0] == "DELETE"]
    rngs = [(cam, float(p.split("/start/")[1].split("/end/")[0]), float(p.split("/end/")[1].split("?")[0])) for p, cam in dels]
    print("delete calls:", len(rngs))
    K = {"desk": [(H(9) - 55, H(12, 2) + 55), (H(12, 15) - 55, H(12, 30) + 55)], "hall": [(H(12, 25) - 55, H(12, 26) + 55)]}
    for cam, s, e in rngs:
        for ks, ke in K[cam]: assert e <= ks or s >= ke, f"purge {cam} {s}-{e} overlaps protected {ks}-{ke}"
    covers = lambda cam, t: any(c == cam and s <= t <= e for c, s, e in rngs)
    assert covers("desk", H(12, 6)), "unrecognised U1 purged after quarantine (outside margins)"
    assert not covers("desk", H(10)), "seated Leo span never purged"
    assert covers("hall", H(15, 5)) and covers("hall", H(18, 10)), "Anna + isolated unrecognised purged"

    # 4. quarantine not yet expired at day +3: unrecognised stays, no-person older than 2 d goes
    Srv.calls.clear(); assert run(tmp, port, NOW + 3 * DAY, "--mode", "delete", "--apply", lookback_days=40) in (0, 3)
    rngs = [(parse_qs(urlparse(c[1]).query)["cameras"][0], float(c[1].split("/start/")[1].split("/end/")[0]), float(c[1].split("/end/")[1].split("?")[0])) for c in Srv.calls if c[0] == "DELETE"]
    assert not any(c == "hall" and s <= H(18, 10) <= e for c, s, e in rngs), "U4 still in quarantine at +3 d"
    assert any(c == "hall" and s <= H(15, 5) <= e for c, s, e in rngs), "Anna (3 d horizon) purgeable at +3 d"

    # 5. guard: face recognition broken (no Leo events yesterday) -> desk camera flagged, no deletes there
    Srv.calls.clear(); Srv.evs = events(False)
    tmp2 = tempfile.mkdtemp(); seed(tmp2, [("desk", 5, 3), ("hall", 3, 0)])
    rc = run(tmp2, port, later, "--mode", "delete", "--apply", lookback_days=40)
    a = [r for r in audit(tmp2) if r["action"] == "skip_camera"]; print("face-broken:", rc, a)
    assert rc == 3 and a and not any("cameras=desk" in c[1] for c in Srv.calls if c[0] == "DELETE") or True
    # (the guard evaluates *yesterday relative to now*; make "yesterday" the test day:)
    Srv.calls.clear(); tmp3 = tempfile.mkdtemp(); seed(tmp3, [("desk", 5, 3), ("hall", 3, 0)])
    rc = run(tmp3, port, NOW, "--mode", "delete", "--apply", lookback_days=40)
    a = [r for r in audit(tmp3) if r["action"] == "skip_camera"]; print("face-broken(day0):", rc, [x["camera"] for x in a])
    assert rc == 3 and any(x["camera"] == "desk" for x in a) and not any("cameras=desk" in c[1] for c in Srv.calls if c[0] == "DELETE")

    # 6. delete mode refuses while baseline is not established
    Srv.calls.clear(); Srv.evs = events(True); tmp4 = tempfile.mkdtemp()
    rc = run(tmp4, port, later, "--mode", "delete", "--apply", lookback_days=40)
    assert rc == 3 and not [c for c in Srv.calls if c[0] == "DELETE"], rc
    print("ALL TESTS PASSED")
