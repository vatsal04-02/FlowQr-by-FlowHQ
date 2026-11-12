"""Seed an ISOLATED demo stack with realistic, clearly-synthetic data for screenshots and design review.

Never run this against a database that holds real customers. It is meant for the throw-away compose project
described in docs/ART_DIRECTION_AND_UI_AUDIT.md ("Demo stack"):

    Get-Content e2e/seed_demo.py | docker compose -p flowqr-demo ... exec -T api python -

Real flows go through the public HTTP API (register, onboarding, locations, card batches, assignment).
The two things that normally arrive from outside FlowQR are written directly: Google-synced reviews and
QR/NFC scan events. Every review below is synthetic and every reviewer is an initial pair, not a person.
"""
import random
from datetime import timedelta

import httpx

from app.core.db import system_session
from app.models import (
    GoogleConnection, GoogleConnectionStatus, GoogleLocation, Location, QRCard, ReplyDraft, ReplyLog, ReplyStatus,
    Review, ScanEvent, ScanEventType, Tenant, User,
)
from app.models.base import utcnow
from sqlalchemy import select

BASE = "http://localhost:8000/api/v1"
PASSWORD = "DemoPassw0rd!x"
OWNER, ADMIN = "demo-owner@example.com", "demo-admin@example.com"
random.seed(7)


def client(email: str, name: str) -> tuple[httpx.Client, dict]:
    c = httpx.Client(base_url=BASE, timeout=30)
    r = c.post("/auth/register", json={"email": email, "password": PASSWORD, "full_name": name})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PASSWORD})
    r.raise_for_status()
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


owner, oh = client(OWNER, "Demo Owner")
admin, ah = client(ADMIN, "Demo Platform Admin")

# A brand-new business (location only: no cards, reviews or scans) to review the first-run dashboard,
# and an account that has registered but not finished onboarding.
FRESH, ONBOARDING = "demo-new@example.com", "demo-onboarding@example.com"
fresh, fh = client(FRESH, "Demo New Owner")
if not fresh.get("/auth/me").json()["memberships"]:
    fresh.post("/tenants", headers=fh, json={"name": "New Demo Clinic", "category": "Physiotherapy clinic", "language": "en", "timezone": "Asia/Kolkata"}).raise_for_status()
    fresh.post("/locations", headers=fh, json={"name": "Only branch", "city": "Lucknow", "state": "Uttar Pradesh"}).raise_for_status()
    fresh.post("/tenant/complete-onboarding", headers=fh).raise_for_status()
client(ONBOARDING, "Demo Onboarding User")

# ---- business, locations, onboarding (real API) -------------------------------------------------------------
if not owner.get("/auth/me").json()["memberships"]:
    owner.post("/tenants", headers=oh, json={"name": "Demo Clinic", "category": "Physiotherapy clinic", "email": "hello@example.com",
                                              "phone": "9876543210", "address": "Illustrative address", "language": "en", "timezone": "Asia/Kolkata"}).raise_for_status()
    for name, city, url in [("Main branch", "Lucknow", "https://g.page/r/DemoMain/review"), ("Second branch", "Kanpur", "https://g.page/r/DemoSecond/review"), ("Third branch", "Agra", None)]:
        owner.post("/locations", headers=oh, json={"name": name, "city": city, "state": "Uttar Pradesh", "review_url": url}).raise_for_status()
    owner.post("/tenant/complete-onboarding", headers=oh).raise_for_status()
locs = owner.get("/locations").json()
tenant_id = owner.get("/auth/me").json()["memberships"][0]["tenant"]["id"]

# ---- card batch + assignment (real admin API) ---------------------------------------------------------------
if not admin.get("/admin/cards", params={"search": "FQR-"}).json()["items"]:
    admin.post("/admin/batches", headers=ah, json={"name": "Demo batch", "quantity": 8}).raise_for_status()
