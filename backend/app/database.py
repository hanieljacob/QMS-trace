"""Database engine, session factory, and declarative base for qmstrace.

SQLite is the only backend for this demo. Foreign key enforcement is off by
default in SQLite, so we turn it on for every connection, the whole point of
this system is that the trace links are real.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Configurable so the same code runs locally (a file in the working directory)
# and on Lambda (a writable copy under /tmp). Defaults to the local file.
DATABASE_URL = os.environ.get("QMSTRACE_DATABASE_URL", "sqlite:///./qmstrace.db")

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by every qmstrace ORM model."""


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Install the append-only audit + immutability enforcement on every Session.
# Imported here, at the bottom, so that simply using the database wires in the
# guarantees, no application code has to remember to enable them.
from app.services import audit as _audit  # noqa: E402

_audit.register()
