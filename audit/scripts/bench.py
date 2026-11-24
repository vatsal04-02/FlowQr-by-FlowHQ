"""Backend benchmark: real FastAPI handlers, real PostgreSQL with RLS, a realistic volume of data, per-endpoint latency and SQL statements per request.
Usage:  python bench.py seed     (once, builds the data in database flowqr_bench)
        python bench.py run [label]  (measures; writes results/<label>.json)
Everything runs against a LOCAL throwaway database. Nothing here touches production."""
import json
import os
import random
import statistics
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone

PORT = os.environ.get("BENCH_PG_PORT", "55441")
os.environ.update({
    "APP_ENV": "test", "RATE_LIMIT_ENABLED": "false", "REDIS_URL": "redis://127.0.0.1:1/0",
    "DATABASE_URL": f"postgresql+psycopg://flowqr_app:flowqr_app_dev@127.0.0.1:{PORT}/flowqr_bench",
    "MIGRATION_DATABASE_URL": f"postgresql+psycopg://flowqr:flowqr_dev@127.0.0.1:{PORT}/flowqr_bench",
    "TOKEN_ENCRYPTION_KEY": "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZS1rZXktMTIzNDU=", "GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "y",
    "GEMINI_API_KEY": "", "PUBLIC_CARD_BASE_URL": "https://go.test.flowqr.example", "PLATFORM_ADMIN_EMAILS": "root@flowhq-admin.example.com",
})
sys.path.insert(0, ".")
from sqlalchemy import create_engine, event, text  # noqa: E402

PW = "Str0ngPassw0rd!bench"
OWNER_URL = os.environ["MIGRATION_DATABASE_URL"]


