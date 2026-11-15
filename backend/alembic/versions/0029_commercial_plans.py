"""Commercial plans (Starter / Growth / Pro), separate review-generation and reply allowances, plan limits that stay OFF until approved, subscription history,
promotional access (the Growth month that comes with a physical card), and card bundles.

Revision ID: 0029
Revises: 0028

* billing_plans / subscriptions gain review_generations, review_replies and limits (JSONB). Existing subscriptions are GRANDFATHERED: their location and seat limits are
  untouched, and their old combined allowance is split in half between the two new ones, so nobody ends up with less than they had. Features are refreshed from the plan so
  existing subscribers can use what their plan now includes.
* Starter / Growth / Pro are added; Essential and Multi stay as retired rows (is_active false) so existing subscribers and Razorpay plan ids keep resolving.
* geo-grid allowances are NULL on every plan: the owner has not approved any, so maps stay off until an admin sets them.
* subscription_events: append-only (the app role can only SELECT and INSERT). promotional_grants: one per card order. card_orders.offer_code.
"""
import json
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

CORE = ["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"]
GROWTH_ADD = ["gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent"]
LIMITS = {"geo": {"max_grids": None, "max_points": None, "monthly_points": None}}
# code, name, price_paise, max_locations, max_staff, generations, replies, features, sort
PLANS = [
    ("starter", "Starter", 49900, 1, 3, 200, 200, CORE, 1),
    ("growth", "Growth", 79900, 1, 10, 400, 400, CORE + GROWTH_ADD, 2),
    ("pro", "Pro", 149900, 10, 50, 800, 800, CORE + GROWTH_ADD + ["multi_location"], 3),
]


def _grant(table: str, privileges: str) -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {privileges} ON {table} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({COND}) WITH CHECK ({COND})")


def upgrade() -> None:
    for t in ("billing_plans", "subscriptions"):
        op.add_column(t, sa.Column("review_generations", sa.Integer(), nullable=False, server_default="0"))
        op.add_column(t, sa.Column("review_replies", sa.Integer(), nullable=False, server_default="0"))
        op.add_column(t, sa.Column("limits", JSONB(), nullable=False, server_default="{}"))
    op.add_column("card_orders", sa.Column("offer_code", sa.String(16)))

    # ---- the confirmed plans
    for code, name, price, locs, staff, gens, reps, feats, sort in PLANS:
        op.execute(sa.text(
            "INSERT INTO billing_plans (code, name, price_paise, currency, interval, max_locations, monthly_ai_generations, review_generations, review_replies, max_staff, features, limits, sort_order, is_active) "
            "VALUES (:c, :n, :p, 'INR', 'monthly', :l, :t, :g, :r, :s, CAST(:f AS jsonb), CAST(:lim AS jsonb), :o, true) "
            "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, price_paise = EXCLUDED.price_paise, max_locations = EXCLUDED.max_locations, monthly_ai_generations = EXCLUDED.monthly_ai_generations, "
            "review_generations = EXCLUDED.review_generations, review_replies = EXCLUDED.review_replies, max_staff = EXCLUDED.max_staff, features = EXCLUDED.features, limits = EXCLUDED.limits, "
            "sort_order = EXCLUDED.sort_order, is_active = true"
        ).bindparams(c=code, n=name, p=price, l=locs, t=gens + reps, g=gens, r=reps, s=staff, f=json.dumps(feats), lim=json.dumps(LIMITS), o=sort))
    # ---- retired plans: kept, hidden, with allowances that do not exceed what they promised
    op.execute("UPDATE billing_plans SET is_active = false, sort_order = 90 + sort_order, review_generations = monthly_ai_generations / 2, review_replies = monthly_ai_generations / 2 WHERE code IN ('essential', 'multi')")

    # ---- existing subscriptions: grandfather the limits, refresh the features and the new fields
    op.execute("UPDATE subscriptions SET review_generations = monthly_ai_generations / 2, review_replies = monthly_ai_generations / 2")
    op.execute(
        "UPDATE subscriptions s SET features = p.features, limits = p.limits "
        "FROM billing_plans p WHERE p.code = CASE s.plan WHEN 'trial' THEN 'growth' WHEN 'essential' THEN 'starter' WHEN 'multi' THEN 'pro' ELSE s.plan END"
    )

    # ---- subscription history (append-only)
    op.create_table(
        "subscription_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(24)), sa.Column("to_status", sa.String(24)),
        sa.Column("from_plan", sa.String(32)), sa.Column("to_plan", sa.String(32)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("ref", sa.String(120)),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_events_tenant", "subscription_events", ["tenant_id", "created_at"])
    # ---- promotional access
    op.create_table(
        "promotional_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False, server_default="card_purchase"),
        sa.Column("plan", sa.String(32), nullable=False, server_default="growth"),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("card_order_id", sa.UUID(), sa.ForeignKey("card_orders.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_order_id", name="uq_promo_grant_card_order"),
        sa.CheckConstraint("status in ('active','ended','revoked')", name="ck_promo_grant_status"),
    )
    op.create_index("ix_promo_grants_tenant", "promotional_grants", ["tenant_id", "status"])
    for t in ("subscription_events", "promotional_grants"):
        _rls(t)
    _grant("subscription_events", "SELECT, INSERT")  # append-only for the app: no UPDATE, no DELETE
    _grant("promotional_grants", "SELECT, INSERT, UPDATE")


def downgrade() -> None:
    op.drop_table("promotional_grants")
    op.drop_table("subscription_events")
    op.drop_column("card_orders", "offer_code")
    for t in ("subscriptions", "billing_plans"):
        op.drop_column(t, "limits")
        op.drop_column(t, "review_replies")
        op.drop_column(t, "review_generations")
    op.execute("DELETE FROM billing_plans WHERE code IN ('starter', 'pro')")
    op.execute("UPDATE billing_plans SET is_active = true, sort_order = sort_order - 90 WHERE code IN ('essential', 'multi')")
