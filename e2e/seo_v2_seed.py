import uuid
from datetime import timedelta
from sqlalchemy import select, text
from app.core.config import settings
from app.core.db import system_session
from app.models import GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Tenant, AgentAction
from app.models.base import utcnow
from app.services.agent import executor, seo_engine
from app.services.agent.v2 import owner

db = system_session()
db.execute(text("UPDATE users SET email_verified_at = now() WHERE email = '__EMAIL__'"))
tid, lid = uuid.UUID("__TID__"), uuid.UUID("__LID__")
t = db.get(Tenant, tid)
t.review_context = {"description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back care", "Neck pain physiotherapy", "Sports injury rehab"]}
t.phone = "+91 90000 00000"
t.address = "12 MG Road, Gomti Nagar, Lucknow 226010"
c = GoogleConnection(tenant_id=tid, google_email="seeded@example.com", google_sub="seeded-" + str(tid)[:6], status=GoogleConnectionStatus.active, api_access="approved", connected_at=utcnow())
db.add(c); db.flush()
g = GoogleLocation(tenant_id=tid, connection_id=c.id, location_id=lid, google_account_name="accounts/1", google_location_name="locations/9001", title="SEO Main (Google)", address="12 MG Road, Gomti Nagar, Lucknow", selected=True, last_synced_at=utcnow(), last_sync_status="ok")
db.add(g); db.flush()
PRIMARY = "categories/gcid:physiotherapist"
info = {"title": "Gomti Physio", "description": "Physio clinic in Lucknow offering back care and neck pain physiotherapy. Call us to book a visit or ask a question about our services.", "phone": "+91 98765 43210", "website": "https://clinic.example.com",
        "primary_category": {"id": PRIMARY, "name": "Physiotherapist"}, "additional_categories": [], "hours": [{"day": "MONDAY", "open": "09:00", "close": "18:00"}],
        "services": ["job_type_id:dry_needling"], "special_hours": [], "open_status": "OPEN",
        "service_items": [{"k": "s", "id": "job_type_id:dry_needling"}], "special_hours_periods": [], "service_area": None, "storefront_address": True, "has_regular_hours": True,
        "can_modify_service_list": True, "language_code": "en", "attributes": [],
        "catalog": {"fetched_at": utcnow().isoformat(),
                    "service_types": {PRIMARY: [{"id": "job_type_id:back_care", "name": "Back care"}, {"id": "job_type_id:dry_needling", "name": "Dry needling"}]},
                    "attribute_metadata": {"attributes/has_wheelchair_accessible_entrance": {"valueType": "BOOL", "displayName": "Wheelchair accessible entrance"},
                                           "attributes/wi_fi": {"valueType": "ENUM", "displayName": "Wi-Fi", "valueMetadata": [{"value": "free_wifi", "displayName": "Free"}]}},
                    "categories": {"candidates": [{"id": "categories/gcid:sports_injury_clinic", "name": "Sports injury clinic", "matched_term": "Sports injury rehab"}, {"id": "categories/gcid:pizza_restaurant", "name": "Pizza restaurant", "matched_term": "x"}],
                                   "searched_at": utcnow().isoformat(), "terms": []},
                    "google_updated": {"diff_mask": "", "pending_mask": "", "checked_at": utcnow().isoformat()}}}
db.add(GbpSnapshot(tenant_id=tid, google_location_id=g.id, fetched_at=utcnow(), media=[], posts=[], info=info,
                   performance={"current": 40, "previous": 30, "window_days": 28, "from": "2026-10-01", "to": "2026-10-28", "metrics": [], "keywords": [{"keyword": "back pain treatment", "value": 120, "below": None}], "keywords_months": ["2026-08", "2026-10"]}))
db.commit()
if "__MODE__" == "test":
    settings.seo_v2_test_location_names = "locations/9001"   # applies only inside this seed process; the API container reads its own env
out = seo_engine.scan_tenant(db, db.get(Tenant, tid))
db.commit()
# a blocked change (invalid special hours) created through the real owner path
uid = db.execute(text("select user_id from memberships where tenant_id = :t limit 1"), {"t": tid}).scalar()
try:
    a = owner.propose_special_hours(db, db.get(Tenant, tid), g, user_id=uid, entries=[{"start": "2099-11-30", "open": "14:00", "close": "09:00"}])
    db.commit()
except Exception as e:
    db.rollback(); print("blocked-proposal error", e)
# a failed change and a verified change: real proposals, then their outcome recorded the way the executor would (seed data in a throwaway database)
a1 = executor.propose(db, db.get(Tenant, tid), g, "description_improve", proposed="Physio clinic in Lucknow offering back care, neck pain physiotherapy and sports injury rehab. Call us to book a visit or ask any question about our services.",
                      source={"kind": "business_knowledge", "refs": ["description", "services"]}, trigger="optimizer:description", problem="Seeded failed example.", reason="Seeded.")
db.commit()
db.execute(text("UPDATE agent_actions SET status='failed', last_error='Google accepted the request but its profile does not show the new description yet.' WHERE id=:i"), {"i": a1.id})
a2 = owner.propose_attributes(db, db.get(Tenant, tid), g, user_id=uid, answers=[{"name": "wi_fi", "value": "free_wifi"}]) if False else None
import json
from app.models import AgentAction as AA
v = AA(tenant_id=tid, google_location_id=g.id, action_type="special_hours_update", field_key="special_hours", trigger="owner_request", problem="You added special hours for 2099-12-24.", reason="r", expected_outcome="e",
       evidence={}, source={}, current_value={"value": []}, proposed_value={"value": [], "canonical": [{"start": "2099-12-24", "end": "2099-12-24", "closed": True, "open": None, "close": None}]},
       base_fingerprint="b", value_hash="v", facts_fingerprint="f", idempotency_key="seeded-verified", policy_level=2, effective_type="special_hours_update", risk_level="medium", policy_reasons=[],
       authorization="owner", status="executed", proposed_by="user", attempts=1, executed_at=utcnow(), verified_at=utcnow(), verification={"matched": True})
db.add(v)
db.commit()
print("scan:", out)
print(g.id)