cards = admin.get("/admin/cards", params={"limit": 50}).json()["items"]
plan = [("Reception desk", 0), ("Waiting area", 0), ("Checkout counter", 1), ("Front desk", 1)]
for card, (label, li) in zip(cards, plan):
    if card["status"] == "unassigned":
        admin.post(f"/admin/cards/{card['id']}/assign", headers=ah, json={"tenant_id": tenant_id, "location_id": locs[li]["id"], "label": label}).raise_for_status()
for card in cards[:3]:
    admin.post(f"/admin/cards/{card['id']}/status", headers=ah, json={"status": "active"})
if len(cards) > 3:
    admin.post(f"/admin/cards/{cards[3]['id']}/status", headers=ah, json={"status": "deactivated"})

# ---- externally-sourced data: Google reviews and scan events (direct) ---------------------------------------
db = system_session()
now = utcnow()
tenant = db.get(Tenant, tenant_id)
for u in db.scalars(select(User).where(User.email.in_([OWNER, ADMIN, FRESH, ONBOARDING]))):  # demo accounts: skip the email-verification banner
    u.email_verified_at = u.email_verified_at or now
if not db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == tenant.id)):
    conn = GoogleConnection(tenant_id=tenant.id, google_email="owner@example.com", status=GoogleConnectionStatus.active,
                            scopes="business.manage", connected_at=now - timedelta(days=40))
    db.add(conn); db.flush()
    gls = []
    for i, loc in enumerate(db.scalars(select(Location).where(Location.tenant_id == tenant.id).order_by(Location.name)).all()[:3]):
        # Main/Second branch synced; Third branch is discovered on Google but not selected yet.
        gl = GoogleLocation(tenant_id=tenant.id, connection_id=conn.id, location_id=loc.id if i < 2 else None, google_account_name="accounts/1",
                            google_location_name=f"locations/{100 + i}", title=f"Demo Clinic, {loc.city}", address=f"Illustrative address, {loc.city}",
                            selected=i < 2, last_synced_at=now - timedelta(minutes=12 + 7 * i) if i < 2 else None,
                            last_sync_status="ok" if i < 2 else None)
        db.add(gl); gls.append((gl, loc))
    db.flush()

    texts = {
        5: ["Booked online and was seen on time. The staff explained every step clearly.", "Clean clinic, friendly reception and a treatment plan that was easy to follow.",
            "Quick appointment and helpful follow-up. Would recommend.", "Doctor ne dhyan se suna aur achhe se samjhaya. Thank you!", "Very smooth experience from check-in to billing.",
            None, "Helpful team, good communication throughout.", "Exercises were explained properly and progress was tracked every visit."],
        4: ["Good service overall. The waiting area was a bit crowded.", "Helpful staff. Parking is limited but the visit itself was good."],
        3: ["Treatment was fine but I waited over 40 minutes past my slot."],
        2: ["Billing took long and the estimate changed at the counter."],
        1: ["Long wait and nobody updated me. I would like a refund for the extra session."],
    }
    ratings = [5] * 26 + [4] * 7 + [3] * 3 + [2] * 2 + [1] * 2
    random.shuffle(ratings)
    initials = ["A. S.", "R. K.", "M. P.", "S. T.", "N. V.", "K. R.", "D. G.", "P. M.", "V. L.", "H. B."]
    reviews = []
    for n, rating in enumerate(ratings):
        gl, loc = gls[0] if n % 3 else gls[1]
        age = random.randint(0, 58) if n >= 6 else random.randint(0, 3)
        created = now - timedelta(days=age, hours=random.randint(0, 9))
        rv = Review(tenant_id=tenant.id, location_id=loc.id, google_location_id=gl.id, external_id=f"demo-{n}", rating=rating,
                    text=random.choice(texts[rating]), reviewer_name=random.choice(initials), review_created_at=created, first_seen_at=created + timedelta(minutes=30))
        db.add(rv); reviews.append(rv)
    db.flush()
    reviews.sort(key=lambda r: r.review_created_at, reverse=True)

    drafts = 0
    for k, rv in enumerate(reviews):
        if k == 1 and rv.rating >= 4:
            rv.reviewer_name = "A. S."
        if k < 9:  # recent: needs a reply, some with AI drafts, one failed, one approved
            if k in (1, 3, 4):
                db.add(ReplyDraft(tenant_id=tenant.id, review_id=rv.id, status=ReplyStatus.draft, generated_by_ai=True, language="en",
                                  body="Thank you for taking the time to share this. We're glad the visit went well and we look forward to seeing you again.", created_at=rv.review_created_at + timedelta(hours=2)))
            if k == 2:
                d = ReplyDraft(tenant_id=tenant.id, review_id=rv.id, status=ReplyStatus.failed, generated_by_ai=True, language="en", attempts=2,
                               failure_reason="Google did not accept the reply (rate limited). Try again shortly.", approved_at=now - timedelta(hours=3),
                               body="Thank you for your kind words. We appreciate your feedback and hope to see you again.", created_at=rv.review_created_at + timedelta(hours=1))
                db.add(d); db.flush()
                db.add(ReplyLog(tenant_id=tenant.id, review_id=rv.id, draft_id=d.id, action="publish_attempt", success=False, http_status=429,
                                error="Rate limited by Google", created_at=now - timedelta(hours=2, minutes=40)))
            if k == 5:
                db.add(ReplyDraft(tenant_id=tenant.id, review_id=rv.id, status=ReplyStatus.approved, generated_by_ai=False, language="en", approved_at=now - timedelta(minutes=30),
                                  body="Thank you for your feedback. We're happy the team could help.", created_at=rv.review_created_at + timedelta(hours=1)))
        else:  # older: mostly replied
            if k % 5 != 0:
                rv.google_reply_text = "Thank you for your feedback. We're glad we could help and look forward to seeing you again."
                rv.google_reply_at = rv.review_created_at + timedelta(hours=random.randint(2, 30))
                d = ReplyDraft(tenant_id=tenant.id, review_id=rv.id, status=ReplyStatus.published, generated_by_ai=k % 2 == 0, language="en", attempts=1,
                               body=rv.google_reply_text, approved_at=rv.google_reply_at - timedelta(minutes=5), published_at=rv.google_reply_at, created_at=rv.google_reply_at - timedelta(minutes=20))
                db.add(d); db.flush()
                db.add(ReplyLog(tenant_id=tenant.id, review_id=rv.id, draft_id=d.id, action="publish_attempt", success=True, http_status=200, created_at=rv.google_reply_at))

