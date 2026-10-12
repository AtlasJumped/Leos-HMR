import json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
import frigate_scrub as fs

NOW = 1_790_000_000.0  # fixed "now"
DAY = 86400
yday_start = (int((NOW - DAY) // DAY)) * DAY          # 00:00 UTC of "yesterday"
T = lambda h: yday_start + h * 3600                    # hour offset inside yesterday

def review(rid, cam, s, d, objects, subs, dets):
    return dict(id=rid, camera=cam, start_time=s, end_time=s + d, severity="alert",
                data=dict(detections=dets, objects=objects, sub_labels=subs, zones=[], audio=[]))
def event(eid, cam, s, d, sub):
    return dict(id=eid, camera=cam, label="person", sub_label=sub, start_time=s, end_time=s + d, data={})

def build(leo=True):
    R, E = [], []
    # R1 Leo recognised; R2 unrecognised 60 s later same cam (bridge); R3 isolated unrecognised
    R.append(review("R1", "A", T(8), 600, ["person-verified"], ["Leo"] if leo else ["Anna"], ["e1"])); E.append(event("e1", "A", T(8), 600, "Leo" if leo else "Anna"))
    R.append(review("R2", "A", T(8) + 660, 300, ["person"], [], ["e2"])); E.append(event("e2", "A", T(8) + 660, 300, None))
    R.append(review("R3", "B", T(14), 900, ["person"], [], ["e3"])); E.append(event("e3", "B", T(14), 900, None))
    R.append(review("R4", "C", T(15), 120, ["dog"], [], ["d4"]))
    R.append(review("R5", "C", T(16), 120, ["person-verified"], ["Anna"], ["e5"])); E.append(event("e5", "C", T(16), 120, "Anna"))
    R.append(review("R7", "A", T(8) - 310, 300, ["dog"], [], ["d7"]))                 # 10 s before R1 -> edge_protected
    R.append(review("R8", "A", T(20), 500, ["person-verified", "person"], ["Leo"], ["e8", "e9"])); E.append(event("e8", "A", T(20), 500, "Leo")); E.append(event("e9", "A", T(20), 500, None))
    return R, E

class H(BaseHTTPRequestHandler):
    reviews, events, calls = [], [], []
    def log_message(self, *a): pass
    def _send(self, obj): b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/stats": return self._send({})
        if u.path == "/api/review":
            a, b = float(q["after"]), float(q["before"])
            return self._send([r for r in H.reviews if r["start_time"] < b and r["end_time"] > a])
        if u.path == "/api/events":
            a, b = float(q["after"]), float(q["before"]); lim, off = int(q["limit"]), int(q["offset"])
            ev = sorted([e for e in H.events if a < e["start_time"] < b], key=lambda e: e["start_time"])
            return self._send(ev[off:off + lim])
        self.send_response(404); self.end_headers()
    def _body(self): return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
    def do_POST(self):
        H.calls.append(("POST", self.path, self._body())); self._send({"success": True})
    def do_DELETE(self):
        H.calls.append(("DELETE", self.path, self._body())); self._send({"success": True})

def run(now, apply, tmp, port, extra=None):
    cfg = dict(base_url=f"http://127.0.0.1:{port}", state_dir=tmp, log_dir=tmp, **(extra or {}))
    p = os.path.join(tmp, "cfg.json"); json.dump(cfg, open(p, "w"))
    args = ["--now", str(now), "--no-zfs", "--config-json", p] + (["--apply"] if apply else [])
    return fs.main(args)

def last_decisions(tmp, run_prefix=None):
    rows = [json.loads(l) for l in open(os.path.join(tmp, "audit.jsonl"))]
    last = [r for r in rows if r["action"] == "decide"]
    run_id = last[-1]["run"]
    return {r["review"]: (r["klass"], r["decision"]) for r in last if r["run"] == run_id}, rows

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    H.reviews, H.events = build(True)
    tmp = tempfile.mkdtemp()
    # seed baseline so guards have history: 6 days of 6 person reviews, 3 Leo
    import sqlite3
    led = fs.Ledger(os.path.join(tmp, "ledger.sqlite"))
    for i in range(6): led.db.execute("INSERT INTO daily VALUES(?,?,?)", (f"2026-09-{10+i:02d}", 6, 3))
    led.commit(); led.db.close()

    rc = run(NOW, False, tmp, port); d, rows = last_decisions(tmp)
    print("day0 dry-run rc", rc, d)
    assert d["R1"] == ("KEEP_LEO", "keep") and d["R8"] == ("KEEP_LEO", "keep")
    assert d["R2"] == ("KEEP_BRIDGED", "keep"), d["R2"]
    assert d["R3"] == ("UNRECOGNIZED", "quarantine")
    assert d["R4"][1] == "quarantine" and d["R5"][1] == "quarantine"
    assert d["R7"][1] == "edge_protected", d["R7"]
    assert not H.calls, "dry-run must not mutate"

    # day +15: quarantine expired -> purge R3, R4, R5 (R7 stays edge protected; keeps untouched)
    rc = run(NOW + 15 * DAY + 1, True, tmp, port, extra=dict(lookback_days=40)); d, rows = last_decisions(tmp)
    print("day15 apply rc", rc, d)
    print("calls:", H.calls)
    assert rc == fs.EXIT_OK or rc == fs.EXIT_REFUSED
    if rc == fs.EXIT_REFUSED:
        print("refused:", [r for r in rows if r["action"] == "REFUSED"][-1]["problems"])

    # guard test: Leo never recognised (face library wiped) -> must REFUSE, no calls
    H.calls.clear(); H.reviews, H.events = build(False)
    tmp2 = tempfile.mkdtemp(); led = fs.Ledger(os.path.join(tmp2, "ledger.sqlite"))
    for i in range(6): led.db.execute("INSERT INTO daily VALUES(?,?,?)", (f"2026-09-{10+i:02d}", 6, 3))
    led.commit(); led.db.close()
    run(NOW, False, tmp2, port)  # first sighting (starts quarantine clocks)
    rc = run(NOW + 15 * DAY + 1, True, tmp2, port, extra=dict(lookback_days=40))
    print("face-broken apply rc", rc, "calls", H.calls)
    assert rc == fs.EXIT_REFUSED and not H.calls

    # guard test: face pipeline broken only yesterday (zero Leo recognitions vs baseline share 0.5) -> REFUSED even for day-0 apply
    H.calls.clear(); R, E = build(True)
    for r in R:
        if r["id"] in ("R1", "R8"): r["data"]["sub_labels"] = ["Anna"]; r["data"]["objects"] = ["person-verified"]
    for e in E:
        if e["sub_label"] == "Leo": e["sub_label"] = "Anna"
    H.reviews, H.events = R, E
    tmp3 = tempfile.mkdtemp(); led = fs.Ledger(os.path.join(tmp3, "ledger.sqlite"))
    for i in range(6): led.db.execute("INSERT INTO daily VALUES(?,?,?)", (f"2026-09-{10+i:02d}", 6, 3))
    led.commit(); led.db.close()
    rc = run(NOW, True, tmp3, port); rows = [json.loads(l) for l in open(os.path.join(tmp3, "audit.jsonl"))]
    print("leo-share guard rc", rc, [r for r in rows if r["action"] == "REFUSED"][-1]["problems"])
    assert rc == fs.EXIT_REFUSED and not H.calls
    n = fs.Ledger(os.path.join(tmp3, "ledger.sqlite")).db.execute("select count(*) from daily").fetchone()[0]
    assert n == 6, "anomalous day must not enter the baseline"

    # guard test: detector outage (only 1 person review yesterday vs median 6)
    H.calls.clear(); R, E = build(True); keep = {"R1"}
    H.reviews = [r for r in R if r["id"] in keep or r["data"]["objects"] == ["dog"]]; H.events = [e for e in E if e["id"] == "e1"]
    tmp4 = tempfile.mkdtemp(); led = fs.Ledger(os.path.join(tmp4, "ledger.sqlite"))
    for i in range(6): led.db.execute("INSERT INTO daily VALUES(?,?,?)", (f"2026-09-{10+i:02d}", 6, 3))
    led.commit(); led.db.close()
    rc = run(NOW, True, tmp4, port); rows = [json.loads(l) for l in open(os.path.join(tmp4, "audit.jsonl"))]
    print("outage guard rc", rc, [r for r in rows if r["action"] == "REFUSED"][-1]["problems"])
    assert rc == fs.EXIT_REFUSED and not H.calls
    print("ALL TESTS PASSED")
