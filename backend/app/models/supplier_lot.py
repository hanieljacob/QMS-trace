"""Supplier lots, their certificates, and incoming inspection results."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftVoidMixin, TimestampMixin
from app.models.enums import InspectionDisposition


class SupplierLot(TimestampMixin, SoftVoidMixin, Base):
    """A quantity of a purchased part received under one supplier lot number.

    This is the unit of incoming traceability and the anchor of the backward
    trace (lot -> every serial that consumed it).
    """

    __tablename__ = "supplier_lot"
    __table_args__ = (
        UniqueConstraint(
            "part_id", "supplier_name", "lot_number", name="uq_supplier_lot_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id"), nullable=False)
    lot_number: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    received_at: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    part: Mapped["Part"] = relationship()
    certificates: Mapped[List["CertificateOfConformance"]] = relationship(
        back_populates="supplier_lot"
    )
    inspections: Mapped[List["IncomingInspection"]] = relationship(
        back_populates="supplier_lot"
    )


class CertificateOfConformance(TimestampMixin, SoftVoidMixin, Base):
    """A supplier's attestation that a supplier lot meets its specification."""

    __tablename__ = "certificate_of_conformance"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_lot_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_lot.id"), nullable=False
    )
    document_reference: Mapped[str] = mapped_column(String(300), nullable=False)
    issued_at: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)

    supplier_lot: Mapped["SupplierLot"] = relationship(back_populates="certificates")


class IncomingInspection(TimestampMixin, SoftVoidMixin, Base):
    """The recorded inspection of a supplier lot on receipt, with a disposition."""

    __tablename__ = "incoming_inspection"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_lot_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_lot.id"), nullable=False
    )
    inspected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    disposition: Mapped[InspectionDisposition] = mapped_column(
        SAEnum(InspectionDisposition, name="inspection_disposition", native_enum=False),
        nullable=False,
    )
    result_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    supplier_lot: Mapped["SupplierLot"] = relationship(back_populates="inspections")