# scan activity for the three active cards over the last 30 days; the deactivated one has history only
if not db.scalar(select(ScanEvent).where(ScanEvent.tenant_id == tenant.id)):
    owned = db.scalars(select(QRCard).where(QRCard.tenant_id == tenant.id).order_by(QRCard.card_code)).all()
    weight = [1.0, 0.7, 0.5, 0.2]
    for ci, card in enumerate(owned):
        for day in range(30):
            if ci == 3 and day < 12:
                continue  # deactivated 12 days ago
            for _ in range(int(random.gauss(7, 3) * weight[ci]) if ci < 4 else 0):
                t = now - timedelta(days=day, hours=random.randint(0, 11), minutes=random.randint(0, 59))
                visitor = f"demo{random.getrandbits(40):x}"
                steps = [ScanEventType.scan]
                if random.random() < 0.86:
                    steps.append(ScanEventType.landing_view)
                    if random.random() < 0.45:
                        steps.append(ScanEventType.ai_assist)
                    if random.random() < 0.64:
                        steps.append(ScanEventType.google_click)
                for s in steps:
                    db.add(ScanEvent(card_id=card.id, tenant_id=tenant.id, location_id=card.location_id, event_type=s, visitor_hash=visitor, is_bot=False, created_at=t))
db.commit()
print("seeded:", {"tenant": tenant.name, "locations": len(locs), "cards": len(cards)})
print("owner:", OWNER, " admin:", ADMIN, " password:", PASSWORD)
