#!/usr/bin/env python3
"""frigate_scrub.py -- nightly keep / quarantine / purge for Frigate review items.

OUTLINE. Endpoint shapes were read from Frigate v0.18.0 / dev source; this script has only
been exercised against a mock server, never a live Frigate.  stdlib + requests only.

Policy (tri-state, conservative):
  person recognised as Leo (review.data.sub_labels)  -> KEEP        (sticky, never purged)
  unrecognised person near a KEEP item (bridging)    -> KEEP
  unrecognised person, not bridged                   -> QUARANTINE N days, then PURGE
  only other *named* people (guests you enrolled)    -> configurable (default purge after 3 d)
  no person at all                                   -> purge after short horizon
Deletes go through the Frigate API only, never `rm` on /media/frigate.
"""
import argparse, fcntl, json, logging, os, sqlite3, statistics, subprocess, sys, time, uuid
import requests

EXIT_OK, EXIT_ERR, EXIT_REFUSED = 0, 1, 3

DEFAULTS = dict(
    base_url=os.environ.get("FRIGATE_URL", "http://127.0.0.1:5000"),  # 5000 = internal, admin, no auth
    user=os.environ.get("FRIGATE_USER"),            # only if using the authenticated 8971 port
    password_file=os.environ.get("FRIGATE_PASSWORD_FILE"),  # e.g. $CREDENTIALS_DIRECTORY/frigate_pass
    ca_file=os.environ.get("FRIGATE_CA_FILE"),      # pin Frigate's self-signed cert; never verify=False
    leo_names={"leo"},
    quarantine_days=14.0,
    other_known_days=3.0,
    no_person_days=2.0,
    settle_s=1800,          # ignore reviews that ended < 30 min ago
    bridge_gap_s=90,        # same-camera: unrecognised within 90 s of a KEEP review is the same scene
    xcam_gap_s=45,          # cross-camera hop (only for cameras listed in ADJACENT)
    edge_margin_s=30,       # recordings are ~10 s segments split on keyframes; keep a safety margin
    lookback_days=21,       # how far back each run re-evaluates
    max_purge_frac_person=0.60,   # refuse if >60 % of person-containing review time would be purged
    min_event_ratio=0.25,         # refuse if today's person-review count < 25 % of trailing median
    min_leo_ratio=0.40,           # refuse if Leo-recognised share < 40 % of trailing median share
    max_purge_items=400,
    state_dir=os.environ.get("STATE_DIRECTORY", "/var/lib/frigate-scrub"),
    log_dir=os.environ.get("LOGS_DIRECTORY", "/var/log/frigate-scrub"),
    zfs_dataset=os.environ.get("ZFS_DATASET", "tank/frigate"),  # recursive snapshot target
    snapshot_keep_days=14,
)
ADJACENT = {}  # e.g. {"hall": {"living", "kitchen"}, ...}; empty => no cross-camera bridging


# ---------- Frigate client -------------------------------------------------------------------
class Frigate:
    def __init__(self, cfg):
        self.base = cfg["base_url"].rstrip("/")
        self.s = requests.Session()
        self.s.verify = cfg["ca_file"] or True
        self.cfg = cfg
        if cfg["user"]:
            self.login()

    def login(self):
        pw = open(self.cfg["password_file"]).read().strip()
        r = self.s.post(f"{self.base}/api/login", json={"user": self.cfg["user"], "password": pw}, timeout=30)
        r.raise_for_status()  # JWT arrives as Set-Cookie 'frigate_token' (default 24 h); Session keeps it

    def _req(self, method, path, **kw):
        kw.setdefault("timeout", 60)
        for attempt in (1, 2):
            r = self.s.request(method, f"{self.base}/api{path}", **kw)
            if r.status_code == 401 and self.cfg["user"] and attempt == 1:
                self.login(); continue
            r.raise_for_status()
            return r
    def get(self, path, **params): return self._req("GET", path, params=params).json()
    def post(self, path, body): return self._req("POST", path, json=body).json()
    def delete(self, path, body=None): return self._req("DELETE", path, json=body).json()

    def person_events(self, after, before):
        out, offset, limit = [], 0, 500
        while True:   # offset paging; sort=date_asc keeps pages stable while new events arrive
            page = self.get("/events", labels="person", after=after, before=before,
                            limit=limit, offset=offset, sort="date_asc", include_thumbnails=0)
            out += page
            if len(page) < limit: return out
            offset += limit

    def reviews(self, after, before):
        out, t = [], after
        while t < before:   # /review has no offset: walk 24 h windows
            out += self.get("/review", after=t, before=min(t + 86400, before))
            t += 86400
        return {r["id"]: r for r in out}.values()   # de-dup windows that straddle a review


