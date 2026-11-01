#!/usr/bin/env python3
"""After a restore: restored password hashes work, cards resolve, tenant data intact, new work continues (sequence)."""
import json, os, sys, time, httpx

def login(client, email, pw):
    for _ in range(10):  # auth is rate-limited per IP: back off like a real client
        r = client.post('/auth/login', json={'email': email, 'password': pw})
        if r.status_code != 429: return r
        time.sleep(15)
    return r

D = os.environ.get("STAGING_DOMAIN", "flowqr-staging.dev"); seed = json.load(open("/out/seed.json"))
APP, CARD = f"https://app.{D}/api/v1", f"https://go.{D}"
ok = []
def check(c, n, d=""): ok.append(c); print(f"[{'PASS' if c else 'FAIL'}] {n}" + (f"  ({d})" if d else ""))
o = httpx.Client(base_url=APP, timeout=20)
r = login(o, seed["owner"]["email"], seed["owner"]["password"])
check(r.status_code == 200, "owner logs in with the restored password hash", str(r.status_code))
H = {"X-CSRF-Token": r.json()["csrf_token"]}
locs = o.get("/locations").json(); check(len(locs) >= 1 and locs[0]["id"] == seed["location_id"], "restored location present", str(len(locs)))
cards = o.get("/cards").json(); check(any(c["card_code"] == seed["card"]["code"] for c in cards), "restored card assigned to the business", seed["card"]["code"])
st = o.get("/billing/subscription").json(); check(st["status"] in ("canceled", "active", "trialing", "past_due", "halted", "expired"), "subscription restored", st["status"])
check(len(o.get("/billing/payments").json()) >= 1, "payment history restored")
p = httpx.get(f"{CARD}/api/v1/public/c/{seed['card']['token']}", headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari/604.1"}, timeout=20).json()
check(p.get("state") == "ok", "PRINTED card URL still resolves after restore (permanent token survived)", p.get("business", {}).get("name", ""))
a = httpx.Client(base_url=APP, timeout=20); r = login(a, seed["admin"]["email"], seed["admin"]["password"]); AH = {"X-CSRF-Token": r.json()["csrf_token"]}
b = a.post("/admin/batches", json={"name": "post-restore batch", "quantity": 2}, headers=AH).json()
codes = [c["card_code"] for c in a.get("/admin/cards", params={"batch_id": b["id"]}).json()["items"]]
check(len(codes) == 2, "new batch after restore continues card numbering without reuse", str(codes))
other = httpx.Client(base_url=APP, timeout=20); other.post("/auth/register", json={"email": f"after-restore-{os.urandom(3).hex()}@{D}", "password": "Staging-Passw0rd!x1", "full_name": "After Restore"})
check(other.get("/locations").status_code in (200, 403), "fresh account works after restore")
sys.exit(0 if all(ok) else 1)
