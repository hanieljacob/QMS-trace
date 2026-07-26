"""Append-only audit trail.

Every insert and update anywhere in the app writes one audit event *per changed
field* — table, record id, field, old value, new value, actor, and timestamp,
plus a reason for change that is mandatory on updates. Rows are written
automatically at the session level (see ``app.services.audit``) so no code path
can forget to record a change.

This table is deliberately the one place with no ``SoftVoidMixin`` — audit
events are immutable and are never updated or deleted.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin
from app.models.enums import AuditAction


class AuditEvent(TimestampMixin, Base):
    """One recorded field-level change against some other record.

    ``created_at`` / ``created_by`` (from the mixin) are the *timestamp* and
    *actor*; the columns below are *what changed, where, and why*.
    """

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(80), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action", native_enum=False), nullable=False
    )
    field_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Mandatory on updates (enforced in app.services.audit); null on inserts.
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
