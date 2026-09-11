"""SQLAlchemy engine and session management.

Phase 0 only proves connectivity; tables (workbook_versions, runs, ...) arrive with the phases that need them.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    url = get_settings().resolved_database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    with get_session_factory()() as session:
        yield session


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """Development-grade migration: add columns that exist in the models but not in an older
    SQLite file. Postgres deployments get Alembic; this keeps local databases usable across phases."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table.name}")'))}
            if not existing:
                continue
            for column in table.columns:
                if column.name in existing:
                    continue
                ctype = column.type.compile(dialect=engine.dialect)
                default = ""
                if column.default is not None and column.default.is_scalar:
                    value = column.default.arg
                    default = f" DEFAULT {int(value) if isinstance(value, bool) else value!r}"
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ctype}{default}')
                )


def check_database() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check must never raise
        return False
