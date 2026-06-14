from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return
    database_path = make_url(database_url).database
    if not database_path or database_path == ":memory:":
        return
    Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(settings.database_url)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db() -> None:
    from backend.app.models import tables  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "instruments" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("instruments")}
    with engine.begin() as connection:
        if "instrument_type" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE instruments "
                    "ADD COLUMN instrument_type VARCHAR(20) DEFAULT '' NOT NULL"
                )
            )
    columns_by_table = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in inspector.get_table_names()
    }
    level_set_columns = columns_by_table.get("daily_level_sets", set())
    with engine.begin() as connection:
        if "execution_status" not in level_set_columns:
            connection.execute(
                text(
                    "ALTER TABLE daily_level_sets "
                    "ADD COLUMN execution_status VARCHAR(20) DEFAULT 'PENDING'"
                )
            )
