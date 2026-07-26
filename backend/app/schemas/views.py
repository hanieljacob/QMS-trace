"""Pydantic response models shaped for the frontend views.

These intentionally do **not** mirror the database tables. They present the
domain the way the traceability screens consume it — a build tree, a recall
scope, a nonconformance list, a signature receipt, an audit trail — and are
built from the plain results returned by the service layer.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.services import genealogy as g


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #

class NonconformanceView(BaseModel):
    """A nonconformance as surfaced inside another view."""

    nc_number: str
    status: str
    description: str


# --------------------------------------------------------------------------- #
# Serial search
# --------------------------------------------------------------------------- #

class SerialSummary(BaseModel):
    """One row in the serial search results."""

    serial_number: str
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    work_order_number: Optional[str] = None
    built_at: Optional[datetime.datetime] = None

    @classmethod
    def from_record(cls, rec) -> "SerialSummary":
        return cls(
            serial_number=rec.serial_number,
            part_number=rec.part.part_number if rec.part else None,
            part_name=rec.part.name if rec.part else None,
            work_order_number=rec.work_order.work_order_number if rec.work_order else None,
            built_at=rec.built_at,
        )


# --------------------------------------------------------------------------- #
# As-built tree (device history)
# --------------------------------------------------------------------------- #

class ConsumedLot(BaseModel):
    """The supplier lot consumed at a component position, with its quality context."""

    lot_number: Optional[str] = None
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    supplier_name: Optional[str] = None
    received_at: Optional[datetime.date] = None
    certificate_status: str = Field(description="'present' or 'absent'")
    inspection_disposition: Optional[str] = Field(
        default=None, description="Incoming inspection outcome, e.g. 'accepted' or 'rejected'."
    )
    inspection_notes: Optional[str] = None
    nonconformances: list[NonconformanceView] = []


class BuildComponent(BaseModel):
    """One component position of a built unit and what filled it."""

    position: Optional[str] = None
    quantity: Optional[Decimal] = None
    kind: Literal["lot", "serial", "orphan"]
    lot: Optional[ConsumedLot] = None
    child: Optional["SerialTree"] = None
    note: Optional[str] = Field(
        default=None, description="Set when the reference is dangling or malformed."
    )


class SerialTree(BaseModel):
    """A built unit and, recursively, its full as-built genealogy."""

    serial_number: Optional[str] = None
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    work_order_number: Optional[str] = None
    built_at: Optional[datetime.datetime] = None
    is_cycle: bool = Field(
        default=False, description="True when this unit repeats an ancestor (a data cycle); not expanded further."
    )
    nonconformances: list[NonconformanceView] = []
    components: list[BuildComponent] = []


def _nc(nc: "g.NCView") -> NonconformanceView:
    return NonconformanceView(nc_number=nc.nc_number, status=nc.status, description=nc.description)


def _lot(lot: "g.LotView") -> ConsumedLot:
    return ConsumedLot(
        lot_number=lot.lot_number,
        part_number=lot.part_number,
        part_name=lot.part_name,
        supplier_name=lot.supplier_name,
        received_at=lot.received_at,
        certificate_status=lot.certificate_status,
        inspection_disposition=lot.inspection_disposition,
        inspection_notes=lot.inspection_notes,
        nonconformances=[_nc(n) for n in lot.nonconformances],
    )


def _component(comp: "g.ComponentNode") -> BuildComponent:
    return BuildComponent(
        position=comp.position,
        quantity=comp.quantity,
        kind=comp.kind,
        lot=_lot(comp.lot) if comp.lot else None,
        child=serial_tree(comp.child) if comp.child else None,
        note=comp.note,
    )


def serial_tree(node: "g.SerialNode") -> SerialTree:
    """Convert a genealogy ``SerialNode`` into the API ``SerialTree``."""
    return SerialTree(
        serial_number=node.serial_number,
        part_number=node.part_number,
        part_name=node.part_name,
        work_order_number=node.work_order_number,
        built_at=node.built_at,
        is_cycle=node.is_cycle,
        nonconformances=[_nc(n) for n in node.nonconformances],
        components=[_component(c) for c in node.components],
    )


BuildComponent.model_rebuild()


# --------------------------------------------------------------------------- #
# Recall scope (lot -> affected serials)
# --------------------------------------------------------------------------- #

class AffectedSerial(BaseModel):
    """One serial pulled into a lot's recall scope."""

    serial_number: Optional[str] = None
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    work_order_number: Optional[str] = None
    built_at: Optional[datetime.datetime] = None
    depth: int = Field(description="0 = consumed the lot directly; higher = via that many sub-assembly levels.")
    direct: bool


