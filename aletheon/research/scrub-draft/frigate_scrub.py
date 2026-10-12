#!/usr/bin/env python3
"""frigate_scrub.py v2 -- nightly "keep clips where Leo is present" for Frigate (interval based).

OUTLINE.  Endpoint shapes read from Frigate v0.18.0 / dev source; exercised only against a mock
server, never a live Frigate.  stdlib + requests only.

Why intervals from *events*, not review items: review items only span ACTIVE (moving) objects
(a stationary person drops out of them after detect.stationary.threshold), whereas a tracked-object
event lasts as long as the track does, so a person sitting still at a desk is still one long event.

Policy (tri-state, conservative):
  event sub_label in leo_names                 -> KEEP (sticky: written to ledger, never un-kept)
  unrecognised person event near a KEEP span   -> KEEP (one-hop bridging, same camera or adjacent camera)
  gaps <= sandwich_gap between KEEP spans      -> KEEP
  unrecognised person otherwise                -> QUARANTINE quarantine_days, then purge-eligible
  only other named people                      -> purge-eligible after other_known_days
  no person at all                             -> purge-eligible after no_person_days
Modes:
  export : (recommended) non-destructive. Copy KEEP spans to /media/frigate/exports via the export API;
           Frigate's own retention expires everything else.
  delete : explicit DELETE /api/recordings/start/{a}/end/{b}?cameras=cam on purge-eligible ranges.
"""
import argparse, fcntl, json, logging, os, sqlite3, statistics, subprocess, sys, time, uuid
import requests

EXIT_OK, EXIT_ERR, EXIT_REFUSED = 0, 1, 3
INF = float("inf")
DEFAULTS = dict(
    base_url=os.environ.get("FRIGATE_URL", "http://127.0.0.1:5000"),   # 5000 = internal port: admin, no auth
    user=os.environ.get("FRIGATE_USER"),             # set only when using authenticated 8971
    password_file=os.environ.get("FRIGATE_PASSWORD_FILE"),   # $CREDENTIALS_DIRECTORY/frigate_pass
    ca_file=os.environ.get("FRIGATE_CA_FILE"),       # pinned self-signed cert; never verify=False
    leo_names=["leo"], adjacent={},                  # adjacent: {"hall": ["living", "kitchen"]}
    pre_s=10, post_s=10, bridge_gap_s=90, xcam_gap_s=45, sandwich_gap_s=300, edge_margin_s=45,
    quarantine_days=14.0, other_known_days=3.0, no_person_days=2.0,
    settle_s=1800, lookback_days=21, min_piece_s=5,
    max_purge_vs_median=2.0,            # refuse a camera if purge-seconds > 2x its trailing median
    min_event_ratio=0.25, min_leo_ratio=0.40, baseline_days=5,
    export_batch=40,                    # Frigate queue holds 100 export jobs (MAX_QUEUED_EXPORT_JOBS)
    skip_zfs=False, snapshot_prefix="scrub-",
    state_dir=os.environ.get("STATE_DIRECTORY", "/var/lib/frigate-scrub"),
    log_dir=os.environ.get("LOGS_DIRECTORY", "/var/log/frigate-scrub"),
)

# ---------- interval algebra ------------------------------------------------------------------
def merge(iv, gap=0.0):
    out = []
    for s, e in sorted(i for i in iv if i[1] > i[0]):
        if out and s <= out[-1][1] + gap: out[-1] = (out[-1][0], max(out[-1][1], e))
        else: out.append((s, e))
    return out
def intersect(a, b):
    out, i, j = [], 0, 0
    a, b = merge(a), merge(b)
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if e > s: out.append((s, e))
        if a[i][1] < b[j][1]: i += 1
        else: j += 1
    return out
def subtract(a, b):
    out, b = [], merge(b)
    for s, e in merge(a):
        cur = s
        for bs, be in b:
            if be <= cur or bs >= e: continue
            if bs > cur: out.append((cur, bs))
            cur = max(cur, be)
            if cur >= e: break
        if cur < e: out.append((cur, e))
    return out
def dilate(iv, m): return merge([(s - m, e + m) for s, e in iv])

