"""Migration 0072: review_drafts.suggestions, one nullable JSONB column. Additive, reversible, no existing row changes."""
import uuid

from tests.conftest import head_revision, make_business, owner_exec, owner_query
from tests.test_migration_0037 import alembic


def _has_column() -> bool:
    return bool(owner_query("SELECT 1 FROM information_schema.columns WHERE table_name = 'review_drafts' AND column_name = 'suggestions'"))


def test_the_column_is_nullable_and_the_downgrade_drops_only_it_then_the_upgrade_restores_it():
    biz = make_business("Migration 0072 Clinic")
    camp, sess, draft = (str(uuid.uuid4()) for _ in range(3))
    owner_exec("INSERT INTO review_campaigns (id, tenant_id, location_id, name, public_id, status, customization, created_at, updated_at) VALUES (:c, :t, :l, 'm', :p, 'active', '{}', now(), now())",
               c=camp, t=biz.tenant_id, l=biz.location_id, p="m72" + uuid.uuid4().hex[:8])
    owner_exec("INSERT INTO review_sessions (id, tenant_id, campaign_id, session_identifier, language, style, customer_input, created_at) VALUES (:s, :t, :c, :i, 'en', 'natural', '{}', now())",
               s=sess, t=biz.tenant_id, c=camp, i="m72" + uuid.uuid4().hex[:10])
    owner_exec("INSERT INTO review_drafts (id, tenant_id, session_id, generated_content, generation_count, ai_assisted, created_at, updated_at) VALUES (:d, :t, :s, 'Kept text.', 1, true, now(), now())",
               d=draft, t=biz.tenant_id, s=sess)
    assert _has_column() and owner_query("SELECT suggestions FROM review_drafts WHERE id = :d", d=draft)[0][0] is None  # an older draft simply has none
    try:
        alembic("downgrade", "0071")
        assert not _has_column()
        assert owner_query("SELECT generated_content FROM review_drafts WHERE id = :d", d=draft)[0][0] == "Kept text."  # the row and its text survived
    finally:
        alembic("upgrade", "head")
    assert _has_column() and owner_query("SELECT version_num FROM alembic_version")[0][0] == head_revision()
    assert tuple(owner_query("SELECT generated_content, suggestions FROM review_drafts WHERE id = :d", d=draft)[0]) == ("Kept text.", None)
