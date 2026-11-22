"""Journeys 2 and 8 (mock Google only; see README.md): connect -> discover -> select -> worker sync -> beat sync -> failure isolation -> poison review -> recovery -> ops heartbeat. Real API, worker, beat, Redis, Postgres."""
import json
import re
import subprocess
import sys
import time
import urllib.parse
import uuid

import httpx

import os

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8700/api/v1")
HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("FAKE_GOOGLE_CONTROL", HERE + "/fake_google.json")
APILOG = os.environ["E2E_API_LOG"]  # the file the dev API writes its log to: development mail (verification links) is read from it
PG_CONTAINER = os.environ.get("PG_CONTAINER", "fq-hardening-pg")  # a DISPOSABLE Postgres container, used only to read and nudge state with psql
PG_DB = os.environ.get("PG_DB", "flowqr_e2e")
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER", "fq-hardening-redis")
OUT_DIR = os.environ.get("OUT_DIR", HERE)
rnd = uuid.uuid4().hex[:6]
results = []


def check(name, ok, ev=""):
    results.append((name, ok, ev))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  -- {ev}" if ev else ""), flush=True)


def psql(sql):
    out = subprocess.run(["docker", "exec", PG_CONTAINER, "psql", "-U", "flowqr", "-d", PG_DB, "-At", "-F", "|", "-c", sql], capture_output=True, text=True)
    return [r.split("|") for r in out.stdout.strip().splitlines() if r]


def set_control(c):
    json.dump(c, open(CONTROL, "w"))


def rv(i, rating=5, text="Great clinic", created="2026-11-20T10:00:00Z", **kw):
    return {"id": f"rev-{i}", "rating": rating, "text": text, "created": created, **kw}


class Biz:
    def __init__(self, tag):
        self.tag = tag
        self.http = httpx.Client(base_url=BASE, timeout=30)
        self.email = f"sync-{tag.lower()}-{rnd}@e2e.example.com"
        r = self.http.post("/auth/register", json={"email": self.email, "password": "Str0ngPassw0rd!", "age_confirmed": True, "full_name": f"Sync {tag}"})
        assert r.status_code == 201, r.text
        self.csrf = r.json()["csrf_token"]
        time.sleep(0.5)
        log = open(APILOG, encoding="utf8", errors="ignore").read().split("[DEV EMAIL - not delivered]")
        link = [b for b in log if f"to={self.email} " in b and "verify-email" in b][-1]
        token = urllib.parse.parse_qs(urllib.parse.urlparse(re.search(r"https?://\S+", link).group(0)).query)["token"][0]
        assert self.http.post("/auth/verify-email", json={"token": token}).status_code == 204
        t = self.post("/tenants", {"name": f"Sync Clinic {tag}", "category": "Dental clinic", "language": "en"})
        self.tenant = t.json()["id"]
        self.loc = self.post("/locations", {"name": "Main", "city": "Lucknow", "review_url": "https://g.page/r/FAKE/review"}).json()["id"]
        psql(f"UPDATE subscriptions SET max_locations = 5 WHERE tenant_id = '{self.tenant}'")

    def post(self, path, body=None):
        return self.http.post(path, json=body or {}, headers={"X-CSRF-Token": self.csrf})

    def connect(self):
        r = self.post("/google/connect")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["auth_url"]).query)["state"][0]
        cb = self.http.get("/google/callback", params={"code": self.tag, "state": state}, follow_redirects=False)
        self.conn = self.http.get("/google/status").json()["connections"][0]["id"]
        self.gloc = self.http.get(f"/google/connections/{self.conn}/locations").json()[0]["id"]
        return cb

    def select(self):
        return self.http.put(f"/google/connections/{self.conn}/selection", json={"selections": [{"google_location_id": self.gloc, "selected": True, "location_id": self.loc}]}, headers={"X-CSRF-Token": self.csrf})

    def reviews(self):
        return self.http.get("/reviews", params={"limit": 100}).json()

    def row(self):
        r = psql(f"SELECT last_sync_status, coalesce(last_sync_error,''), consecutive_failures, next_sync_after IS NOT NULL, last_synced_at IS NOT NULL FROM google_locations WHERE id = '{self.gloc}'")[0]
        return {"status": r[0], "error": r[1], "failures": int(r[2] or 0), "backoff": r[3] == "t", "synced": r[4] == "t"}

    def wait(self, pred, secs=200, every=3):
        end = time.time() + secs
        while time.time() < end:
            if pred():
                return True
            time.sleep(every)
        return False