# ---------- Frigate client ---------------------------------------------------------------------
class Frigate:
    def __init__(self, cfg):
        self.base, self.cfg, self.s = cfg["base_url"].rstrip("/"), cfg, requests.Session()
        self.s.verify = cfg["ca_file"] or True
        if cfg["user"]: self.login()
    def login(self):
        pw = open(self.cfg["password_file"]).read().strip()
        r = self.s.post(f"{self.base}/api/login", json={"user": self.cfg["user"], "password": pw}, timeout=30)
        r.raise_for_status()                      # JWT comes back as Set-Cookie "frigate_token" (24 h default)
    def _req(self, method, path, **kw):
        kw.setdefault("timeout", 120)
        for attempt in (1, 2):
            r = self.s.request(method, f"{self.base}/api{path}", **kw)
            if r.status_code == 401 and self.cfg["user"] and attempt == 1: self.login(); continue
            r.raise_for_status(); return r
    def get(self, path, **p): return self._req("GET", path, params=p).json()
    def post(self, path, body): return self._req("POST", path, json=body).json()
    def delete(self, path, body=None, **p): return self._req("DELETE", path, json=body, params=p).json()
    def person_events(self, after, before):
        out, off, lim = [], 0, 500
        while True:                                # limit/offset paging, stable order
            page = self.get("/events", labels="person", after=after, before=before, limit=lim,
                            offset=off, sort="date_asc", include_thumbnails=0)
            out += page
            if len(page) < lim: return out
            off += lim

# ---------- policy -----------------------------------------------------------------------------
def sub_names(e): return {p.strip().lower() for p in str(e.get("sub_label") or "").split(",") if p.strip()}

def build(events, cfg, leo_prev, kept_prev):
    """-> per-camera dict with keep K, Leo anchors A, unrecognised QU, other-known QO (merged interval lists).
    Only Leo-recognised spans are bridging anchors (also across runs), so keeps cannot chain outward."""
    leo = {n.lower() for n in cfg["leo_names"]}; cams = {}
    for e in events:
        if e["end_time"] is None: continue                       # in-progress track: handled next run
        names = sub_names(e)
        k = "leo" if names & leo else ("other" if names else "unrec")
        cams.setdefault(e["camera"], {"leo": [], "other": [], "unrec": []})[k].append((e["start_time"], e["end_time"]))
    for c in list(leo_prev) + list(kept_prev): cams.setdefault(c, {"leo": [], "other": [], "unrec": []})
    padded = lambda l: [(s - cfg["pre_s"], e + cfg["post_s"]) for s, e in l]
    anchors = {c: merge(padded(v["leo"]) + leo_prev.get(c, [])) for c, v in cams.items()}
    res = {}
    for c, v in cams.items():
        bridged = []
        for s, e in v["unrec"]:
            same = any(a_s - cfg["bridge_gap_s"] <= e and s <= a_e + cfg["bridge_gap_s"] for a_s, a_e in anchors[c])
            adj = any(a_s - cfg["xcam_gap_s"] <= e and s <= a_e + cfg["xcam_gap_s"]
                      for oc in cfg["adjacent"].get(c, []) for a_s, a_e in anchors.get(oc, []))
            if same or adj: bridged.append((s - cfg["pre_s"], e + cfg["post_s"]))   # one hop: anchors only
        K = merge(anchors[c] + bridged + kept_prev.get(c, []), gap=cfg["sandwich_gap_s"])
        res[c] = dict(K=K, A=anchors[c], QU=merge(padded(v["unrec"])), QO=merge(padded(v["other"])))
    return res

def purge_ranges(c, now, win, cfg):
    """Purge-eligible ranges for one camera: never within edge_margin of K; horizon depends on class."""
    free = subtract([win], dilate(c["K"], cfg["edge_margin_s"]))
    QU, QO = dilate(c["QU"], cfg["edge_margin_s"]), dilate(c["QO"], cfg["edge_margin_s"])
    old = lambda days: [(-INF, now - days * 86400)]
    eu = intersect(intersect(free, QU), old(cfg["quarantine_days"]))
    eo = intersect(subtract(intersect(free, QO), QU), old(cfg["other_known_days"]))
    en = intersect(subtract(subtract(free, QU), QO), old(cfg["no_person_days"]))
    return [r for r in merge(eu + eo + en) if r[1] - r[0] >= cfg["min_piece_s"]]

