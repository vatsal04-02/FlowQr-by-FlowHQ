import os, re, sys, collections
sys.argv = ["x", "run"]; sys.path.insert(0, "../../audit")
import bench  # sets the environment for the bench database
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import event
from app.core.db import engine
from app.main import app
paths = sys.stdin.read().split()
stmts = []
@event.listens_for(engine, "before_cursor_execute")
def _c(conn, cur, st, p, ctx, many): stmts.append(re.sub(r"\s+", " ", st)[:150])
today = date.today()
with TestClient(app, base_url="http://testserver") as c:
    c.post("/api/v1/auth/login", json={"email": "bench0@example.com", "password": bench.PW})
    for path in paths:
        path = path.replace("{d0}", today.isoformat()).replace("{d30}", (today - timedelta(days=29)).isoformat())
        c.get("/api/v1" + path); stmts.clear(); c.get("/api/v1" + path)
        cnt = collections.Counter(stmts)
        print(f"\n== {path}: {len(stmts)} statements, {len(cnt)} distinct")
        for st, n in cnt.most_common(5):
            if n > 1: print(f"  x{n}  {st}")
