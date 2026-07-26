"""Genealogy traversals, the two queries qmstrace exists to answer.

Pure functions over a SQLAlchemy ``Session``; no web framework, no request or
response objects. Each returns plain dataclasses so callers (an API layer, a
CLI, a test) can shape the output however they like.

Two traversals, mapped to the CLAUDE.md vocabulary:

* :func:`serial_genealogy`, given a serial number, walk *down* the as-built
  tree to every component position, the lot consumed there, and that lot's
  supplier / certificate / inspection / nonconformance. This assembles the
  device history record (CLAUDE.md "forward trace").
* :func:`lot_where_used`, given a supplier lot, walk *up* to every serial that
  consumed it at any depth, with the work order and build date for each
  (CLAUDE.md "backward trace").

Both are defensive about two kinds of bad data:

* **Cycles**, an as-built graph should never contain one, but if a serial ends
  up (transitively) consuming itself, traversal stops instead of looping
  forever. Downward it is flagged as ``is_cycle``; upward the visited-set simply
  refuses to re-expand a node.
* **Orphan references**, a component pointing at a lot or serial row that is
  not there (or a missing part / work order / bom line) is reported as an
  ``orphan`` / ``None`` field rather than raising.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import app.models as m

__all__ = [
    "NCView",
    "LotView",
    "ComponentNode",
    "SerialNode",
    "LotConsumer",
    "LotUsage",
    "serial_genealogy",
    "lot_where_used",
]


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #

@dataclass
class NCView:
    """A nonconformance as seen from within a trace."""

    nc_number: str
    status: str
    description: str


@dataclass
class LotView:
    """A consumed supplier lot with its receiving-quality context."""

    lot_id: int
    lot_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    supplier_name: Optional[str]
    received_at: Optional[datetime.date]
    certificate_status: str  # "present" | "absent" | "unknown"
    certificate_count: int
    inspection_disposition: Optional[str]
    inspection_notes: Optional[str]
    nonconformances: list[NCView] = field(default_factory=list)
    is_orphan: bool = False


@dataclass
class ComponentNode:
    """One component position of a built unit and what filled it.

    ``kind`` is ``"lot"`` (``lot`` set), ``"serial"`` (``child`` set), or
    ``"orphan"`` (neither, a dangling or malformed reference, see ``note``).
    """

    kind: str
    position: Optional[str]
    quantity: Optional[Decimal]
    bom_line_id: Optional[int]
    lot: Optional[LotView] = None
    child: Optional["SerialNode"] = None
    note: Optional[str] = None


@dataclass
class SerialNode:
    """A built unit and, recursively, everything under it."""

    serial_id: int
    serial_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    work_order_number: Optional[str]
    built_at: Optional[datetime.datetime]
    components: list[ComponentNode] = field(default_factory=list)
    nonconformances: list[NCView] = field(default_factory=list)
    is_cycle: bool = False  # True => this node repeats an ancestor; not expanded


@dataclass
class LotConsumer:
    """One serial that consumed a lot, directly or via a sub-assembly."""

    serial_id: int
    serial_number: Optional[str]
    part_number: Optional[str]
    part_name: Optional[str]
    part_type: Optional[str]
    work_order_number: Optional[str]
    built_at: Optional[datetime.datetime]
    depth: int          # 0 = consumed the lot directly; n = via n levels of sub-assembly
    direct: bool
    voided: bool = False
    is_orphan: bool = False


@dataclass
class LotUsage:
    """Result of :func:`lot_where_used`."""

    lot_id: int
    lot_number: Optional[str]
    supplier_name: Optional[str]
    consumers: list[LotConsumer] = field(default_factory=list)

    @property
    def direct_consumers(self) -> list[LotConsumer]:
        return [c for c in self.consumers if c.direct]

    def at_depth(self, depth: int) -> list[LotConsumer]:
        return [c for c in self.consumers if c.depth == depth]


# --------------------------------------------------------------------------- #
# Downward: serial -> full as-built tree
# --------------------------------------------------------------------------- #

def serial_genealogy(session: Session, serial_number: str) -> SerialNode:
    """Return the complete as-built tree rooted at ``serial_number``.

    The whole subtree is bulk-loaded up front (a fixed handful of queries), then
    the tree is assembled in memory, so a deep, wide build history costs the
    same few round trips as a shallow one, not one query per node.

    Raises ``LookupError`` if no such serial exists.
    """
    root = session.scalar(
        select(m.AsBuiltSerialRecord).where(
            m.AsBuiltSerialRecord.serial_number == serial_number
        )
    )
    if root is None:
        raise LookupError(f"serial number not found: {serial_number!r}")

    # 1. Collect every serial id reachable downward, one BOM level per query.
    #    Only new ids are ever added, so a cycle terminates the walk.
    serial_ids: set[int] = {root.id}
    frontier: set[int] = {root.id}
    while frontier:
        children = set(
            session.scalars(
                select(m.AsBuiltComponent.consumed_serial_id).where(
                    m.AsBuiltComponent.serial_id.in_(frontier),
                    m.AsBuiltComponent.consumed_serial_id.isnot(None),
                )
            )
        )
        frontier = children - serial_ids
        serial_ids |= frontier

    store = _GenealogyStore.load(session, serial_ids)
    return store.build(root.id, frozenset())


class _GenealogyStore:
    """In-memory maps for a subtree, loaded in a fixed number of queries."""

    def __init__(self) -> None:
        self.records: dict[int, "m.AsBuiltSerialRecord"] = {}
        self.components: dict[int, list["m.AsBuiltComponent"]] = {}
        self.lots: dict[int, "m.SupplierLot"] = {}
        self.bom_lines: dict[int, "m.BomLine"] = {}
        self.coc_count: dict[int, int] = {}
        self.inspection: dict[int, "m.IncomingInspection"] = {}
        self.nc_by_lot: dict[int, list["m.Nonconformance"]] = {}
        self.nc_by_serial: dict[int, list["m.Nonconformance"]] = {}

    @classmethod
    def load(cls, session: Session, serial_ids: set[int]) -> "_GenealogyStore":
        s = cls()
        if not serial_ids:
            return s

        s.records = {
            r.id: r
            for r in session.scalars(
                select(m.AsBuiltSerialRecord)
                .options(
                    selectinload(m.AsBuiltSerialRecord.part),
                    selectinload(m.AsBuiltSerialRecord.work_order),
                )
                .where(m.AsBuiltSerialRecord.id.in_(serial_ids))
            )
        }

        comps = session.scalars(
            select(m.AsBuiltComponent)
            .where(m.AsBuiltComponent.serial_id.in_(serial_ids))
            .order_by(m.AsBuiltComponent.id)
        ).all()
        for c in comps:
            s.components.setdefault(c.serial_id, []).append(c)

        lot_ids = {c.consumed_supplier_lot_id for c in comps if c.consumed_supplier_lot_id}
        bom_line_ids = {c.bom_line_id for c in comps if c.bom_line_id}

        if bom_line_ids:
            s.bom_lines = {
                b.id: b
                for b in session.scalars(
                    select(m.BomLine).where(m.BomLine.id.in_(bom_line_ids))
                )
            }

        if lot_ids:
            s.lots = {
                lot.id: lot
                for lot in session.scalars(
                    select(m.SupplierLot)
                    .options(selectinload(m.SupplierLot.part))
                    .where(m.SupplierLot.id.in_(lot_ids))
                )
            }
            for lot_id in session.scalars(
                select(m.CertificateOfConformance.supplier_lot_id).where(
                    m.CertificateOfConformance.supplier_lot_id.in_(lot_ids)
                )
            ):
                s.coc_count[lot_id] = s.coc_count.get(lot_id, 0) + 1
            # Ascending order → the last row seen per lot is the latest inspection.
            for ins in session.scalars(
                select(m.IncomingInspection)
                .where(m.IncomingInspection.supplier_lot_id.in_(lot_ids))
                .order_by(m.IncomingInspection.inspected_at)
            ):
                s.inspection[ins.supplier_lot_id] = ins

        nc_where = m.Nonconformance.serial_id.in_(serial_ids)
        if lot_ids:
            nc_where = m.Nonconformance.supplier_lot_id.in_(lot_ids) | nc_where
        for nc in session.scalars(select(m.Nonconformance).where(nc_where)):
            if nc.supplier_lot_id is not None:
                s.nc_by_lot.setdefault(nc.supplier_lot_id, []).append(nc)
            elif nc.serial_id is not None:
                s.nc_by_serial.setdefault(nc.serial_id, []).append(nc)
        return s

    def build(self, sid: int, ancestors: frozenset[int]) -> SerialNode:
        rec = self.records.get(sid)
        if sid in ancestors:
            # Cycle: this unit already appears above it in the tree. Stop here.
            return SerialNode(
                serial_id=sid,
                serial_number=rec.serial_number if rec else None,
                part_number=None, part_name=None, work_order_number=None,
                built_at=rec.built_at if rec else None,
                is_cycle=True,
            )
        if rec is None:
            return SerialNode(
                serial_id=sid, serial_number=None, part_number=None, part_name=None,
                work_order_number=None, built_at=None,
            )

        part = rec.part
        wo = rec.work_order
        node = SerialNode(
            serial_id=rec.id,
            serial_number=rec.serial_number,
            part_number=part.part_number if part else None,
            part_name=part.name if part else None,
            work_order_number=wo.work_order_number if wo else None,
            built_at=rec.built_at,
            nonconformances=[_nc_view(nc) for nc in self.nc_by_serial.get(sid, [])],
        )
        next_ancestors = ancestors | {sid}
        for comp in self.components.get(sid, []):
            node.components.append(self._component(comp, next_ancestors))
        return node

    def _component(self, comp: "m.AsBuiltComponent", ancestors: frozenset[int]) -> ComponentNode:
        bom_line = self.bom_lines.get(comp.bom_line_id) if comp.bom_line_id else None
        base = dict(
            position=bom_line.position if bom_line else None,
            quantity=comp.quantity,
            bom_line_id=comp.bom_line_id,
        )
        if comp.consumed_supplier_lot_id is not None:
            lot = self.lots.get(comp.consumed_supplier_lot_id)
            if lot is None:
                return ComponentNode(kind="orphan", note="consumed supplier lot missing", **base)
            return ComponentNode(kind="lot", lot=self._lot_view(lot), **base)
        if comp.consumed_serial_id is not None:
            if comp.consumed_serial_id not in self.records:
                return ComponentNode(kind="orphan", note="consumed serial missing", **base)
            return ComponentNode(kind="serial", child=self.build(comp.consumed_serial_id, ancestors), **base)
        # XOR constraint should prevent this, but never trust the data blindly.
        return ComponentNode(kind="orphan", note="component has no source", **base)

    def _lot_view(self, lot: "m.SupplierLot") -> LotView:
        part = lot.part
        inspection = self.inspection.get(lot.id)
        coc = self.coc_count.get(lot.id, 0)
        return LotView(
            lot_id=lot.id,
            lot_number=lot.lot_number,
            part_number=part.part_number if part else None,
            part_name=part.name if part else None,
            supplier_name=lot.supplier_name,
            received_at=lot.received_at,
            certificate_status="present" if coc else "absent",
            certificate_count=coc,
            inspection_disposition=inspection.disposition.value if inspection else None,
            inspection_notes=inspection.result_notes if inspection else None,
            nonconformances=[_nc_view(nc) for nc in self.nc_by_lot.get(lot.id, [])],
        )


def _nc_view(nc: "m.Nonconformance") -> NCView:
    status = nc.status.value if nc.status is not None else None
    return NCView(nc_number=nc.nc_number, status=status, description=nc.description)


# --------------------------------------------------------------------------- #
# Upward: supplier lot -> every consuming serial, at any depth
# --------------------------------------------------------------------------- #

def lot_where_used(session: Session, lot_number: str) -> LotUsage:
    """Return every serial that consumed ``lot_number`` at any BOM depth.

    Raises ``LookupError`` if no such lot exists.
    """
    lot = session.scalar(
        select(m.SupplierLot).where(m.SupplierLot.lot_number == lot_number)
    )
    if lot is None:
        raise LookupError(f"lot number not found: {lot_number!r}")

    # Serials that consumed the lot directly.
    direct_ids = set(
        session.scalars(
            select(m.AsBuiltComponent.serial_id).where(
                m.AsBuiltComponent.consumed_supplier_lot_id == lot.id
            )
        )
    )

    # Walk upward one BOM level at a time, one query per level, not one per node
    #, so the whole traversal is a handful of round trips regardless of fan-out.
    # ``depth_by_id`` doubles as the visited set, so a cycle can never re-expand.
    depth_by_id: dict[int, int] = {sid: 0 for sid in direct_ids}
    frontier = set(direct_ids)
    depth = 0
    while frontier:
        depth += 1
        parents = set(
            session.scalars(
                select(m.AsBuiltComponent.serial_id).where(
                    m.AsBuiltComponent.consumed_serial_id.in_(frontier)
                )
            )
        )
        frontier = {pid for pid in parents if pid not in depth_by_id}
        for pid in frontier:
            depth_by_id[pid] = depth

    # Bulk-load every consuming record (with its part and work order) in one go.
    records: dict[int, "m.AsBuiltSerialRecord"] = {}
    if depth_by_id:
        rows = session.scalars(
            select(m.AsBuiltSerialRecord)
            .options(
                selectinload(m.AsBuiltSerialRecord.part),
                selectinload(m.AsBuiltSerialRecord.work_order),
            )
            .where(m.AsBuiltSerialRecord.id.in_(depth_by_id.keys()))
        ).all()
        records = {r.id: r for r in rows}

    consumers: list[LotConsumer] = []
    for sid, d in depth_by_id.items():
        rec = records.get(sid)
        if rec is None:
            consumers.append(LotConsumer(
                serial_id=sid, serial_number=None, part_number=None, part_name=None,
                part_type=None, work_order_number=None, built_at=None, depth=d,
                direct=(d == 0), is_orphan=True,
            ))
            continue
        part = rec.part
        wo = rec.work_order
        consumers.append(LotConsumer(
            serial_id=sid,
            serial_number=rec.serial_number,
            part_number=part.part_number if part else None,
            part_name=part.name if part else None,
            part_type=part.part_type.value if part and part.part_type else None,
            work_order_number=wo.work_order_number if wo else None,
            built_at=rec.built_at,
            depth=d,
            direct=(d == 0),
            voided=rec.voided_at is not None,
        ))

    consumers.sort(key=lambda c: (c.depth, c.serial_number or ""))
    return LotUsage(
        lot_id=lot.id,
        lot_number=lot.lot_number,
        supplier_name=lot.supplier_name,
        consumers=consumers,
    )