class RecallScope(BaseModel):
    """Everything a supplier lot reached — the blast radius for a recall."""

    lot_number: Optional[str] = None
    supplier_name: Optional[str] = None
    total_affected: int = Field(description="Distinct serials that consumed the lot at any depth.")
    direct_consumers: int = Field(description="Serials that consumed the lot directly.")
    max_depth: int
    finished_devices: list[str] = Field(
        description="Serial numbers of affected finished devices — the units that shipped or would ship."
    )
    affected_serials: list[AffectedSerial] = []

    @classmethod
    def from_usage(cls, usage: "g.LotUsage") -> "RecallScope":
        consumers = usage.consumers
        return cls(
            lot_number=usage.lot_number,
            supplier_name=usage.supplier_name,
            total_affected=len(consumers),
            direct_consumers=sum(1 for c in consumers if c.direct),
            max_depth=max((c.depth for c in consumers), default=0),
            finished_devices=sorted(
                c.serial_number for c in consumers
                if c.part_type == "finished_device" and c.serial_number
            ),
            affected_serials=[
                AffectedSerial(
                    serial_number=c.serial_number,
                    part_number=c.part_number,
                    part_name=c.part_name,
                    work_order_number=c.work_order_number,
                    built_at=c.built_at,
                    depth=c.depth,
                    direct=c.direct,
                )
                for c in consumers
            ],
        )


# --------------------------------------------------------------------------- #
# Lot search
# --------------------------------------------------------------------------- #

class LotSummary(BaseModel):
    """One row in the supplier-lot search results, with quality flags."""

    lot_number: str
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    supplier_name: Optional[str] = None
    received_at: Optional[datetime.date] = None
    inspection_disposition: Optional[str] = None
    certificate_status: str
    open_nc_count: int = 0

    @classmethod
    def from_hit(cls, hit) -> "LotSummary":
        return cls(
            lot_number=hit.lot_number,
            part_number=hit.part_number,
            part_name=hit.part_name,
            supplier_name=hit.supplier_name,
            received_at=hit.received_at,
            inspection_disposition=hit.inspection_disposition,
            certificate_status=hit.certificate_status,
            open_nc_count=hit.open_nc_count,
        )


# --------------------------------------------------------------------------- #
# Lot report (the lot view)
# --------------------------------------------------------------------------- #

class InspectionResultView(BaseModel):
    inspected_at: Optional[datetime.datetime] = None
    disposition: Optional[str] = None
    notes: Optional[str] = None


class AffectedUnit(BaseModel):
    """One consuming unit within a work-order group."""

    serial_number: Optional[str] = None
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    built_at: Optional[datetime.datetime] = None
    depth: int
    direct: bool
    status: str = Field(description="Current unit status: 'released', 'nc_open', or 'voided'.")
    is_finished_device: bool


class WorkOrderGroupView(BaseModel):
    work_order_number: str
    unit_count: int
    units: list[AffectedUnit] = []