# ---------- pure policy ----------------------------------------------------------------------
def names_of(sub_labels):
    out = set()
    for s in sub_labels or []:
        out |= {p.strip().lower() for p in str(s).split(",") if p.strip()}   # Frigate may join "a, b"
    return out

def classify(reviews, events, cfg):
    """-> {review_id: (klass, reason)}.  klass in KEEP_LEO, KEEP_BRIDGED, UNRECOGNIZED, OTHER_KNOWN, NO_PERSON"""
    ev = {e["id"]: e for e in events}
    base = {}
    for r in reviews:
        d = r.get("data") or {}
        objs = set(d.get("objects") or [])
        has_person = bool(objs & {"person", "person-verified"})
        names = names_of(d.get("sub_labels"))
        unrec = [i for i in d.get("detections", []) if i in ev and ev[i]["label"] == "person" and not ev[i].get("sub_label")]
        if names & cfg["leo_names"]:
            base[r["id"]] = ("KEEP_LEO", "sub_label=" + ",".join(sorted(names & cfg["leo_names"])))
        elif not has_person:
            base[r["id"]] = ("NO_PERSON", "objects=" + ",".join(sorted(objs)))
        elif names and not unrec and "person" not in objs:
            base[r["id"]] = ("OTHER_KNOWN", "named=" + ",".join(sorted(names)))
        else:
            base[r["id"]] = ("UNRECOGNIZED", f"unrecognised_tracks={len(unrec)}")
    keeps = [r for r in reviews if base[r["id"]][0] == "KEEP_LEO"]
    out = dict(base)
    for r in reviews:                      # one-hop bridging only (non-transitive on purpose)
        if base[r["id"]][0] != "UNRECOGNIZED": continue
        for k in keeps:
            same = k["camera"] == r["camera"]
            gap_ok = cfg["bridge_gap_s"] if same else cfg["xcam_gap_s"]
            if not same and k["camera"] not in ADJACENT.get(r["camera"], ()): continue
            gap = max(r["start_time"] - k["end_time"], k["start_time"] - r["end_time"], 0)
            if gap <= gap_ok:
                out[r["id"]] = ("KEEP_BRIDGED", f"{'same' if same else 'x'}-camera gap {gap:.0f}s to {k['id']}")
                break
    return out

def plan(reviews, klass, ledger, cfg, now):
    """Decide per review: keep | quarantine | purge | edge_protected.  Sticky keeps come from ledger."""
    keep_spans = {}
    for r in reviews:
        if klass[r["id"]][0].startswith("KEEP") or ledger.is_kept(r["id"]):
            keep_spans.setdefault(r["camera"], []).append((r["start_time"] - cfg["edge_margin_s"], r["end_time"] + cfg["edge_margin_s"]))
    horizon = {"UNRECOGNIZED": cfg["quarantine_days"], "OTHER_KNOWN": cfg["other_known_days"], "NO_PERSON": cfg["no_person_days"]}
    out = {}
    for r in reviews:
        k, why = klass[r["id"]]
        if k.startswith("KEEP") or ledger.is_kept(r["id"]):
            out[r["id"]] = ("keep", why); continue
        first = ledger.first_seen(r["id"], now)
        due = first + horizon[k] * 86400
        touches_keep = any(a <= r["end_time"] and r["start_time"] <= b for a, b in keep_spans.get(r["camera"], []))
        if touches_keep:
            out[r["id"]] = ("edge_protected", f"{k} within {cfg['edge_margin_s']}s of a keep span")
        elif now < due:
            out[r["id"]] = ("quarantine", f"{k}; purge in {(due-now)/86400:.1f} d")
        else:
            out[r["id"]] = ("purge", f"{k}; first seen {(now-first)/86400:.1f} d ago")
    return out


