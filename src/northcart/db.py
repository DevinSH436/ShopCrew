"""SQLAlchemy engine and session handling."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from northcart.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every store table."""


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def configure(url: str | None = None) -> Engine:
    """(Re)create the engine. Tests call this with a temporary database URL."""
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(_engine, "connect", _sqlite_pragmas)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    """Return the configured engine, creating it on first use."""
    return _engine or configure()


def SessionLocal() -> Session:  # noqa: N802 - reads like the usual factory name
    """Open a new session."""
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    return _SessionLocal()


def create_all() -> None:
    """Create every table that does not exist yet."""
    from northcart import models  # noqa: F401 - registers the tables

    Base.metadata.create_all(engine())


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
