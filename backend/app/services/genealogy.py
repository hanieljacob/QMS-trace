"""Genealogy traversals — the two queries qmstrace exists to answer.

Pure functions over a SQLAlchemy ``Session``; no web framework, no request or
response objects. Each returns plain dataclasses so callers (an API layer, a
CLI, a test) can shape the output however they like.

Two traversals, mapped to the CLAUDE.md vocabulary:

* :func:`serial_genealogy` — given a serial number, walk *down* the as-built
  tree to every component position, the lot consumed there, and that lot's
  supplier / certificate / inspection / nonconformance. This assembles the
  device history record (CLAUDE.md "forward trace").
* :func:`lot_where_used` — given a supplier lot, walk *up* to every serial that
  consumed it at any depth, with the work order and build date for each
  (CLAUDE.md "backward trace").

Both are defensive about two kinds of bad data:

* **Cycles** — an as-built graph should never contain one, but if a serial ends
  up (transitively) consuming itself, traversal stops instead of looping
  forever. Downward it is flagged as ``is_cycle``; upward the visited-set simply
  refuses to re-expand a node.
* **Orphan references** — a component pointing at a lot or serial row that is
  not there (or a missing part / work order / bom line) is reported as an
  ``orphan`` / ``None`` field rather than raising.
"""

from __future__ import annotations

import datetime
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    ``"orphan"`` (neither — a dangling or malformed reference, see ``note``).
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

    Raises ``LookupError`` if no such serial exists.
    """
    rec = session.scalar(
        select(m.AsBuiltSerialRecord).where(
            m.AsBuiltSerialRecord.serial_number == serial_number
        )
    )
    if rec is None:
        raise LookupError(f"serial number not found: {serial_number!r}")
    return _serial_node(session, rec, frozenset())


def _serial_node(
    session: Session, rec: "m.AsBuiltSerialRecord", ancestors: frozenset[int]
) -> SerialNode:
    if rec.id in ancestors:
        # Cycle: this unit already appears above it in the tree. Stop here.
        return SerialNode(
            serial_id=rec.id,
            serial_number=rec.serial_number,
            part_number=None,
            part_name=None,
            work_order_number=None,
            built_at=rec.built_at,
            is_cycle=True,
        )

    part = session.get(m.Part, rec.part_id)
    wo = session.get(m.WorkOrder, rec.work_order_id)
    node = SerialNode(
        serial_id=rec.id,
        serial_number=rec.serial_number,
        part_number=part.part_number if part else None,
        part_name=part.name if part else None,
        work_order_number=wo.work_order_number if wo else None,
        built_at=rec.built_at,
    )

    for nc in session.scalars(
        select(m.Nonconformance).where(m.Nonconformance.serial_id == rec.id)
    ):
        node.nonconformances.append(_nc_view(nc))

    next_ancestors = ancestors | {rec.id}
    comps = session.scalars(
        select(m.AsBuiltComponent)
        .where(m.AsBuiltComponent.serial_id == rec.id)
        .order_by(m.AsBuiltComponent.id)
    )
    for comp in comps:
        node.components.append(_component_node(session, comp, next_ancestors))
    return node


def _component_node(
    session: Session, comp: "m.AsBuiltComponent", ancestors: frozenset[int]
) -> ComponentNode:
    bom_line = session.get(m.BomLine, comp.bom_line_id) if comp.bom_line_id else None
    position = bom_line.position if bom_line else None
    base = dict(position=position, quantity=comp.quantity, bom_line_id=comp.bom_line_id)

    if comp.consumed_supplier_lot_id is not None:
        lot = session.get(m.SupplierLot, comp.consumed_supplier_lot_id)
        if lot is None:
            return ComponentNode(
                kind="orphan", note="consumed supplier lot missing", **base
            )
        return ComponentNode(kind="lot", lot=_lot_view(session, lot), **base)

    if comp.consumed_serial_id is not None:
        child = session.get(m.AsBuiltSerialRecord, comp.consumed_serial_id)
        if child is None:
            return ComponentNode(
                kind="orphan", note="consumed serial missing", **base
            )
        return ComponentNode(
            kind="serial", child=_serial_node(session, child, ancestors), **base
        )

    # XOR constraint should prevent this, but never trust the data blindly.
    return ComponentNode(kind="orphan", note="component has no source", **base)


def _lot_view(session: Session, lot: "m.SupplierLot") -> LotView:
    certs = session.scalars(
        select(m.CertificateOfConformance).where(
            m.CertificateOfConformance.supplier_lot_id == lot.id
        )
    ).all()
    inspection = session.scalars(
        select(m.IncomingInspection)
        .where(m.IncomingInspection.supplier_lot_id == lot.id)
        .order_by(m.IncomingInspection.inspected_at.desc())
    ).first()
    ncs = [
        _nc_view(nc)
        for nc in session.scalars(
            select(m.Nonconformance).where(m.Nonconformance.supplier_lot_id == lot.id)
        )
    ]
    part = session.get(m.Part, lot.part_id)
    return LotView(
        lot_id=lot.id,
        lot_number=lot.lot_number,
        part_number=part.part_number if part else None,
        part_name=part.name if part else None,
        supplier_name=lot.supplier_name,
        received_at=lot.received_at,
        certificate_status="present" if certs else "absent",
        certificate_count=len(certs),
        inspection_disposition=inspection.disposition.value if inspection else None,
        inspection_notes=inspection.result_notes if inspection else None,
        nonconformances=ncs,
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

    # Breadth-first walk upward: a parent is any serial that consumed a serial we
    # already reached. ``depth_by_id`` doubles as the visited set, so a cycle can
    # never re-expand a node.
    depth_by_id: dict[int, int] = {}
    queue: deque[int] = deque()
    for sid in direct_ids:
        depth_by_id[sid] = 0
        queue.append(sid)

    while queue:
        sid = queue.popleft()
        depth = depth_by_id[sid]
        parents = session.scalars(
            select(m.AsBuiltComponent.serial_id).where(
                m.AsBuiltComponent.consumed_serial_id == sid
            )
        )
        for pid in parents:
            if pid not in depth_by_id:
                depth_by_id[pid] = depth + 1
                queue.append(pid)

    consumers: list[LotConsumer] = []
    for sid, depth in depth_by_id.items():
        rec = session.get(m.AsBuiltSerialRecord, sid)
        if rec is None:
            consumers.append(LotConsumer(
                serial_id=sid, serial_number=None, part_number=None, part_name=None,
                part_type=None, work_order_number=None, built_at=None, depth=depth,
                direct=(depth == 0), is_orphan=True,
            ))
            continue
        part = session.get(m.Part, rec.part_id)
        wo = session.get(m.WorkOrder, rec.work_order_id)
        consumers.append(LotConsumer(
            serial_id=sid,
            serial_number=rec.serial_number,
            part_number=part.part_number if part else None,
            part_name=part.name if part else None,
            part_type=part.part_type.value if part and part.part_type else None,
            work_order_number=wo.work_order_number if wo else None,
            built_at=rec.built_at,
            depth=depth,
            direct=(depth == 0),
        ))

    consumers.sort(key=lambda c: (c.depth, c.serial_number or ""))
    return LotUsage(
        lot_id=lot.id,
        lot_number=lot.lot_number,
        supplier_name=lot.supplier_name,
        consumers=consumers,
    )