# ---------- state / audit --------------------------------------------------------------------
class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""CREATE TABLE IF NOT EXISTS item(review_id TEXT PRIMARY KEY, camera TEXT, start REAL, end REAL,
            klass TEXT, first_seen REAL, kept INTEGER DEFAULT 0, purged_at REAL);
            CREATE TABLE IF NOT EXISTS daily(day TEXT PRIMARY KEY, person_reviews INT, leo_reviews INT);""")
    def is_kept(self, rid):
        row = self.db.execute("SELECT kept FROM item WHERE review_id=?", (rid,)).fetchone()
        return bool(row and row[0])
    def first_seen(self, rid, now):
        row = self.db.execute("SELECT first_seen FROM item WHERE review_id=?", (rid,)).fetchone()
        return row[0] if row else now
    def record(self, r, klass, now):
        self.db.execute("INSERT INTO item(review_id,camera,start,end,klass,first_seen,kept) VALUES(?,?,?,?,?,?,?) "
                        "ON CONFLICT(review_id) DO UPDATE SET klass=excluded.klass, kept=MAX(kept, excluded.kept)",
                        (r["id"], r["camera"], r["start_time"], r["end_time"], klass, now, int(klass.startswith("KEEP"))))
    def mark_purged(self, rid, now): self.db.execute("UPDATE item SET purged_at=? WHERE review_id=?", (now, rid))
    def trailing(self, days=14):
        rows = self.db.execute("SELECT person_reviews, leo_reviews FROM daily ORDER BY day DESC LIMIT ?", (days,)).fetchall()
        return rows
    def commit(self): self.db.commit()

class Audit:
    def __init__(self, path, run_id): self.f, self.run = open(path, "a", buffering=1), run_id
    def __call__(self, **kw): self.f.write(json.dumps({"ts": time.time(), "run": self.run, **kw}) + "\n")


# ---------- guards ---------------------------------------------------------------------------
def guards(reviews, yesterday, klass, decisions, ledger, cfg):
    """Baseline checks use *yesterday's* counts vs the trailing daily median; purge-share check uses the whole window."""
    problems = []
    person = yesterday                                   # person-containing reviews that started yesterday
    leo = [r for r in yesterday if klass[r["id"]][0] == "KEEP_LEO"]
    hist = ledger.trailing()
    if len(hist) >= 5:   # need a baseline; until then run dry-run only
        med_person = statistics.median(h[0] for h in hist)
        med_share = statistics.median((h[1] / h[0]) if h[0] else 0 for h in hist)
        if med_person and len(person) < cfg["min_event_ratio"] * med_person:
            problems.append(f"person-review count {len(person)} < {cfg['min_event_ratio']:.0%} of trailing median {med_person}: detector outage?")
        share = len(leo) / len(person) if person else 0
        if med_share and share < cfg["min_leo_ratio"] * med_share:
            problems.append(f"Leo share {share:.2f} < {cfg['min_leo_ratio']:.0%} of trailing median {med_share:.2f}: face library/model broken?")
    else:
        problems.append("fewer than 5 days of baseline in ledger: apply disabled (dry-run only)")
    dur = lambda rs: sum(max(0, r["end_time"] - r["start_time"]) for r in rs)
    purge = [r for r in reviews if decisions[r["id"]][0] == "purge"]
    all_person = [r for r in reviews if klass[r["id"]][0] != "NO_PERSON"]
    pt = dur(all_person)
    if pt and dur([r for r in purge if klass[r["id"]][0] != "NO_PERSON"]) / pt > cfg["max_purge_frac_person"]:
        problems.append("purge would remove > max_purge_frac_person of person-containing footage")
    if len(purge) > cfg["max_purge_items"]:
        problems.append(f"{len(purge)} purge items > max_purge_items {cfg['max_purge_items']}")
    return problems


