"""As-built serial records and the components consumed to build them."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftVoidMixin, TimestampMixin


class AsBuiltSerialRecord(TimestampMixin, SoftVoidMixin, Base):
    """One physical unit that was built, identified by a serial number.

    Its ``components`` capture exactly what went into this unit at each
    position; walking them is the forward trace (serial -> full build history).
    """

    __tablename__ = "as_built_serial_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id"), nullable=False)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_order.id"), nullable=False
    )
    built_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    part: Mapped["Part"] = relationship()
    work_order: Mapped["WorkOrder"] = relationship(back_populates="serials")

    # What this unit consumed at each component position.
    components: Mapped[List["AsBuiltComponent"]] = relationship(
        back_populates="serial",
        foreign_keys="AsBuiltComponent.serial_id",
    )
    # The parent lines in which this unit was itself consumed as a sub-assembly.
    consumed_in: Mapped[List["AsBuiltComponent"]] = relationship(
        back_populates="consumed_serial",
        foreign_keys="AsBuiltComponent.consumed_serial_id",
    )


class AsBuiltComponent(TimestampMixin, SoftVoidMixin, Base):
    """What was actually consumed at one component position of a built unit.

    Each row ties a parent serial's position to *either* a supplier lot (a
    purchased component) *or* a child serial (a serialized sub-assembly), never
    both, never neither. This dual link is what makes the trace work in both
    directions and to any BOM depth.
    """

    __tablename__ = "as_built_component"
    __table_args__ = (
        CheckConstraint(
            "(consumed_supplier_lot_id IS NOT NULL) <> (consumed_serial_id IS NOT NULL)",
            name="ck_as_built_component_exactly_one_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_id: Mapped[int] = mapped_column(
        ForeignKey("as_built_serial_record.id"), nullable=False
    )
    # Which BOM position this consumption satisfies (optional, but ties the
    # as-built structure back to the engineering BOM).
    bom_line_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bom_line.id"), nullable=True
    )
    consumed_supplier_lot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("supplier_lot.id"), nullable=True
    )
    consumed_serial_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("as_built_serial_record.id"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    serial: Mapped["AsBuiltSerialRecord"] = relationship(
        back_populates="components", foreign_keys=[serial_id]
    )
    consumed_serial: Mapped[Optional["AsBuiltSerialRecord"]] = relationship(
        back_populates="consumed_in", foreign_keys=[consumed_serial_id]
    )
    consumed_supplier_lot: Mapped[Optional["SupplierLot"]] = relationship()
    bom_line: Mapped[Optional["BomLine"]] = relationship()
