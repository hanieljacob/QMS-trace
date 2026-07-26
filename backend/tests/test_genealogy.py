"""Tests for the genealogy traversals.

The seeded-data tests assert *exact* counts against the deterministic demo
dataset (see scripts/seed.py), which is rebuilt once per test session. The
cycle and orphan tests build tiny hand-crafted databases to prove the
traversals stay defensive when the data is malformed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models as m
from app.database import Base
from app.services.genealogy import lot_where_used, serial_genealogy

BACKEND = Path(__file__).resolve().parent.parent

CONTAM_BEARING_LOT = "CMP610-NBA-02"
CONTAM_ADHESIVE_LOT = "CMP660-TBA-02"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    """Rebuild the deterministic demo database once for the whole test session."""
    subprocess.run(
        [sys.executable, "scripts/seed.py"],
        cwd=BACKEND, check=True, capture_output=True,
    )


@pytest.fixture
def session():
    from app.database import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _memory_engine():
    # In-memory SQLite (SingletonThreadPool keeps a single connection, so the
    # schema and data persist for the life of the engine).
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def memory_session():
    """FK-enforced scratch DB for the cycle test (all references are valid)."""
    engine = _memory_engine()
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture
def fk_off_session():
    """Scratch DB with FK enforcement OFF, so genuine dangling references can be
    inserted for the orphan-defense test."""
    engine = _memory_engine()
    conn = engine.connect()
    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        conn.close()
        engine.dispose()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _flatten(root):
    """Walk a SerialNode tree, collecting serial numbers, consumed lot numbers,
    surfaced NC numbers, and the maximum serial depth."""
    serials, lots, ncs = [], [], []
    max_depth = 0

    def walk(node, depth):
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        serials.append(node.serial_number)
        ncs.extend(nc.nc_number for nc in node.nonconformances)
        for comp in node.components:
            if comp.kind == "lot":
                lots.append(comp.lot.lot_number)
                ncs.extend(nc.nc_number for nc in comp.lot.nonconformances)
            elif comp.kind == "serial":
                walk(comp.child, depth + 1)

    walk(root, 0)
    return serials, lots, ncs, max_depth


# --------------------------------------------------------------------------- #
# Backward trace: lot -> consuming serials (exact seeded counts)
# --------------------------------------------------------------------------- #

def test_where_used_contaminated_bearing_counts(session):
    usage = lot_where_used(session, CONTAM_BEARING_LOT)

    assert usage.supplier_name == "Nordic Bearings AB"
    # 9 direct + 5 joint assemblies + 2 finished arms = 16 total.
    assert len(usage.consumers) == 16
    assert len(usage.direct_consumers) == 9
    assert len(usage.at_depth(1)) == 5
    assert len(usage.at_depth(2)) == 2

    direct = {c.serial_number for c in usage.direct_consumers}
    assert direct == {
        "SMM-0001", "SMM-0002", "SMM-0003", "SMM-0004", "SMM-0005",
        "HDG-0001", "HDG-0002", "BCG-0001", "BCG-0002",
    }
    # The bad bearing reached both finished arms.
    arms = {c.serial_number for c in usage.consumers if c.part_number == "SRA-1000"}
    assert arms == {"SRA-0001", "SRA-0002"}

    # Every consumer carries a work order and a build date.
    assert all(c.work_order_number for c in usage.consumers)
    assert all(c.built_at is not None for c in usage.consumers)


def test_where_used_contaminated_adhesive_counts(session):
    usage = lot_where_used(session, CONTAM_ADHESIVE_LOT)

    assert usage.supplier_name == "ThermoBond Adhesives"
    # 6 direct + 3 + 1 = 10 total, spanning multiple work orders.
    assert len(usage.consumers) == 10
    assert len(usage.direct_consumers) == 6
    assert len(usage.at_depth(1)) == 3
    assert len(usage.at_depth(2)) == 1

    spanned_wos = {c.work_order_number for c in usage.direct_consumers}
    assert len(spanned_wos) >= 2  # the open NC spans multiple work orders
    arms = {c.serial_number for c in usage.consumers if c.part_number == "SRA-1000"}
    assert arms == {"SRA-0001", "SRA-0002"}


# --------------------------------------------------------------------------- #
# Forward trace: serial -> full as-built tree (exact seeded counts)
# --------------------------------------------------------------------------- #

def test_serial_genealogy_finished_arm(session):
    root = serial_genealogy(session, "SRA-0001")

    assert root.part_number == "SRA-1000"
    # base + interface assemblies are not built in this seed batch, so those two
    # positions stay open: 5 serialized children + 2 lots = 7 components.
    assert len(root.components) == 7

    serials, lots, ncs, max_depth = _flatten(root)
    assert len(set(serials)) == 21          # arm + 3 joints + 15 joint-children + harness + control
    assert len(serials) == 21               # no serial appears twice (no cycles)
    assert len(lots) == 72                  # total consumed-lot positions in the tree
    assert max_depth == 2                   # arm(0) -> joint(1) -> sub-assembly(2) -> lot leaf

    # The contaminated lots surface deep in this arm's history.
    assert lots.count(CONTAM_BEARING_LOT) == 5
    assert lots.count(CONTAM_ADHESIVE_LOT) == 4
    # The open adhesive nonconformance is visible wherever that lot was consumed.
    assert ncs.count("NC-1001") == 4


def test_serial_genealogy_surfaces_failed_inspection(session):
    """A bearing lot's failed incoming inspection must be visible in the tree."""
    root = serial_genealogy(session, "SRA-0001")

    def find_lot(node, lot_number):
        for comp in node.components:
            if comp.kind == "lot" and comp.lot.lot_number == lot_number:
                return comp.lot
            if comp.kind == "serial":
                hit = find_lot(comp.child, lot_number)
                if hit:
                    return hit
        return None

    lot = find_lot(root, CONTAM_BEARING_LOT)
    assert lot is not None
    assert lot.inspection_disposition == "rejected"
    assert lot.certificate_status == "absent"