# ---------- main -----------------------------------------------------------------------------
def zfs_snapshot(cfg, run_id):
    name = f"{cfg['zfs_dataset']}@scrub-{run_id}"
    subprocess.run(["zfs", "snapshot", "-r", name], check=True, timeout=120)   # atomic across child datasets
    return name

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform deletions (default: dry-run)")
    ap.add_argument("--now", type=float, default=None); ap.add_argument("--no-zfs", action="store_true")
    ap.add_argument("--config-json", default=None)
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    if a.config_json: cfg.update(json.load(open(a.config_json)))
    cfg["leo_names"] = {n.lower() for n in cfg["leo_names"]}
    now = a.now or time.time(); run_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now)) + "-" + uuid.uuid4().hex[:6]
    os.makedirs(cfg["state_dir"], exist_ok=True); os.makedirs(cfg["log_dir"], exist_ok=True)
    lock = open(os.path.join(cfg["state_dir"], "lock"), "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: print("another run active"); return EXIT_ERR
    audit = Audit(os.path.join(cfg["log_dir"], "audit.jsonl"), run_id)
    ledger = Ledger(os.path.join(cfg["state_dir"], "ledger.sqlite"))
    fr = Frigate(cfg)
    audit(action="start", apply=a.apply, base=cfg["base_url"])
    try:
        fr.get("/stats")   # preflight: Frigate up and answering as admin
        after, before = now - cfg["lookback_days"] * 86400, now - cfg["settle_s"]
        reviews = [r for r in fr.reviews(after, before) if r.get("end_time") and r["end_time"] < before]
        events = fr.person_events(after, before)
        klass = classify(reviews, events, cfg)
        for r in reviews: ledger.record(r, klass[r["id"]][0], now)
        decisions = plan(reviews, klass, ledger, cfg, now)
        day = time.strftime("%Y-%m-%d", time.gmtime(now - 86400))
        yesterday = [r for r in reviews if time.strftime("%Y-%m-%d", time.gmtime(r["start_time"])) == day and klass[r["id"]][0] != "NO_PERSON"]
        problems = guards(reviews, yesterday, klass, decisions, ledger, cfg)
        if not [p for p in problems if "baseline" not in p]:   # never let an anomalous day poison the baseline
            ledger.db.execute("INSERT OR REPLACE INTO daily VALUES(?,?,?)", (day, len(yesterday), sum(1 for r in yesterday if klass[r["id"]][0] == "KEEP_LEO")))
        tally = {}
        for rid, (d, why) in decisions.items(): tally[d] = tally.get(d, 0) + 1
        for r in reviews: audit(action="decide", review=r["id"], camera=r["camera"], span=[r["start_time"], r["end_time"]], klass=klass[r["id"]][0], decision=decisions[r["id"]][0], why=decisions[r["id"]][1])
        print(json.dumps({"run": run_id, "reviews": len(reviews), "tally": tally, "problems": problems}, indent=1))
        purge = [r for r in reviews if decisions[r["id"]][0] == "purge"]
        if not a.apply: ledger.commit(); audit(action="dry_run_done", tally=tally); return EXIT_OK
        if problems:
            ledger.commit(); audit(action="REFUSED", problems=problems); return EXIT_REFUSED
        if purge and not a.no_zfs:
            audit(action="zfs_snapshot", name=zfs_snapshot(cfg, run_id))      # abort on failure (check=True)
        for i in range(0, len(purge), 25):
            batch = purge[i:i + 25]
            res = fr.post("/reviews/delete", {"ids": [r["id"] for r in batch]})          # review rows + overlapping recordings
            ev_ids = sorted({e for r in batch for e in (r["data"].get("detections") or [])})
            res2 = fr.delete("/events/", {"event_ids": ev_ids}) if ev_ids else {}           # event rows, snapshots, embeddings
            for r in batch: ledger.mark_purged(r["id"], time.time()); audit(action="purged", review=r["id"], api=res, events_api=res2)
            ledger.commit(); time.sleep(1)
        audit(action="done", purged=len(purge)); return EXIT_OK
    except Exception as e:
        audit(action="error", error=repr(e)); logging.exception("scrub failed"); return EXIT_ERR
    finally:
        ledger.commit()

if __name__ == "__main__":
    sys.exit(main())
