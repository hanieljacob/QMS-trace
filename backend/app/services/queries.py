"""Read queries backing the list/search API views.

Thin, reusable query functions so the route handlers stay handler-shaped. The
genealogy and signature traversals live in their own modules; these cover the
plain list/lookup reads.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

import app.models as m
from app.services.genealogy import lot_where_used


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


# --------------------------------------------------------------------------- #
# Lot search
# --------------------------------------------------------------------------- #

@dataclass
class LotSearchHit:
    lot_number: str
    part_number: Optional[str]
    part_name: Optional[str]
    supplier_name: Optional[str]
    received_at: Optional[datetime.date]
    inspection_disposition: Optional[str]
    certificate_status: str
    open_nc_count: int


def search_lots(
    session: Session, query: Optional[str] = None, limit: int = 50
) -> list[LotSearchHit]:
    """Find supplier lots by lot number, supplier, or part, with quality flags.

    Quality context (latest inspection, CoC presence, open-NC count) is gathered
    in a fixed number of grouped queries, never one per lot.
    """
    stmt = (
        select(m.SupplierLot)
        .options(selectinload(m.SupplierLot.part))
        .order_by(m.SupplierLot.lot_number)
        .limit(limit)
    )
    if query:
        like = f"%{query}%"
        stmt = stmt.join(m.Part, m.Part.id == m.SupplierLot.part_id).where(
            or_(
                m.SupplierLot.lot_number.ilike(like),
                m.SupplierLot.supplier_name.ilike(like),
                m.Part.part_number.ilike(like),
                m.Part.name.ilike(like),
            )
        )
    lots = list(session.scalars(stmt).unique())
    ids = [lot.id for lot in lots]
    if not ids:
        return []

    # Latest inspection disposition per lot (ascending order → last write wins).
    disposition: dict[int, str] = {}
    for lot_id, disp in session.execute(
        select(m.IncomingInspection.supplier_lot_id, m.IncomingInspection.disposition)
        .where(m.IncomingInspection.supplier_lot_id.in_(ids))
        .order_by(m.IncomingInspection.inspected_at)
    ):
        disposition[lot_id] = disp.value if disp else None

    with_coc = set(
        session.scalars(
            select(m.CertificateOfConformance.supplier_lot_id)
            .where(m.CertificateOfConformance.supplier_lot_id.in_(ids))
        )
    )

    open_nc: dict[int, int] = {}
    for lot_id in session.scalars(
        select(m.Nonconformance.supplier_lot_id).where(
            m.Nonconformance.supplier_lot_id.in_(ids),
            m.Nonconformance.status == m.NonconformanceStatus.open,
        )
    ):
        open_nc[lot_id] = open_nc.get(lot_id, 0) + 1

    return [
        LotSearchHit(
            lot_number=lot.lot_number,
            part_number=lot.part.part_number if lot.part else None,
            part_name=lot.part.name if lot.part else None,
            supplier_name=lot.supplier_name,
            received_at=lot.received_at,
            inspection_disposition=disposition.get(lot.id),
            certificate_status="present" if lot.id in with_coc else "absent",
            open_nc_count=open_nc.get(lot.id, 0),
        )
        for lot in lots
    ]


# --------------------------------------------------------------------------- #
# Lot report (the lot view, one call, everything the screen needs)
# --------------------------------------------------------------------------- #

@dataclass
class InspectionResult:
    inspected_at: Optional[datetime.datetime]
    disposition: Optional[str]
    notes: Optional[str]


@dataclass
class NCLine:
    nc_number: str
    status: str
    description: str


@dataclass
class UnitLine:
    serial_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    built_at: Optional[datetime.datetime]
    depth: int
    direct: bool
    status: str  # "released" | "nc_open" | "voided"
    is_finished_device: bool


@dataclass
class WorkOrderGroup:
    work_order_number: str
    unit_count: int
    units: list[UnitLine]


@dataclass
class LotReport:
    lot_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    supplier_name: Optional[str]
    received_at: Optional[datetime.date]
    quantity_received: Optional[Decimal]
    certificate_status: str
    certificate_references: list[str]
    inspections: list[InspectionResult]
    nonconformances: list[NCLine]
    blast_radius: int
    direct_consumers: int
    finished_device_count: int
    finished_devices: list[str]
    work_order_groups: list[WorkOrderGroup] = field(default_factory=list)


def lot_report(session: Session, lot_number: str) -> LotReport:
    """Assemble the full lot view in one shot: quality context + blast radius +
    every consuming unit grouped by work order.

    Raises ``LookupError`` if the lot does not exist.
    """
    usage = lot_where_used(session, lot_number)  # validates existence; batched traversal
    lot = session.get(m.SupplierLot, usage.lot_id)
    part = session.get(m.Part, lot.part_id)

    inspections = [
        InspectionResult(
            inspected_at=ins.inspected_at,
            disposition=ins.disposition.value if ins.disposition else None,
            notes=ins.result_notes,
        )
        for ins in session.scalars(
            select(m.IncomingInspection)
            .where(m.IncomingInspection.supplier_lot_id == lot.id)
            .order_by(m.IncomingInspection.inspected_at.desc())
        )
    ]
    certificate_references = list(
        session.scalars(
            select(m.CertificateOfConformance.document_reference)
            .where(m.CertificateOfConformance.supplier_lot_id == lot.id)
        )
    )
    nonconformances = [
        NCLine(nc_number=nc.nc_number, status=nc.status.value if nc.status else "", description=nc.description)
        for nc in session.scalars(
            select(m.Nonconformance).where(m.Nonconformance.supplier_lot_id == lot.id)
        )
    ]

    # One query for which consuming serials carry an open nonconformance.
    consuming_ids = [c.serial_id for c in usage.consumers if not c.is_orphan]
    open_nc_serials: set[int] = set()
    if consuming_ids:
        open_nc_serials = set(
            session.scalars(
                select(m.Nonconformance.serial_id).where(
                    m.Nonconformance.serial_id.in_(consuming_ids),
                    m.Nonconformance.status == m.NonconformanceStatus.open,
                )
            )
        )

    groups: dict[str, list[UnitLine]] = {}
    for c in usage.consumers:
        if c.voided:
            status = "voided"
        elif c.serial_id in open_nc_serials:
            status = "nc_open"
        else:
            status = "released"
        line = UnitLine(
            serial_number=c.serial_number,
            part_number=c.part_number,
            part_name=c.part_name,
            built_at=c.built_at,
            depth=c.depth,
            direct=c.direct,
            status=status,
            is_finished_device=(c.part_type == "finished_device"),
        )
        groups.setdefault(c.work_order_number or "-", []).append(line)

    work_order_groups = [
        WorkOrderGroup(
            work_order_number=wo,
            unit_count=len(units),
            units=sorted(units, key=lambda u: (u.depth, u.serial_number or "")),
        )
        for wo, units in sorted(groups.items())
    ]
    finished = sorted(
        c.serial_number for c in usage.consumers
        if c.part_type == "finished_device" and c.serial_number
    )

    return LotReport(
        lot_number=lot.lot_number,
        part_number=part.part_number if part else None,
        part_name=part.name if part else None,
        supplier_name=lot.supplier_name,
        received_at=lot.received_at,
        quantity_received=lot.quantity_received,
        certificate_status="present" if certificate_references else "absent",
        certificate_references=certificate_references,
        inspections=inspections,
        nonconformances=nonconformances,
        blast_radius=len(usage.consumers),
        direct_consumers=sum(1 for c in usage.consumers if c.direct),
        finished_device_count=len(finished),
        finished_devices=finished,
        work_order_groups=work_order_groups,
    )


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