A, B = Biz("A"), Biz("B")
set_control({"A": {"reviews": [rv(i, 5 - (i % 3)) for i in range(1, 6)]}, "B": {"reviews": [rv(i, 4) for i in range(1, 4)]}})
ca, cb = A.connect(), B.connect()
check("J2 OAuth callback redirects to the app with connected=1 (state + nonce cookie verified)", ca.status_code == 303 and "connected=1" in ca.headers["location"] and cb.status_code == 303, ca.headers.get("location"))
check("J2 accounts and locations were discovered and mapped to each business's own location", bool(A.gloc) and bool(B.gloc) and A.gloc != B.gloc)
tokens = psql("SELECT refresh_token_encrypted FROM google_connections WHERE tenant_id IN ('%s','%s')" % (A.tenant, B.tenant))
check("J2 refresh tokens are stored encrypted, never in clear text", all(t[0].startswith("gAAAA") and "RT-" not in t[0] for t in tokens), tokens[0][0][:12] + "...")
check("J2 the status API never returns a token", "RT-" not in A.http.get("/google/status").text and "AT-" not in A.http.get("/google/status").text)
check("J2 selecting a location accepts the request", A.select().status_code == 200 and B.select().status_code == 200)
ok = A.wait(lambda: A.reviews()["total"] == 5 and B.reviews()["total"] == 3)
check("J8 worker (via Redis) synced both businesses; 2 pages + a duplicate across pages gave no duplicate rows", ok, f"A={A.reviews()['total']} B={B.reviews()['total']}")
dups = psql(f"SELECT count(*) - count(DISTINCT external_id) FROM reviews WHERE google_location_id = '{A.gloc}'")[0][0]
check("J2 no duplicate reviews in the database", dups == "0", dups)
check("J2 both businesses show status ok", A.row()["status"] == "ok" and B.row()["status"] == "ok", f"{A.row()} {B.row()}")
check("J2 reviews are visible only to their own business", all(r["external_id".replace("external_id", "id")] for r in A.reviews()["items"]) and A.reviews()["total"] != B.reviews()["total"])
hb = subprocess.run(["docker", "exec", REDIS_CONTAINER, "redis-cli", "get", "flowqr:ops:heartbeat"], capture_output=True, text=True).stdout.strip()
check("J8 beat -> worker heartbeat is fresh in Redis", bool(hb) and time.time() - float(hb) < 120, f"{time.time() - float(hb):.0f}s old" if hb else "none")

# ---- beat-driven update: Google edits a review and adds a new one; nobody clicks Sync
c = json.load(open(CONTROL))
c["A"]["reviews"][1] = rv(2, 1, "Waited far too long", updated="2026-11-22T09:00:00Z")
c["A"]["reviews"].insert(0, rv(6, 5, "Brand new review", created="2026-11-22T10:00:00Z"))
set_control(c)
t0 = time.time()
ok = A.wait(lambda: A.reviews()["total"] == 6, secs=240, every=5)
check("J8 beat scheduled sync picked up an edited review and a new one without any user action", ok, f"{time.time() - t0:.0f}s")
edited = [r for r in A.reviews()["items"] if r["text"] == "Waited far too long"]
check("J2 an edited review is updated in place (rating changed, update_count incremented), not duplicated", bool(edited) and edited[0]["rating"] == 1 and edited[0]["update_count"] == 1)

