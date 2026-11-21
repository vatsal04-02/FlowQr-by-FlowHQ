"""Google content retention: when content was last re-fetched from Google, and when it was expired (docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md).

Revision ID: 0064
Revises: 0063

Additive and nullable. Nothing is deleted by this migration, and the retention job that uses these columns is OFF until GOOGLE_CONTENT_RETENTION_ENABLED=true.

* reviews.google_fetched_at          the last time Google returned this review. Existing rows are set to the migration time ("treated as fetched now"), so enabling retention later never expires a
                                     review merely because this column did not exist; the sync then keeps it current.
* reviews.google_content_expired_at  set when the text, reviewer name and Google's copy of the reply were cleared by the retention job (rating, dates and ids stay).
* gbp_metric_daily               the application role gets DELETE (0035 deliberately gave it none: rows left only with their business). The retention job needs it to remove old daily metrics. Nothing deletes
                                     anything until GOOGLE_CONTENT_RETENTION_ENABLED=true.
* google_locations.last_full_synced_at  the last sync that read the location's whole review list (not only the recent part), which is what refreshes every review's fetch time.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("google_fetched_at", sa.DateTime(timezone=True)))
    op.add_column("reviews", sa.Column("google_content_expired_at", sa.DateTime(timezone=True)))
    op.add_column("google_locations", sa.Column("last_full_synced_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE reviews SET google_fetched_at = now() WHERE google_fetched_at IS NULL")
    op.create_index("ix_reviews_google_fetched", "reviews", ["google_fetched_at"])
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT DELETE ON gbp_metric_daily TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE DELETE ON gbp_metric_daily FROM {APP_ROLE}';
          END IF;
        END $$;
    """)
    op.drop_index("ix_reviews_google_fetched", table_name="reviews")
    op.drop_column("google_locations", "last_full_synced_at")
    op.drop_column("reviews", "google_content_expired_at")
    op.drop_column("reviews", "google_fetched_at")
