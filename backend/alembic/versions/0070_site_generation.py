"""AI website generation from onboarding: the generation job, and a hosting status for a draft an owner generated that nobody has activated.

Revision ID: 0070
Revises: 0069

Additive. One new tenant table (`site_generation_jobs`, forced row-level security like every tenant table; at most one queued or running job per business) and one more allowed value of
`sites.commercial_status`: `not_activated`. A site in that status can be edited and previewed but never published (services/sites/service.commercial_blockers already refuses anything that
is not complimentary or paid_offline). Downgrade turns such sites into `expired` and drops the table.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "site_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="INITIALIZING"),
        sa.Column("steps", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("notes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.String(300)),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status in ('queued', 'running', 'completed', 'failed')", name="ck_site_generation_status"),
    )
    op.create_index("ix_site_generation_tenant", "site_generation_jobs", ["tenant_id", "created_at"])
    op.create_index("uq_site_generation_active", "site_generation_jobs", ["tenant_id"], unique=True, postgresql_where=sa.text("status in ('queued', 'running')"))
    op.execute("ALTER TABLE site_generation_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE site_generation_jobs FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON site_generation_jobs USING ({COND}) WITH CHECK ({COND})")
    op.execute("""
        DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowqr_app') THEN GRANT SELECT, INSERT, UPDATE, DELETE ON site_generation_jobs TO flowqr_app; END IF; END $$
    """)
    op.drop_constraint("ck_sites_commercial", "sites", type_="check")
    op.create_check_constraint("ck_sites_commercial", "sites", "commercial_status in ('complimentary', 'paid_offline', 'expired', 'suspended', 'not_activated')")


def downgrade() -> None:
    op.execute("UPDATE sites SET commercial_status = 'expired' WHERE commercial_status = 'not_activated'")
    op.drop_constraint("ck_sites_commercial", "sites", type_="check")
    op.create_check_constraint("ck_sites_commercial", "sites", "commercial_status in ('complimentary', 'paid_offline', 'expired', 'suspended')")
    op.drop_table("site_generation_jobs")
