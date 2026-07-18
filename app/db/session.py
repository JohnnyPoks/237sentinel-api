"""SQLAlchemy 2.x engine/session setup.

Uses DATABASE_URL (Postgres) in production; falls back to a local SQLite file
so the API boots on a fresh machine. On Hugging Face Spaces the filesystem is
ephemeral, so production MUST point DATABASE_URL at Postgres (Supabase/Neon).
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.effective_database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables for first run / SQLite fallback.

    Postgres deployments use Alembic migrations; this is a convenience so a
    fresh clone works immediately. Importing models registers them on Base.
    """
    from app import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=engine)
