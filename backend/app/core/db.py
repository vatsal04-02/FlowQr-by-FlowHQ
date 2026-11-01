"""Database engine/session plus the Row-Level-Security context plumbing.

RLS design (defence in depth, on top of explicit tenant checks in every endpoint):
  * Tenant-scoped tables have FORCE ROW LEVEL SECURITY with a policy comparing
    tenant_id to the transaction-local setting `app.tenant_id`, OR `app.bypass_rls = 'on'`.
  * The app connects as a non-superuser role, so the policies are really enforced.
  * With no context set, tenant-scoped tables return NO rows (default deny).
  * `Session.info` carries the context; an `after_begin` hook applies it on every new
    transaction so it survives commits.
"""
from collections.abc import Generator
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _apply_rls_context(session: Session, connection) -> None:
    tenant_id = session.info.get("rls_tenant_id")
    bypass = session.info.get("rls_bypass", False)
    connection.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.bypass_rls', :b, true)"),
        {"t": str(tenant_id) if tenant_id else "", "b": "on" if bypass else "off"},
    )


@event.listens_for(SessionLocal, "after_begin")
def _after_begin(session: Session, transaction, connection) -> None:  # pragma: no cover - trivial
    _apply_rls_context(session, connection)


def set_rls_context(db: Session, *, tenant_id: UUID | None = None, bypass: bool = False) -> None:
    """Set RLS context for the session (current + future transactions)."""
    db.info["rls_tenant_id"] = tenant_id
    db.info["rls_bypass"] = bypass
    if db.in_transaction():
        _apply_rls_context(db, db.connection())


def get_db() -> Generator[Session, None, None]:
    """Plain session with default-deny RLS context. Auth dependencies elevate it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def system_session() -> Session:
    """Session for background workers / bootstrap: bypasses RLS. Caller must close it."""
    db = SessionLocal()
    set_rls_context(db, bypass=True)
    return db
