"""Append-only audit trail.

Every write in the system (create, update, or void) is recorded here. This
table is deliberately the one place with no ``SoftVoidMixin`` — audit events are
immutable and are never voided or deleted.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Enum as SAEnum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin
from app.models.enums import AuditAction


class AuditEvent(TimestampMixin, Base):
    """A single recorded write against some other record.

    ``created_at`` / ``created_by`` (from the mixin) answer *when* and *by whom*;
    the columns below answer *what changed and to which row*.
    """

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(80), nullable=False)
    record_id: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action", native_enum=False), nullable=False
    )
    # Snapshot of the changed fields (before/after), stored as JSON.
    changes: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
