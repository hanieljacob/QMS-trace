"""FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from app.database import SessionLocal


def get_db() -> Iterator[Session]:
    """Yield a request-scoped database session, always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
