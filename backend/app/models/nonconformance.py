"""Nonconformances raised against a supplier lot or a single serial."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftVoidMixin, TimestampMixin
from app.models.enums import NonconformanceStatus


class Nonconformance(TimestampMixin, SoftVoidMixin, Base):
    """A recorded deviation from specification.

    A nonconformance attaches to *either* a supplier lot *or* a single as-built
    serial — exactly one of the two — so it always has a clear subject in the
    trace.
    """

    __tablename__ = "nonconformance"
    __table_args__ = (
        CheckConstraint(
            "(supplier_lot_id IS NOT NULL) <> (serial_id IS NOT NULL)",
            name="ck_nonconformance_exactly_one_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nc_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    supplier_lot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("supplier_lot.id"), nullable=True
    )
    serial_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("as_built_serial_record.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NonconformanceStatus] = mapped_column(
        SAEnum(NonconformanceStatus, name="nonconformance_status", native_enum=False),
        nullable=False,
    )

    supplier_lot: Mapped[Optional["SupplierLot"]] = relationship()
    serial: Mapped[Optional["AsBuiltSerialRecord"]] = relationship()
