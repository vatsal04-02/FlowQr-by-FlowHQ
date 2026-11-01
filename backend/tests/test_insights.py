import pytest

from app.services.insights import analyse, sentiment, topics_in
from tests.test_google_and_reviews import connected, fake, greview, sync_select  # noqa: F401


@pytest.mark.parametrize("rating,text,expected", [
    (5, "Great doctor, very kind", "positive"), (1, "Worst experience, rude staff", "negative"),
    (3, "okay but staff was very helpful and friendly, great", "positive"), (3, "bad, waste of time, terrible", "negative"),
    (3, "it was fine", "neutral"), (5, None, "positive"), (2, None, "negative"),
    (1, "bahut badhiya zabardast excellent great", "positive"),   # clear contradiction flips a 1-star
])
def test_sentiment(rating, text, expected):
    assert sentiment(rating, text) == expected


def test_topics_in_english_hinglish_hindi():
    assert {"wait_time", "staff"} <= set(topics_in("We had to wait an hour and the reception staff were rude"))
    assert "results" in topics_in("meri dard mein bahut aaram mila")
    assert "pricing" in topics_in("fees बहुत महंगा hai")
    assert "cleanliness" in topics_in("क्लिनिक साफ है")
    assert topics_in("lovely") == []


def test_analyse_counts_and_previous_period():
    cur = [(1, "long wait, rude staff"), (2, "waiting too long"), (5, "doctor was great, pain relief")]
    prev = [(4, "wait was short")]
    r = analyse(cur, prev)
    wait = next(t for t in r["topics"] if t["topic"] == "wait_time")
    assert wait["mentions"] == 2 and wait["negative"] == 2 and wait["previous_mentions"] == 1 and wait["sample"]
    assert r["sentiment"] == {"positive": 1, "neutral": 0, "negative": 2} and r["method"]


def test_insights_endpoint_gated_and_isolated(connected, fake, biz_b):  # noqa: F811
    fake.reviews = [greview(1, 1, "Waited long, staff rude"), greview(2, 5, "Doctor great, pain relief")]
    sync_select(connected, fake)
    r = connected.get("/analytics/insights", params={"from": "2024-12-01", "to": "2025-01-31"})
    assert r.status_code == 200 and r.json()["total_reviews"] == 2
    assert {t["topic"] for t in r.json()["topics"]} >= {"wait_time", "staff", "doctor", "results"}
    assert biz_b.get("/analytics/insights", params={"from": "2024-12-01", "to": "2025-01-31"}).json()["total_reviews"] == 0
    from tests.test_billing import db_sub
    db, sub = db_sub(connected.tenant_id); sub.features = ["review_sync"]; db.commit(); db.close()
    assert connected.get("/analytics/insights").status_code == 402