class LotReport(BaseModel):
    """Everything the lot view needs, in one response."""

    lot_number: Optional[str] = None
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    supplier_name: Optional[str] = None
    received_at: Optional[datetime.date] = None
    quantity_received: Optional[Decimal] = None

    # Quality context shown alongside the affected units.
    certificate_status: str = Field(description="'present' or 'absent'")
    certificate_references: list[str] = []
    inspections: list[InspectionResultView] = []
    nonconformances: list[NonconformanceView] = []

    # Blast radius — the headline number.
    blast_radius: int = Field(description="Total distinct units that consumed this lot at any depth.")
    direct_consumers: int
    finished_device_count: int
    finished_devices: list[str] = []

    work_order_groups: list[WorkOrderGroupView] = []

    @classmethod
    def from_report(cls, r) -> "LotReport":
        return cls(
            lot_number=r.lot_number,
            part_number=r.part_number,
            part_name=r.part_name,
            supplier_name=r.supplier_name,
            received_at=r.received_at,
            quantity_received=r.quantity_received,
            certificate_status=r.certificate_status,
            certificate_references=r.certificate_references,
            inspections=[
                InspectionResultView(inspected_at=i.inspected_at, disposition=i.disposition, notes=i.notes)
                for i in r.inspections
            ],
            nonconformances=[
                NonconformanceView(nc_number=nc.nc_number, status=nc.status, description=nc.description)
                for nc in r.nonconformances
            ],
            blast_radius=r.blast_radius,
            direct_consumers=r.direct_consumers,
            finished_device_count=r.finished_device_count,
            finished_devices=r.finished_devices,
            work_order_groups=[
                WorkOrderGroupView(
                    work_order_number=g.work_order_number,
                    unit_count=g.unit_count,
                    units=[
                        AffectedUnit(
                            serial_number=u.serial_number,
                            part_number=u.part_number,
                            part_name=u.part_name,
                            built_at=u.built_at,
                            depth=u.depth,
                            direct=u.direct,
                            status=u.status,
                            is_finished_device=u.is_finished_device,
                        )
                        for u in g.units
                    ],
                )
                for g in r.work_order_groups
            ],
        )


# --------------------------------------------------------------------------- #
# Nonconformance list
# --------------------------------------------------------------------------- #

class NonconformanceListItem(BaseModel):
    """A nonconformance with its subject resolved for the list view."""

    nc_number: str
    status: str
    description: str
    subject_type: Literal["supplier_lot", "serial", "none"]
    subject_reference: Optional[str] = Field(
        default=None, description="The lot number or serial number the NC is raised against."
    )
    supplier_name: Optional[str] = None
    created_at: Optional[datetime.datetime] = None

    @classmethod
    def from_nc(cls, nc) -> "NonconformanceListItem":
        if nc.supplier_lot_id is not None and nc.supplier_lot is not None:
            subject_type, reference = "supplier_lot", nc.supplier_lot.lot_number
            supplier = nc.supplier_lot.supplier_name
        elif nc.serial_id is not None and nc.serial is not None:
            subject_type, reference, supplier = "serial", nc.serial.serial_number, None
        else:
            subject_type, reference, supplier = "none", None, None
        return cls(
            nc_number=nc.nc_number,
            status=nc.status.value if nc.status else "",
            description=nc.description,
            subject_type=subject_type,
            subject_reference=reference,
            supplier_name=supplier,
            created_at=nc.created_at,
        )


# --------------------------------------------------------------------------- #
# Inspection sign-off
# --------------------------------------------------------------------------- #

class SignoffRequest(BaseModel):
    """The electronic-signature manifestation supplied at inspection sign-off."""

    signer_name: str = Field(description="Name of the person signing.")
    meaning: str = Field(
        description="The meaning of the signature, e.g. 'Performed and approved incoming inspection'."
    )


class SignatureReceipt(BaseModel):
    """Confirmation of a recorded electronic signature."""

    inspection_id: int
    signer_name: str
    meaning: str
    signed_at: datetime.datetime
    record_hash: str = Field(description="SHA-256 over the signed inspection's content at signing time.")
    verified: Optional[bool] = Field(
        description="True if the stored hash still matches the record (i.e. untampered)."
    )


# --------------------------------------------------------------------------- #
# Audit trail
# --------------------------------------------------------------------------- #

class AuditEntry(BaseModel):
    """One field-level change from the append-only audit trail."""

    action: str
    field: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = Field(default=None, description="Reason for change; required on updates.")
    actor: str = Field(description="Who made the change.")
    timestamp: datetime.datetime

    @classmethod
    def from_event(cls, event) -> "AuditEntry":
        return cls(
            action=event.action.value if event.action else "",
            field=event.field_name,
            old_value=event.old_value,
            new_value=event.new_value,
            reason=event.reason,
            actor=event.created_by,
            timestamp=event.created_at,
        )
