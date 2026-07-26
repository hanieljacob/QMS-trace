"""Read queries backing the list/search API views.

Thin, reusable query functions so the route handlers stay handler-shaped. The
genealogy and signature traversals live in their own modules; these cover the
plain list/lookup reads.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

import app.models as m


def search_serials(
    session: Session, query: Optional[str] = None, limit: int = 50
) -> list["m.AsBuiltSerialRecord"]:
    """Find as-built serial records by serial number, part, or work order."""
    stmt = (
        select(m.AsBuiltSerialRecord)
        .options(
            selectinload(m.AsBuiltSerialRecord.part),
            selectinload(m.AsBuiltSerialRecord.work_order),
        )
        .order_by(m.AsBuiltSerialRecord.serial_number)
        .limit(limit)
    )
    if query:
        like = f"%{query}%"
        stmt = (
            stmt.join(m.Part, m.Part.id == m.AsBuiltSerialRecord.part_id)
            .join(m.WorkOrder, m.WorkOrder.id == m.AsBuiltSerialRecord.work_order_id)
            .where(
                or_(
                    m.AsBuiltSerialRecord.serial_number.ilike(like),
                    m.Part.part_number.ilike(like),
                    m.Part.name.ilike(like),
                    m.WorkOrder.work_order_number.ilike(like),
                )
            )
        )
    return list(session.scalars(stmt).unique())


def list_nonconformances(
    session: Session, status: Optional["m.NonconformanceStatus"] = None
) -> list["m.Nonconformance"]:
    """List nonconformances, newest number first, optionally filtered by status."""
    stmt = (
        select(m.Nonconformance)
        .options(
            selectinload(m.Nonconformance.supplier_lot),
            selectinload(m.Nonconformance.serial),
        )
        .order_by(m.Nonconformance.nc_number)
    )
    if status is not None:
        stmt = stmt.where(m.Nonconformance.status == status)
    return list(session.scalars(stmt))


def get_audit_trail(
    session: Session, table_name: str, record_id: int
) -> list["m.AuditEvent"]:
    """Return the full append-only audit trail for one record, oldest first."""
    stmt = (
        select(m.AuditEvent)
        .where(m.AuditEvent.table_name == table_name)
        .where(m.AuditEvent.record_id == record_id)
        .order_by(m.AuditEvent.id)
    )
    return list(session.scalars(stmt))