def test_serial_genealogy_direct_bearing_consumer(session):
    root = serial_genealogy(session, "SMM-0001")
    bearing = [
        c for c in root.components
        if c.kind == "lot" and c.lot.lot_number == CONTAM_BEARING_LOT
    ]
    assert len(bearing) == 1
    assert bearing[0].lot.inspection_disposition == "rejected"
    assert bearing[0].quantity == 2  # two bearings per servo module


# --------------------------------------------------------------------------- #
# Not-found handling
# --------------------------------------------------------------------------- #

def test_unknown_serial_raises(session):
    with pytest.raises(LookupError):
        serial_genealogy(session, "DOES-NOT-EXIST")


def test_unknown_lot_raises(session):
    with pytest.raises(LookupError):
        lot_where_used(session, "DOES-NOT-EXIST")


# --------------------------------------------------------------------------- #
# Cycle defense
# --------------------------------------------------------------------------- #

def _mk_part(s, number, name, ptype=m.PartType.component):
    p = m.Part(part_number=number, name=name, part_type=ptype, created_by="test")
    s.add(p)
    s.flush()
    return p


def _mk_serial(s, number, part, wo):
    rec = m.AsBuiltSerialRecord(
        serial_number=number, part_id=part.id, work_order_id=wo.id, created_by="test"
    )
    s.add(rec)
    s.flush()
    return rec


def test_cycle_is_handled(memory_session):
    s = memory_session
    part = _mk_part(s, "P-1", "Cyclic Part")
    wo = m.WorkOrder(
        work_order_number="WO-CY", part_id=part.id, quantity_ordered=2,
        status=m.WorkOrderStatus.completed, created_by="test",
    )
    s.add(wo)
    s.flush()
    lot_part = _mk_part(s, "P-LOT", "Bought Part", m.PartType.raw_material)
    lot = m.SupplierLot(
        part_id=lot_part.id, lot_number="LOT-CY", supplier_name="Acme",
        quantity_received=10, received_at=__import__("datetime").date(2026, 1, 1),
        created_by="test",
    )
    s.add(lot)
    s.flush()

    s1 = _mk_serial(s, "S1", part, wo)
    s2 = _mk_serial(s, "S2", part, wo)
    # S1 consumes a lot and S2; S2 consumes S1 -> a cycle S1 <-> S2.
    s.add_all([
        m.AsBuiltComponent(serial_id=s1.id, consumed_supplier_lot_id=lot.id, quantity=1, created_by="test"),
        m.AsBuiltComponent(serial_id=s1.id, consumed_serial_id=s2.id, quantity=1, created_by="test"),
        m.AsBuiltComponent(serial_id=s2.id, consumed_serial_id=s1.id, quantity=1, created_by="test"),
    ])
    s.commit()

    # Downward: must terminate and flag the repeated node instead of looping.
    root = serial_genealogy(s, "S1")
    cycle_nodes = []

    def collect(node, seen):
        if node.is_cycle:
            cycle_nodes.append(node.serial_number)
            return
        for comp in node.components:
            if comp.kind == "serial":
                collect(comp.child, seen)

    collect(root, set())
    assert cycle_nodes == ["S1"]  # S1 -> S2 -> S1(cycle, stops)

    # Upward: must terminate and reach both serials exactly once.
    usage = lot_where_used(s, "LOT-CY")
    assert {c.serial_number for c in usage.consumers} == {"S1", "S2"}


# --------------------------------------------------------------------------- #
# Orphan-reference defense
# --------------------------------------------------------------------------- #

def test_orphan_references_are_handled(fk_off_session):
    s = fk_off_session
    part = _mk_part(s, "P-1", "Part")
    wo = m.WorkOrder(
        work_order_number="WO-OR", part_id=part.id, quantity_ordered=1,
        status=m.WorkOrderStatus.completed, created_by="test",
    )
    s.add(wo)
    s.flush()
    real_part = _mk_part(s, "P-LOT", "Bought", m.PartType.raw_material)
    lot = m.SupplierLot(
        part_id=real_part.id, lot_number="LOT-OK", supplier_name="Acme",
        quantity_received=5, received_at=__import__("datetime").date(2026, 1, 1),
        created_by="test",
    )
    s.add(lot)
    s.flush()
    s1 = _mk_serial(s, "S1", part, wo)

    # Dangling references: a missing lot and a missing child serial.
    s.add_all([
        m.AsBuiltComponent(serial_id=s1.id, consumed_supplier_lot_id=999_999, quantity=1, created_by="test"),
        m.AsBuiltComponent(serial_id=s1.id, consumed_serial_id=888_888, quantity=1, created_by="test"),
    ])
    # A dangling *parent*: a component whose owning serial does not exist, but
    # which consumes a real lot -> shows up as an orphan consumer, not a crash.
    s.add(m.AsBuiltComponent(serial_id=777_777, consumed_supplier_lot_id=lot.id, quantity=1, created_by="test"))
    s.commit()

    # Downward: both dangling children become orphan nodes, no exception.
    root = serial_genealogy(s, "S1")
    kinds = sorted(c.kind for c in root.components)
    assert kinds == ["orphan", "orphan"]
    assert all(c.note for c in root.components)

    # Upward: the orphan parent is reported defensively.
    usage = lot_where_used(s, "LOT-OK")
    assert len(usage.consumers) == 1
    assert usage.consumers[0].is_orphan is True
    assert usage.consumers[0].serial_number is None
