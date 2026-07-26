"""Column mixins shared by every table.

Two rules from CLAUDE.md are enforced here so no individual model can forget
them:

* Every table records who created the row and when (``TimestampMixin``).
* Nothing is ever hard-deleted; removal is a state a row moves into
  (``SoftVoidMixin``). There is deliberately no delete path anywhere.
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """``created_at`` / ``created_by`` — mandatory on every table."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # No auth in this project (see CLAUDE.md); created_by is a free-text actor
    # label such as an operator name or "system".
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)


class SoftVoidMixin:
    """Soft-delete-as-state. A voided row is retained forever, never removed.

    A NULL ``voided_at`` means the record is active. Setting these fields is the
    only supported way to "delete" domain data.
    """

    voided_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
