"""Part and bill-of-materials structure."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import SoftVoidMixin, TimestampMixin
from app.models.enums import PartType


class Part(TimestampMixin, SoftVoidMixin, Base):
    """A distinct item that can be stocked, purchased, or built.

    A single part table holds raw materials, components, and finished devices;
    which one a row is is given by ``part_type``.
    """

    __tablename__ = "part"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    part_type: Mapped[PartType] = mapped_column(
        SAEnum(PartType, name="part_type", native_enum=False), nullable=False
    )
    unit_of_measure: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # BOM lines where this part is the parent (its own recipe).
    bom_lines: Mapped[List["BomLine"]] = relationship(
        back_populates="parent_part",
        foreign_keys="BomLine.parent_part_id",
    )
    # BOM lines where this part appears as a component of something else.
    used_in_bom_lines: Mapped[List["BomLine"]] = relationship(
        back_populates="child_part",
        foreign_keys="BomLine.child_part_id",
    )


class BomLine(TimestampMixin, SoftVoidMixin, Base):
    """One component position in a parent part's bill of materials.

    Nesting is achieved by recursion: a part that is the ``child`` on one line
    can be the ``parent`` on its own lines, so a BOM can be three or four (or
    more) levels deep without any special columns.
    """

    __tablename__ = "bom_line"
    __table_args__ = (
        # A given position label is unique within its parent's BOM.
        UniqueConstraint("parent_part_id", "position", name="uq_bom_line_parent_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_part_id: Mapped[int] = mapped_column(ForeignKey("part.id"), nullable=False)
    child_part_id: Mapped[int] = mapped_column(ForeignKey("part.id"), nullable=False)
    # Position / reference designator within the parent (e.g. "R1", "HOUSING").
    position: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    parent_part: Mapped["Part"] = relationship(
        back_populates="bom_lines", foreign_keys=[parent_part_id]
    )
    child_part: Mapped["Part"] = relationship(
        back_populates="used_in_bom_lines", foreign_keys=[child_part_id]
    )