def seed():
    import subprocess
    adm = create_engine(OWNER_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with adm.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS flowqr_bench"))
        c.execute(text("CREATE DATABASE flowqr_bench OWNER flowqr"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=os.environ.copy())
    from fastapi.testclient import TestClient
    from app.main import app
    random.seed(7)
    users = []
    with TestClient(app, base_url="http://testserver") as c:
        def mk(i, name):
            email = f"bench{i}@example.com"
            r = c.post("/api/v1/auth/register", json={"email": email, "password": PW, "age_confirmed": True, "full_name": f"Owner {i}"})
            assert r.status_code == 201, r.text
            csrf = r.json()["csrf_token"]
            eng = create_engine(OWNER_URL)
            with eng.begin() as cn:
                cn.execute(text("update users set email_verified_at=now() where email=:e"), {"e": email})
            h = {"X-CSRF-Token": csrf}
            t = c.post("/api/v1/tenants", json={"name": name, "category": "Physiotherapy clinic", "language": "en"}, headers=h)
            assert t.status_code == 201, t.text
            loc = c.post("/api/v1/locations", json={"name": f"{name} Main", "city": "Lucknow", "review_url": "https://g.page/r/ABC123/review"}, headers=h)
            assert loc.status_code == 201, loc.text
            users.append((email, t.json()["id"], loc.json()["id"]))
        mk(0, "Busy Clinic")
        for i in range(1, 41):
            mk(i, f"Small Business {i}")
    eng = create_engine(OWNER_URL)
    tid, lid = users[0][1], users[0][2]
    now = datetime.now(timezone.utc)
    with eng.begin() as cn:
        cn.execute(text("update tenants set onboarding_completed=true"))
        cn.execute(text("update subscriptions set max_locations=10"))
        conn_id = uuid.uuid4()
        cn.execute(text("insert into google_connections (id,tenant_id,google_email,scopes,status,api_access,created_at,updated_at) values (:i,:t,'o@example.com','https://www.googleapis.com/auth/business.manage','active','approved',now(),now())"), {"i": conn_id, "t": tid})
        glocs = []
        for n in range(3):
            g = uuid.uuid4(); glocs.append(g)
            cn.execute(text("insert into google_locations (id,tenant_id,connection_id,location_id,google_account_name,google_location_name,title,address,selected,consecutive_failures,created_at,updated_at) values (:i,:t,:c,:l,'accounts/1',:n,'Busy Clinic','Gomti Nagar, Lucknow, UP',true,0,now(),now())"), {"i": g, "t": tid, "c": conn_id, "l": lid, "n": f"locations/{n+1}"})
        # 900 reviews, ~60% replied
        for n in range(900):
            cn.execute(text("insert into reviews (id,tenant_id,location_id,google_location_id,external_id,rating,text,reviewer_name,review_created_at,first_seen_at,update_count,google_reply_text,created_at,updated_at) values (gen_random_uuid(),:t,:l,:g,:e,:r,:x,'Asha',:d,:d,0,:rep,now(),now())"),
                       {"t": tid, "l": lid, "g": glocs[n % 3], "e": f"r{n}", "r": random.choice([5, 5, 5, 4, 4, 3, 2, 1]), "x": "Good service and friendly staff. " * random.randint(1, 4),
                        "d": now - timedelta(days=random.randint(0, 700)), "rep": "Thank you!" if n % 5 else None})
        # 2 years of daily metrics x 6 metrics x 3 locations
        for g in glocs:
            for m in ("CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "BUSINESS_BOOKINGS"):
                cn.execute(text("insert into gbp_metric_daily (id,tenant_id,google_location_id,metric,day,value,source,first_fetched_at,fetched_at) select gen_random_uuid(),:t,:g,:m,(current_date - s)::date,(random()*40)::int,'performance_api',now(),now() from generate_series(1,730) s"), {"t": tid, "g": g, "m": m})
        # 300 posts in mixed states (the campaign link is the Marketing Studio one)
        cn.execute(text("insert into marketing_campaigns (id,tenant_id,google_location_id,title,brief,objective,duration_days,start_date,status,created_at,updated_at) values (gen_random_uuid(),:t,:g,'Winter','Winter back care for office workers','keep_active',30,current_date,'ready',now(),now())"), {"t": tid, "g": glocs[0]})
        cn.execute(text("insert into scheduled_posts (id,tenant_id,google_location_id,summary,status,generated_by_ai,topic_type,campaign_id,created_at,updated_at,language,attempts) select gen_random_uuid(),:t,:g,'Post number '||s||' about back care and friendly staff at the clinic',(array['draft','awaiting_approval','scheduled','published','failed'])[1+(s%5)],true,'STANDARD',(select id from marketing_campaigns limit 1),now()-(s||' hours')::interval,now(),'en',0 from generate_series(1,300) s"), {"t": tid, "g": glocs[0]})
        # scans and audit rows (volume for the analytics and audit queries)
        cn.execute(text("insert into audit_logs (id,tenant_id,action,metadata,created_at) select gen_random_uuid(),:t,'bench.event','{}'::jsonb,now()-(s||' minutes')::interval from generate_series(1,6000) s"), {"t": tid})
        cn.execute(text("insert into review_campaigns (id,tenant_id,location_id,name,public_id,status,customization,created_at,updated_at) values (gen_random_uuid(),:t,:l,'Counter','bench0001',  'active','{}',now(),now())"), {"t": tid, "l": lid})
    print("seeded: 41 businesses; the busy one has 900 reviews, 3 locations, 13,140 metric rows, 300 posts, 6,000 audit rows")


ENDPOINTS = [
    ("GET", "/auth/me"), ("GET", "/locations"), ("GET", "/google/status"), ("GET", "/reviews?limit=50"), ("GET", "/reviews?reply_state=none&limit=20"),
    ("GET", "/analytics/overview?from={d30}&to={d0}"), ("GET", "/analytics/growth-score"), ("GET", "/analytics/google-metrics?from={d30}&to={d0}"),
    ("GET", "/posts?limit=100"), ("GET", "/posts/calendar?from={d30}&to={d0}"), ("GET", "/marketing/overview"), ("GET", "/marketing/campaigns"),
    ("GET", "/agent/tasks?scope=today"), ("GET", "/agent/activity"), ("GET", "/cards"), ("GET", "/review-growth/campaigns"), ("GET", "/review-growth/analytics"),
    ("GET", "/settings/team" if False else "/staff"), ("GET", "/seo/overview"),
]


def run(label):
    from fastapi.testclient import TestClient
    from app.core.db import engine
    from app.main import app
    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    today = date.today()
    fmt = {"d0": today.isoformat(), "d30": (today - timedelta(days=29)).isoformat()}
    out = {}
    with TestClient(app, base_url="http://testserver") as c:
        r = c.post("/api/v1/auth/login", json={"email": "bench0@example.com", "password": PW})
        assert r.status_code == 200, r.text
        # the owner's active business is the first one
        for method, path in ENDPOINTS:
            url = "/api/v1" + path.format(**fmt)
            c.request(method, url)  # warm-up (connection pool, imports, plan cache)
            lat, q, status = [], [], None
            for _ in range(25):
                counter["n"] = 0
                t0 = time.perf_counter()
                resp = c.request(method, url)
                lat.append((time.perf_counter() - t0) * 1000)
                q.append(counter["n"])
                status = resp.status_code
            lat.sort()
            out[path.split("?")[0]] = {"status": status, "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1), "max_ms": round(lat[-1], 1),
                                       "queries": round(statistics.median(q)), "bytes": len(resp.content)}
    os.makedirs("../audit/results", exist_ok=True)
    json.dump(out, open(f"../audit/results/{label}.json", "w"), indent=1)
    w = max(len(k) for k in out)
    print(f"{'endpoint':<{w}}  status  p50ms  p95ms  max   SQL  bytes")
    for k, v in sorted(out.items(), key=lambda kv: -kv[1]["p50_ms"]):
        print(f"{k:<{w}}  {v['status']:>5}  {v['p50_ms']:>6}  {v['p95_ms']:>6}  {v['max_ms']:>6}  {v['queries']:>3}  {v['bytes']:>7}")


if __name__ == "__main__":
    seed() if sys.argv[1] == "seed" else run(sys.argv[2] if len(sys.argv) > 2 else "before")