# ---------- state / audit ----------------------------------------------------------------------
class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS kept(camera TEXT, start REAL, end REAL);
          CREATE TABLE IF NOT EXISTS leo_kept(camera TEXT, start REAL, end REAL);
          CREATE TABLE IF NOT EXISTS exported(camera TEXT, start REAL, end REAL, export_id TEXT, ts REAL);
          CREATE TABLE IF NOT EXISTS daily(day TEXT, camera TEXT, person INT, leo INT, purge_s REAL, PRIMARY KEY(day,camera));""")
    def kept(self, table="kept"):
        d = {}
        for c, s, e in self.db.execute(f"SELECT camera,start,end FROM {table}"): d.setdefault(c, []).append((s, e))
        return {c: merge(v) for c, v in d.items()}
    def save_kept(self, K, table="kept"):       # union with old: a keep is never forgotten
        old = self.kept(table); self.db.execute(f"DELETE FROM {table}")
        for c in set(K) | set(old):
            for s, e in merge(K.get(c, []) + old.get(c, [])): self.db.execute(f"INSERT INTO {table} VALUES(?,?,?)", (c, s, e))
    def exported(self, cam): return merge(list(self.db.execute("SELECT start,end FROM exported WHERE camera=?", (cam,))))
    def trailing(self, cam, n=14): return self.db.execute("SELECT person,leo,purge_s FROM daily WHERE camera=? ORDER BY day DESC LIMIT ?", (cam, n)).fetchall()
    def commit(self): self.db.commit()

class Audit:
    def __init__(self, path, run): self.f, self.run = open(path, "a", buffering=1), run
    def __call__(self, **kw): self.f.write(json.dumps({"ts": time.time(), "run": self.run, **kw}) + "\n")

def snapshot_exists(cfg):
    """Snapshots are created as root by `ExecStartPre=+` (Linux can't delegate zfs mount); here we only verify."""
    if cfg["skip_zfs"]: return True
    out = subprocess.run(["zfs", "list", "-H", "-t", "snapshot", "-o", "name", "-s", "creation"], capture_output=True, text=True, timeout=60).stdout
    return any(("@" + cfg["snapshot_prefix"]) in l for l in out.splitlines()[-50:])

# ---------- guards -----------------------------------------------------------------------------
def guards(yres, purges, ledger, cfg):
    """-> {camera: ("ok"|"baseline"|"anomaly", [reasons])}; baseline = still learning, so no deletes."""
    out = {}
    for cam, y in yres.items():
        hist = ledger.trailing(cam)
        if len(hist) < cfg["baseline_days"]: out[cam] = ("baseline", [f"{cam}: {len(hist)}/{cfg['baseline_days']} baseline days"]); continue
        mp = statistics.median(h[0] for h in hist); ms = statistics.median((h[1] / h[0]) if h[0] else 0 for h in hist)
        mpurge = statistics.median(h[2] for h in hist); why = []
        if mp >= 3 and y["nperson"] < cfg["min_event_ratio"] * mp: why.append(f"{cam}: {y['nperson']} person events << median {mp}: detector outage?")
        share = y["nleo"] / y["nperson"] if y["nperson"] else 0
        if ms > 0 and y["nperson"] >= 3 and share < cfg["min_leo_ratio"] * ms: why.append(f"{cam}: Leo share {share:.2f} << median {ms:.2f}: face model/library broken?")
        ps = sum(e - s for s, e in purges.get(cam, []))
        if mpurge > 0 and ps > cfg["max_purge_vs_median"] * mpurge: why.append(f"{cam}: purge {ps:.0f}s > {cfg['max_purge_vs_median']}x median {mpurge:.0f}s")
        out[cam] = ("anomaly", why) if why else ("ok", [])
    return out

# ---------- main -------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["export", "delete", "both"], default="export")
    ap.add_argument("--apply", action="store_true", help="act (default: dry-run, GET only)")
    ap.add_argument("--now", type=float); ap.add_argument("--config-json")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    if a.config_json: cfg.update(json.load(open(a.config_json)))
    now = a.now or time.time(); run = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now)) + "-" + uuid.uuid4().hex[:6]
    os.makedirs(cfg["state_dir"], exist_ok=True); os.makedirs(cfg["log_dir"], exist_ok=True)
    lock = open(os.path.join(cfg["state_dir"], "lock"), "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: print("another run active"); return EXIT_ERR
    audit = Audit(os.path.join(cfg["log_dir"], "audit.jsonl"), run)
    ledger, fr, rc = Ledger(os.path.join(cfg["state_dir"], "ledger.sqlite")), Frigate(cfg), EXIT_OK
    audit(action="start", mode=a.mode, apply=a.apply)
    try:
        fr.get("/stats")                                              # preflight: reachable, admin
        win = (now - cfg["lookback_days"] * 86400, now - cfg["settle_s"])
        events = fr.person_events(*win)
        res = build(events, cfg, ledger.kept("leo_kept"), ledger.kept())
        purges = {c: purge_ranges(v, now, win, cfg) for c, v in res.items()} if a.mode != "export" else {}
        day, ystart = time.strftime("%Y-%m-%d", time.gmtime(now - 86400)), int((now - 86400) // 86400) * 86400   # prod: local midnight via zoneinfo
        leo = {n.lower() for n in cfg["leo_names"]}
        yres = {c: dict(nperson=len(v), nleo=sum(1 for e in v if sub_names(e) & leo)) for c in res
                for v in [[e for e in events if e["camera"] == c and ystart <= e["start_time"] < ystart + 86400]]}
        status = guards(yres, purges, ledger, cfg)
        summary = {c: dict(keep_s=round(sum(e - s for s, e in v["K"])), purge_s=round(sum(e - s for s, e in purges.get(c, []))), guard=status[c][0]) for c, v in res.items()}
        problems = [w for st in status.values() for w in st[1]]
        print(json.dumps({"run": run, "mode": a.mode, "apply": a.apply, "cameras": summary, "problems": problems}, indent=1))
        for c, v in res.items():
            for s, e in v["K"]: audit(action="plan_keep", camera=c, start=s, end=e)
            for s, e in purges.get(c, []): audit(action="plan_purge", camera=c, start=s, end=e, guard=status[c][0])
        if not a.apply: audit(action="dry_run_done"); return EXIT_OK
        ledger.save_kept({c: v["K"] for c, v in res.items()}); ledger.save_kept({c: v["A"] for c, v in res.items()}, "leo_kept"); ledger.commit()   # sticky keeps first
        if a.mode in ("export", "both"):                                            # additive, safe
            n = 0
            for c, v in res.items():
                for s, e in subtract(v["K"], ledger.exported(c)):
                    e = min(e, win[1])
                    if e - s < cfg["min_piece_s"] or n >= cfg["export_batch"]: continue
                    r = fr.post(f"/export/{c}/start/{s:.3f}/end/{e:.3f}", {"name": f"Leo {c} {time.strftime('%Y-%m-%d %H:%M', time.localtime(s))}", "source": "recordings"})
                    ledger.db.execute("INSERT INTO exported VALUES(?,?,?,?,?)", (c, s, e, r.get("export_id"), time.time())); n += 1
                    audit(action="export", camera=c, start=s, end=e, api=r)
            ledger.commit()
        if a.mode in ("delete", "both"):
            if not snapshot_exists(cfg): audit(action="REFUSED", problems=["no recent zfs snapshot"]); rc = EXIT_REFUSED
            else:
                for c, rngs in purges.items():
                    if status[c][0] != "ok": audit(action="skip_camera", camera=c, guard=status[c]); rc = EXIT_REFUSED; continue
                    for s, e in rngs:
                        r = fr.delete(f"/recordings/start/{s:.3f}/end/{e:.3f}", cameras=c)   # API delete keeps Frigate's DB consistent
                        audit(action="purged", camera=c, start=s, end=e, api=r); time.sleep(0.5)
        for c in res:                                                               # never let an anomalous day poison the baseline
            if status[c][0] in ("ok", "baseline"):
                ledger.db.execute("INSERT OR REPLACE INTO daily VALUES(?,?,?,?,?)", (day, c, yres[c]["nperson"], yres[c]["nleo"], sum(e - s for s, e in purges.get(c, []))))
        ledger.commit(); audit(action="done", rc=rc); return rc
    except Exception as ex:
        audit(action="error", error=repr(ex)); logging.exception("scrub failed"); return EXIT_ERR
    finally:
        ledger.commit()

if __name__ == "__main__":
    sys.exit(main())