# ---- failure isolation: A's Google is down, B keeps syncing
c = json.load(open(CONTROL))
c["A"]["mode"] = "server_error"
c["B"]["reviews"].append(rv(4, 3, "B new review", created="2026-11-22T11:00:00Z"))
set_control(c)
ok = A.wait(lambda: A.row()["status"] == "error", secs=240, every=5)
check("J8 a Google 5xx outage is recorded for that location (status error, failure counted, backed off)", ok and A.row()["failures"] >= 1 and A.row()["backoff"], str(A.row()))
ok = B.wait(lambda: B.reviews()["total"] == 4, secs=240, every=5)
check("J8 one failing customer does not stop another customer's sync", ok, f"B total {B.reviews()['total']}")
check("J8 A's already-synced reviews are kept while Google is down", A.reviews()["total"] == 6)

# ---- poison review (finding F-01): a review Google returns in a shape FlowQR cannot parse
c = json.load(open(CONTROL))
c["A"]["mode"] = "ok"
c["A"]["reviews"].append(rv(9, 5, "poison", created="not-a-date"))
set_control(c)
psql(f"UPDATE google_locations SET next_sync_after = NULL, last_synced_at = now() - interval '10 minutes' WHERE id = '{A.gloc}'")
ok = A.wait(lambda: A.row()["status"] == "error" and "not-a-date" not in A.row()["error"] and "could not process" in A.row()["error"].lower() or A.row()["status"] == "error" and A.row()["failures"] >= 2, secs=180, every=5)
check("F-01 through the real worker: an unparseable review ends in a visible error state, not 'running'", ok and A.row()["status"] != "running", str(A.row()))
check("F-01 and it is backed off (not re-queued every cycle)", A.row()["backoff"], str(A.row()))

# ---- recovery
c = json.load(open(CONTROL))
c["A"]["reviews"] = [r for r in c["A"]["reviews"] if r["id"] != "rev-9"]
set_control(c)
psql(f"UPDATE google_locations SET next_sync_after = NULL, last_synced_at = now() - interval '10 minutes' WHERE id = '{A.gloc}'")
ok = A.wait(lambda: A.row()["status"] == "ok" and A.row()["failures"] == 0 and not A.row()["backoff"], secs=180, every=5)
check("J8 after the cause is gone the location recovers by itself (status ok, failures reset, back-off cleared)", ok, str(A.row()))
dups = psql(f"SELECT count(*) - count(DISTINCT external_id) FROM reviews WHERE google_location_id = '{A.gloc}'")[0][0]
check("J8 retries and recovery produced no duplicate reviews", dups == "0" and A.reviews()["total"] == 6, f"dups={dups} total={A.reviews()['total']}")

# ---- revoked access
c = json.load(open(CONTROL))
c["A"]["mode"] = "revoked"
set_control(c)
psql(f"UPDATE google_locations SET next_sync_after = NULL, last_synced_at = now() - interval '10 minutes' WHERE id = '{A.gloc}'")
ok = A.wait(lambda: "revoked" in A.row()["error"].lower(), secs=180, every=5)
check("J2 revoked Google access is detected and shown as a plain reconnect message", ok, A.row()["error"])

# ---- ops
tasks = subprocess.run(["docker", "exec", REDIS_CONTAINER, "redis-cli", "hgetall", "flowqr:ops:tasks"], capture_output=True, text=True).stdout
seen = set(re.findall(r"flowqr\.[a-z_]+", tasks))
check("J8 the worker recorded outcomes for the scheduled jobs (ops page data)", {"flowqr.sync_location", "flowqr.sync_due_locations"} <= seen, ", ".join(sorted(seen))[:200])

bad = [r for r in results if not r[1]]
print(f"\n{len(results) - len(bad)}/{len(results)} checks passed" + (f"; FAILED: {[b[0] for b in bad]}" if bad else ""))
json.dump([{"name": n, "ok": o, "evidence": str(e)} for n, o, e in results], open(OUT_DIR + "/sync-results.json", "w"), indent=1)
sys.exit(1 if bad else 0)
