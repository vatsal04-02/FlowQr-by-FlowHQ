"""Row-level security FILTERS, on every tenant-owned table. The existing sweep proves each table has a forced policy; this proves the policy does its job: with the database session scoped to one
business, every tenant table returns exactly that business's rows and nothing of another's, and a session scoped to a business that owns nothing sees nothing at all. It runs as the application
role (the one the API uses), so a table whose policy is wrong, too loose, or missing from this list's source (the live catalogue) fails here, whatever the API code does."""
import uuid

from sqlalchemy import text

from app.core.db import SessionLocal, set_rls_context
from tests.conftest import make_business, owner_query
from tests.test_google_and_reviews import connected, sync_select  # noqa: F401
from tests.test_google_business_agent import fake  # noqa: F401


def _tenant_tables() -> list[str]:
    return [r[0] for r in owner_query(
        "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema "
        "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE' ORDER BY 1")]


def _count(table: str, *, tenant: uuid.UUID | None = None, bypass: bool = False, where_tenant: uuid.UUID | None = None) -> int:
    with SessionLocal() as db:
        set_rls_context(db, tenant_id=tenant, bypass=bypass)
        sql = f"SELECT count(*) FROM {table}" + (" WHERE tenant_id = :w" if where_tenant else "")  # table names come from the catalogue above, never from input
        return db.execute(text(sql), {"w": where_tenant} if where_tenant else {}).scalar()


def _seed(biz):
    """A few rows of different kinds, so the sweep has something to hide from the other business."""
    assert biz.post("/review-growth/campaigns", json={"name": f"Seed {biz.tenant_id[:6]}", "location_id": biz.location_id}).status_code == 201
    biz.put("/agent/knowledge", json={"description": "Seed description for the sweep.", "services": ["Back care"], "offers": [], "hours": "", "faqs": [], "brand_voice": "warm", "prohibited_claims": []})
    biz.post("/locations", json={"name": "Second branch", "city": "Kanpur", "review_url": "https://g.page/r/SEED2/review"})


def test_every_tenant_table_shows_a_business_only_its_own_rows(connected, fake, biz_b):  # noqa: F811
    sync_select(connected, fake)
    _seed(connected)
    _seed(biz_b)
    a, b = uuid.UUID(connected.tenant_id), uuid.UUID(biz_b.tenant_id)
    nobody = uuid.uuid4()  # a business that owns nothing
    tables = _tenant_tables()
    assert len(tables) >= 30
    wrong, populated = [], 0
    for t in tables:
        total = _count(t, bypass=True)
        mine_a, mine_b = _count(t, bypass=True, where_tenant=a), _count(t, bypass=True, where_tenant=b)
        seen_a, seen_b, seen_nobody = _count(t, tenant=a), _count(t, tenant=b), _count(t, tenant=nobody)
        populated += 1 if total else 0
        if seen_a != mine_a:
            wrong.append(f"{t}: business A sees {seen_a} rows but owns {mine_a}")
        if seen_b != mine_b:
            wrong.append(f"{t}: business B sees {seen_b} rows but owns {mine_b}")
        if seen_nobody != 0:
            wrong.append(f"{t}: a business that owns nothing sees {seen_nobody} rows")
        if mine_a and total > mine_a and seen_a == total:
            wrong.append(f"{t}: business A sees other businesses' rows ({seen_a} of {total})")
    assert populated >= 8, f"the sweep only exercised {populated} tables with data; seed more so it proves something"
    assert not wrong, "row-level security is not filtering:\n" + "\n".join(wrong)


def test_with_no_business_set_and_no_bypass_a_tenant_table_shows_nothing(connected, fake):  # noqa: F811
    """A request that somehow reaches the database with no tenant context must see zero rows, never everything."""
    sync_select(connected, fake)
    leaky = [t for t in _tenant_tables() if _count(t, bypass=True) and _count(t) != 0]
    assert not leaky, f"tables that show rows to a session with no tenant set: {leaky}"
