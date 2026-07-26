"""Work orders that authorize and record a build."""

from __future__ import annotations

from decimal import Decimal
from typing import List

from sqlalchemy import Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftVoidMixin, TimestampMixin
from app.models.enums import WorkOrderStatus


class WorkOrder(TimestampMixin, SoftVoidMixin, Base):
    """Authorization and record for building a quantity of a part.

    A work order produces one or more as-built serial records.
    """

    __tablename__ = "work_order"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_number: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id"), nullable=False)
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    status: Mapped[WorkOrderStatus] = mapped_column(
        SAEnum(WorkOrderStatus, name="work_order_status", native_enum=False),
        nullable=False,
    )

    part: Mapped["Part"] = relationship()
    serials: Mapped[List["AsBuiltSerialRecord"]] = relationship(
        back_populates="work_order"
    )
