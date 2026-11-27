"""SQLAlchemy engine, session factory and base class."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver level
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
    if "claim_lines" in inspect(engine).get_table_names():
        existing_columns = {
            column["name"] for column in inspect(engine).get_columns("claim_lines")
        }
        boolean_default = "0" if engine.dialect.name == "sqlite" else "FALSE"
        with engine.begin() as connection:
            for name in ("quantity_known", "unit_rate_known"):
                if name not in existing_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE claim_lines ADD COLUMN {name} "
                            f"BOOLEAN NOT NULL DEFAULT {boolean_default}"
                        )
                    )
