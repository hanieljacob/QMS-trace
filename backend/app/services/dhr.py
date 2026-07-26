"""Assemble a Device History Record for one serial.

Pure data assembly (no rendering): reuse the genealogy traversal for the build
tree, then gather the incoming inspections + electronic signatures and the
nonconformances that pertain to everything consumed in the build. The PDF
renderer (app/reports/dhr_pdf.py) turns this into the auditor-facing document.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import app.models as m
from app.services.esignature import compute_inspection_hash
from app.services.genealogy import SerialNode, serial_genealogy


@dataclass
class SignatureLine:
    signer_name: str
    meaning: str
    signed_at: Optional[datetime.datetime]
    record_hash: str
    verified: bool


@dataclass
class InspectionEntry:
    lot_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    supplier_name: Optional[str]
    disposition: Optional[str]
    inspected_at: Optional[datetime.datetime]
    notes: Optional[str]
    signatures: list[SignatureLine] = field(default_factory=list)


@dataclass
class NCEntry:
    nc_number: str
    status: str
    subject: str
    description: str


@dataclass
class DHRDocument:
    serial_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    work_order_number: Optional[str]
    built_at: Optional[datetime.datetime]
    genealogy: SerialNode
    inspections: list[InspectionEntry]
    nonconformances: list[NCEntry]
    generated_at: datetime.datetime


def build_dhr(session: Session, serial_number: str) -> DHRDocument:
    """Assemble the full device history record for ``serial_number``.

    Raises ``LookupError`` if the serial does not exist.
    """
    tree = serial_genealogy(session, serial_number)  # bulk-loaded, ~14 queries

    # Collect the lots and serials that appear anywhere in the build.
    lot_ids: set[int] = set()
    serial_ids: set[int] = set()
    serial_number_by_id: dict[int, Optional[str]] = {}

    def walk(node: SerialNode) -> None:
        serial_ids.add(node.serial_id)
        serial_number_by_id[node.serial_id] = node.serial_number
        for comp in node.components:
            if comp.kind == "lot" and comp.lot:
                lot_ids.add(comp.lot.lot_id)
            elif comp.kind == "serial" and comp.child:
                walk(comp.child)

    walk(tree)

    inspections = _collect_inspections(session, lot_ids)
    nonconformances = _collect_nonconformances(
        session, lot_ids, serial_ids, serial_number_by_id
    )

    return DHRDocument(
        serial_number=tree.serial_number,
        part_number=tree.part_number,
        part_name=tree.part_name,
        work_order_number=tree.work_order_number,
        built_at=tree.built_at,
        genealogy=tree,
        inspections=inspections,
        nonconformances=nonconformances,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _collect_inspections(session: Session, lot_ids: set[int]) -> list[InspectionEntry]:
    if not lot_ids:
        return []
    lots = {
        lot.id: lot
        for lot in session.scalars(
            select(m.SupplierLot)
            .options(selectinload(m.SupplierLot.part))
            .where(m.SupplierLot.id.in_(lot_ids))
        )
    }
    inspection_rows = session.scalars(
        select(m.IncomingInspection).where(
            m.IncomingInspection.supplier_lot_id.in_(lot_ids)
        )
    ).all()

    signatures_by_inspection: dict[int, list[m.ElectronicSignature]] = {}
    inspection_ids = [ins.id for ins in inspection_rows]
    if inspection_ids:
        for sig in session.scalars(
            select(m.ElectronicSignature).where(
                m.ElectronicSignature.table_name == "incoming_inspection",
                m.ElectronicSignature.record_id.in_(inspection_ids),
            )
        ):
            signatures_by_inspection.setdefault(sig.record_id, []).append(sig)

    entries: list[InspectionEntry] = []
    for ins in inspection_rows:
        lot = lots.get(ins.supplier_lot_id)
        sig_lines = [
            SignatureLine(
                signer_name=sig.signer_name,
                meaning=sig.meaning,
                signed_at=sig.signed_at,
                record_hash=sig.record_hash,
                verified=(sig.record_hash == compute_inspection_hash(ins)),
            )
            for sig in signatures_by_inspection.get(ins.id, [])
        ]
        entries.append(InspectionEntry(
            lot_number=lot.lot_number if lot else None,
            part_number=lot.part.part_number if lot and lot.part else None,
            part_name=lot.part.name if lot and lot.part else None,
            supplier_name=lot.supplier_name if lot else None,
            disposition=ins.disposition.value if ins.disposition else None,
            inspected_at=ins.inspected_at,
            notes=ins.result_notes,
            signatures=sig_lines,
        ))
    entries.sort(key=lambda e: (e.lot_number or "", e.inspected_at or datetime.datetime.min))
    return entries


def _collect_nonconformances(
    session: Session,
    lot_ids: set[int],
    serial_ids: set[int],
    serial_number_by_id: dict[int, Optional[str]],
) -> list[NCEntry]:
    lots = (
        {lot.id: lot for lot in session.scalars(
            select(m.SupplierLot).where(m.SupplierLot.id.in_(lot_ids))
        )}
        if lot_ids else {}
    )
    where = m.Nonconformance.serial_id.in_(serial_ids)
    if lot_ids:
        where = m.Nonconformance.supplier_lot_id.in_(lot_ids) | where

    entries: list[NCEntry] = []
    for nc in session.scalars(select(m.Nonconformance).where(where)):
        if nc.supplier_lot_id is not None:
            lot = lots.get(nc.supplier_lot_id)
            subject = f"Lot {lot.lot_number}" if lot else f"Lot #{nc.supplier_lot_id}"
        elif nc.serial_id is not None:
            subject = f"Serial {serial_number_by_id.get(nc.serial_id) or nc.serial_id}"
        else:
            subject = "—"
        entries.append(NCEntry(
            nc_number=nc.nc_number,
            status=nc.status.value if nc.status else "",
            subject=subject,
            description=nc.description,
        ))
    entries.sort(key=lambda e: e.nc_number)
    return entries
