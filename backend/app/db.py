"""SQLAlchemy engine/session. SQLite in dev, Postgres in prod (NUDGY_DATABASE_URL).
Holds accounts, usage, and shared walkthroughs — never screenshots of a user's screen
unless an author explicitly chose to include them in a shared walkthrough."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


@lru_cache
def _sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_db() -> None:
    from app import models  # noqa: F401 — register tables

    engine = get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """create_all never alters existing tables; add new columns that have a server default
    (e.g. usage cost fields) so older databases keep working without a migration tool."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or col.server_default is None:
                    continue
                ddl = col.type.compile(engine.dialect)
                default = col.server_default.arg
                conn.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl} DEFAULT {default}")
                )


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with _sessionmaker()() as session:
        yield session
