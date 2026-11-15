"""Book-a-demo leads from the public marketing site."""
from sqlalchemy import create_engine, text

from app.core.config import settings

GOOD = {"name": "Asha Rao", "business_name": "Sunrise Physio", "city": "Bengaluru", "business_type": "clinic", "locations": 2,
        "phone": "98765 43210", "whatsapp_ok": True, "preferred_time": "Weekday mornings"}


def _rows():
    owner = create_engine(settings.migration_database_url)
    with owner.connect() as c:
        return c.execute(text("SELECT name, phone, whatsapp_ok, ip_hash FROM leads ORDER BY created_at")).all()


def test_lead_is_saved_with_a_normalised_phone_and_no_raw_ip(client):
    r = client.post("/api/v1/public/leads", json=GOOD)
    assert r.status_code == 201 and r.json() == {"ok": True}
    rows = _rows()
    assert rows[-1].name == "Asha Rao" and rows[-1].phone == "+919876543210" and rows[-1].whatsapp_ok is True
    assert rows[-1].ip_hash is None or (len(rows[-1].ip_hash) == 64 and "testclient" not in rows[-1].ip_hash)


def test_validation_errors_are_reported(client):
    for bad in ({**GOOD, "phone": "12345"}, {**GOOD, "business_type": "casino"}, {**GOOD, "locations": 0}, {**GOOD, "name": ""}):
        assert client.post("/api/v1/public/leads", json=bad).status_code == 422


def test_honeypot_looks_like_success_but_stores_nothing(client):
    before = len(_rows())
    r = client.post("/api/v1/public/leads", json={**GOOD, "website": "http://spam.example"})
    assert r.status_code == 201 and r.json() == {"ok": True}
    assert len(_rows()) == before


def test_rate_limited_per_address(client):
    codes = [client.post("/api/v1/public/leads", json={**GOOD, "name": f"Person {i}"}).status_code for i in range(7)]
    assert codes[:5] == [201] * 5 and codes[5] == 429
