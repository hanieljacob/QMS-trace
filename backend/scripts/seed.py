#!/usr/bin/env python3
"""Seed qmstrace with a plausible surgical robot arm dataset for demos.

Run it (from anywhere) to rebuild the demo database from scratch:

    python scripts/seed.py

What "from scratch" and "idempotent" mean here:

* The script REBUILDS the demo database, it drops and recreates every table
  through Alembic (downgrade base -> upgrade head), then repopulates. That reset
  is a developer fixture tool operating on the throwaway demo SQLite file. It is
  NOT an application data path; the app itself still never hard-deletes domain
  records (see CLAUDE.md).
* Data generation is deterministic (fixed RNG seed) and the schema is rebuilt
  every run, so each run yields the same logical dataset, rerunning is safe and
  produces identical results.

Two lots are deliberately contaminated so the demo has something to chase:

  1. A precision-bearing lot that FAILED incoming inspection but was consumed
     into 9 built units anyway (a process escape caught at receiving, used in
     spite of it).
  2. A structural-adhesive lot that passed receiving but later drew an OPEN
     nonconformance, and which was consumed across multiple work orders.

The affected lot numbers and a few affected serial numbers are printed at the
end for use in the demo.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
# Make DATABASE_URL's relative "./qmstrace.db" resolve to backend/ regardless of
# where the script is invoked from.
os.chdir(BASE_DIR)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select  # noqa: E402

import app.models as m  # noqa: E402
from app.database import SessionLocal  # noqa: E402

RNG = random.Random(20260726)
SEED_ACTOR = "seed"


# --------------------------------------------------------------------------- #
# Static domain definitions
# --------------------------------------------------------------------------- #

# key -> (part_number, name, part_type, unit_of_measure, purchased?)
PARTS: dict[str, tuple[str, str, m.PartType, str, bool]] = {
    "arm": ("SRA-1000", "Surgical Robot Arm", m.PartType.finished_device, "ea", False),
    # Level-1 assemblies
    "base_asm": ("ASM-100", "Base Assembly", m.PartType.component, "ea", False),
    "shoulder_asm": ("ASM-210", "Shoulder Joint Assembly", m.PartType.component, "ea", False),
    "elbow_asm": ("ASM-220", "Elbow Joint Assembly", m.PartType.component, "ea", False),
    "wrist_asm": ("ASM-230", "Wrist Joint Assembly", m.PartType.component, "ea", False),
    "iface_asm": ("ASM-300", "Instrument Interface Assembly", m.PartType.component, "ea", False),
    "ctrl_mod": ("ASM-400", "Control Electronics Module", m.PartType.component, "ea", False),
    # Level-2 sub-assemblies
    "servo_mod": ("SUB-510", "Servo Motor Module", m.PartType.component, "ea", False),
    "gearbox": ("SUB-520", "Harmonic Drive Gearbox", m.PartType.component, "ea", False),
    "encoder_mod": ("SUB-530", "Encoder Module", m.PartType.component, "ea", False),
    "bearing_cart": ("SUB-540", "Bearing Cartridge", m.PartType.component, "ea", False),
    "joint_housing": ("SUB-550", "Joint Housing", m.PartType.component, "ea", False),
    "cable_harness": ("SUB-560", "Cable Harness Assembly", m.PartType.component, "ea", False),
    # Purchased components / raw materials
    "bearing": ("CMP-610", "Precision Bearing", m.PartType.raw_material, "ea", True),
    "stator": ("CMP-620", "Motor Stator", m.PartType.raw_material, "ea", True),
    "rotor": ("CMP-630", "Motor Rotor", m.PartType.raw_material, "ea", True),
    "enc_disc": ("CMP-640", "Encoder Disc", m.PartType.raw_material, "ea", True),
    "enc_pcb": ("CMP-650", "Encoder PCB", m.PartType.raw_material, "ea", True),
    "adhesive": ("CMP-660", "Structural Adhesive", m.PartType.raw_material, "ml", True),
    "screw": ("CMP-670", "Socket Head Screw M3", m.PartType.raw_material, "ea", True),
    "oring": ("CMP-680", "O-Ring Seal", m.PartType.raw_material, "ea", True),
    "wire": ("CMP-690", "Hookup Wire", m.PartType.raw_material, "m", True),
    "connector": ("CMP-700", "Circular Connector", m.PartType.raw_material, "ea", True),
    "grease": ("CMP-710", "Bearing Grease", m.PartType.raw_material, "ml", True),
    "housing_blank": ("CMP-720", "Aluminum Housing Blank", m.PartType.raw_material, "ea", True),
    "thermal": ("CMP-730", "Thermal Paste", m.PartType.raw_material, "ml", True),
}

PURCHASED = {k for k, v in PARTS.items() if v[4]}

# parent_key -> list of (child_key, quantity, position)
BOM: dict[str, list[tuple[str, int, str]]] = {
    "arm": [
        ("base_asm", 1, "BASE"),
        ("shoulder_asm", 1, "J1-SHOULDER"),
        ("elbow_asm", 1, "J2-ELBOW"),
        ("wrist_asm", 1, "J3-WRIST"),
        ("iface_asm", 1, "IFACE"),
        ("ctrl_mod", 1, "CTRL"),
        ("cable_harness", 1, "HARNESS"),
        ("screw", 12, "FASTENERS"),
        ("adhesive", 1, "BOND"),
    ],
    "base_asm": [
        ("joint_housing", 1, "HSG"),
        ("bearing_cart", 1, "BRG"),
        ("screw", 8, "FASTENERS"),
        ("adhesive", 1, "BOND"),
    ],
    # The three joint assemblies share a recipe.
    "shoulder_asm": [
        ("servo_mod", 1, "MOTOR"),
        ("gearbox", 1, "GEAR"),
        ("encoder_mod", 1, "ENCODER"),
        ("bearing_cart", 1, "BRG"),
        ("joint_housing", 1, "HSG"),
        ("screw", 8, "FASTENERS"),
        ("adhesive", 1, "BOND"),
    ],
    "iface_asm": [
        ("oring", 2, "SEALS"),
        ("connector", 1, "CONN"),
        ("screw", 4, "FASTENERS"),
        ("adhesive", 1, "BOND"),
    ],
    "ctrl_mod": [
        ("enc_pcb", 1, "PCB"),
        ("thermal", 1, "TIM"),
        ("connector", 1, "CONN"),
        ("screw", 4, "FASTENERS"),
    ],
    "servo_mod": [
        ("stator", 1, "STATOR"),
        ("rotor", 1, "ROTOR"),
        ("bearing", 2, "BRG"),
        ("grease", 1, "LUBE"),
        ("screw", 4, "FASTENERS"),
    ],
    "gearbox": [
        ("bearing", 2, "BRG"),
        ("grease", 1, "LUBE"),
        ("housing_blank", 1, "HSG"),
        ("screw", 6, "FASTENERS"),
    ],
    "encoder_mod": [
        ("enc_disc", 1, "DISC"),
        ("enc_pcb", 1, "PCB"),
        ("bearing", 1, "BRG"),
        ("adhesive", 1, "BOND"),
        ("thermal", 1, "TIM"),
    ],
    "bearing_cart": [
        ("bearing", 2, "BRG"),
        ("oring", 2, "SEALS"),
        ("grease", 1, "LUBE"),
        ("adhesive", 1, "BOND"),
    ],
    "joint_housing": [
        ("housing_blank", 1, "BLANK"),
    ],
    "cable_harness": [
        ("wire", 5, "WIRE"),
        ("connector", 2, "CONN"),
        ("screw", 2, "FASTENERS"),
    ],
}
# Elbow and wrist reuse the shoulder recipe.
BOM["elbow_asm"] = list(BOM["shoulder_asm"])
BOM["wrist_asm"] = list(BOM["shoulder_asm"])

# purchased part key -> (supplier_name, supplier_code, number_of_lots)
SUPPLY: dict[str, tuple[str, str, int]] = {
    "bearing": ("Nordic Bearings AB", "NBA", 5),
    "stator": ("Precision Motion Co", "PMC", 3),
    "rotor": ("Precision Motion Co", "PMC", 3),
    "grease": ("Precision Motion Co", "PMC", 3),
    "adhesive": ("ThermoBond Adhesives", "TBA", 4),
    "thermal": ("ThermoBond Adhesives", "TBA", 3),
    "enc_pcb": ("ElectroCore PCB", "ECP", 3),
    "connector": ("ElectroCore PCB", "ECP", 2),
    "wire": ("ElectroCore PCB", "ECP", 2),
    "enc_disc": ("MicroEncoder Systems", "MES", 3),
    "screw": ("FastenRight Fasteners", "FRF", 4),
    "oring": ("SealTech Elastomers", "STE", 3),
    "housing_blank": ("AlloyForm Metals", "AFM", 2),
}  # total lots = 40 across 8 suppliers

# Work orders in build (dependency) order: (wo_number, built_part_key, quantity)
WORK_ORDERS: list[tuple[str, str, int]] = [
    ("WO-2001", "servo_mod", 7),
    ("WO-2002", "servo_mod", 9),
    ("WO-2003", "gearbox", 7),
    ("WO-2004", "encoder_mod", 7),
    ("WO-2005", "bearing_cart", 7),
    ("WO-2006", "joint_housing", 7),
    ("WO-2007", "cable_harness", 4),
    ("WO-2008", "ctrl_mod", 4),
    ("WO-2009", "shoulder_asm", 2),
    ("WO-2010", "elbow_asm", 2),
    ("WO-2011", "wrist_asm", 2),
    ("WO-2012", "arm", 2),
]  # total units = 60

SERIAL_PREFIX: dict[str, str] = {
    "servo_mod": "SMM",
    "gearbox": "HDG",
    "encoder_mod": "ENC",
    "bearing_cart": "BCG",
    "joint_housing": "JHS",
    "cable_harness": "CHA",
    "ctrl_mod": "CEM",
    "shoulder_asm": "SHJ",
    "elbow_asm": "ELJ",
    "wrist_asm": "WRJ",
    "arm": "SRA",
}


# --------------------------------------------------------------------------- #
# Reset (rebuild schema from scratch via Alembic)
# --------------------------------------------------------------------------- #

def reset_database() -> None:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #

def seed() -> None:
    session = SessionLocal()
    try:
        # -- Parts -------------------------------------------------------- #
        part = {}
        for key, (pn, name, ptype, uom, _purchased) in PARTS.items():
            p = m.Part(
                part_number=pn, name=name, part_type=ptype,
                unit_of_measure=uom, created_by=SEED_ACTOR,
            )
            session.add(p)
            part[key] = p
        session.flush()

        # -- Bill of materials -------------------------------------------- #
        # (parent_id, child_id) -> BomLine, for wiring as-built consumption.
        bom_line = {}
        for parent_key, lines in BOM.items():
            for child_key, qty, position in lines:
                bl = m.BomLine(
                    parent_part_id=part[parent_key].id,
                    child_part_id=part[child_key].id,
                    position=position,
                    quantity=Decimal(qty),
                    created_by=SEED_ACTOR,
                )
                session.add(bl)
                bom_line[(part[parent_key].id, part[child_key].id)] = bl
        session.flush()

        # -- Supplier lots (+ incoming inspection, +CoC) ------------------ #
        lots: dict[str, list[m.SupplierLot]] = {}
        base_receipt = date(2026, 1, 6)
        # A handful of non-contaminated lots get non-ideal (but accepted)
        # dispositions for realism; chosen deterministically below.
        flavour_lots: list[m.SupplierLot] = []

        for key, (supplier_name, supplier_code, count) in SUPPLY.items():
            pn_compact = PARTS[key][0].replace("-", "")
            lots[key] = []
            for i in range(count):
                lot = m.SupplierLot(
                    part_id=part[key].id,
                    lot_number=f"{pn_compact}-{supplier_code}-{i + 1:02d}",
                    supplier_name=supplier_name,
                    quantity_received=Decimal(RNG.randint(20, 500)),
                    received_at=base_receipt + timedelta(days=RNG.randint(0, 40)),
                    created_by=SEED_ACTOR,
                )
                session.add(lot)
                lots[key].append(lot)
        session.flush()

        # The two contaminated lots.
        contaminated_bearing = lots["bearing"][1]
        contaminated_adhesive = lots["adhesive"][1]

        # Good-lot pools exclude the contaminated lots from random selection.
        good_lots = {k: list(v) for k, v in lots.items()}
        good_lots["bearing"] = [x for x in lots["bearing"] if x is not contaminated_bearing]
        good_lots["adhesive"] = [x for x in lots["adhesive"] if x is not contaminated_adhesive]

        # Pick a few non-contaminated lots for "accepted_with_deviation" flavour.
        all_good = [x for k in lots for x in good_lots.get(k, lots[k])]
        flavour_lots = RNG.sample(all_good, 4)

        for key, lot_list in lots.items():
            for lot in lot_list:
                if lot is contaminated_bearing:
                    disposition = m.InspectionDisposition.rejected
                    notes = (
                        "Bore diameter above upper limit; radial play exceeds "
                        "spec. Lot REJECTED at receiving."
                    )
                elif lot in flavour_lots:
                    disposition = m.InspectionDisposition.accepted_with_deviation
                    notes = "Minor cosmetic finding; accepted with deviation."
                else:
                    disposition = m.InspectionDisposition.accepted
                    notes = None
                session.add(m.IncomingInspection(
                    supplier_lot_id=lot.id,
                    inspected_at=datetime.combine(lot.received_at, datetime.min.time(), tzinfo=timezone.utc),
                    disposition=disposition,
                    result_notes=notes,
                    created_by=SEED_ACTOR,
                ))
                # Certificate of conformance on every lot except the rejected one.
                if lot is not contaminated_bearing:
                    session.add(m.CertificateOfConformance(
                        supplier_lot_id=lot.id,
                        document_reference=f"CoC-{lot.lot_number}",
                        issued_at=lot.received_at,
                        created_by=SEED_ACTOR,
                    ))

        # Open nonconformance against the adhesive lot (found after receiving).
        adhesive_nc = m.Nonconformance(
            nc_number="NC-1001",
            supplier_lot_id=contaminated_adhesive.id,
            description=(
                "Structural adhesive viscosity out of specification; suspected "
                "incomplete cure and reduced bond strength. Lot quarantined "
                "pending disposition."
            ),
            status=m.NonconformanceStatus.open,
            created_by=SEED_ACTOR,
        )
        session.add(adhesive_nc)
        session.flush()

        # -- Work orders + as-built serial records ------------------------ #
        work_order = {}
        built_units: dict[str, list[m.AsBuiltSerialRecord]] = {k: [] for k in SERIAL_PREFIX}
        serial_counter: dict[str, int] = {k: 0 for k in SERIAL_PREFIX}
        base_build = date(2026, 3, 2)

        for wo_number, part_key, qty in WORK_ORDERS:
            wo = m.WorkOrder(
                work_order_number=wo_number,
                part_id=part[part_key].id,
                quantity_ordered=Decimal(qty),
                status=m.WorkOrderStatus.completed,
                created_by=SEED_ACTOR,
            )
            session.add(wo)
            session.flush()
            work_order[wo_number] = wo
            for _ in range(qty):
                serial_counter[part_key] += 1
                prefix = SERIAL_PREFIX[part_key]
                unit = m.AsBuiltSerialRecord(
                    serial_number=f"{prefix}-{serial_counter[part_key]:04d}",
                    part_id=part[part_key].id,
                    work_order_id=wo.id,
                    built_at=datetime.combine(
                        base_build + timedelta(days=RNG.randint(0, 90)),
                        datetime.min.time(), tzinfo=timezone.utc,
                    ),
                    created_by=SEED_ACTOR,
                )
                session.add(unit)
                built_units[part_key].append(unit)
        session.flush()

        # -- Designate contaminated consumption --------------------------- #
        # Exactly 9 units consume the failed bearing lot (across servo modules,
        # gearboxes, and bearing cartridges).
        contam_bearing_units = (
            built_units["servo_mod"][0:5]
            + built_units["gearbox"][0:2]
            + built_units["bearing_cart"][0:2]
        )
        # The open-NC adhesive lot spans four different work orders.
        contam_adhesive_units = (
            built_units["encoder_mod"][0:2]     # WO-2004
            + built_units["bearing_cart"][2:4]  # WO-2005
            + built_units["shoulder_asm"][0:1]  # WO-2009
            + built_units["arm"][0:1]           # WO-2012
        )
        contam_bearing_set = set(contam_bearing_units)
        contam_adhesive_set = set(contam_adhesive_units)

        # -- As-built consumption ----------------------------------------- #
        # Pools of serialized sub-assemblies available to be consumed upward.
        pool = {k: list(v) for k, v in built_units.items()}

        def pick_lot(child_key: str, unit: m.AsBuiltSerialRecord) -> m.SupplierLot:
            if child_key == "bearing" and unit in contam_bearing_set:
                return contaminated_bearing
            if child_key == "adhesive" and unit in contam_adhesive_set:
                return contaminated_adhesive
            return RNG.choice(good_lots[child_key])

        # Process built parts in dependency order (leaves before roots) so child
        # serials exist in the pool before a parent consumes them.
        build_order = [pk for (_wo, pk, _q) in WORK_ORDERS]
        seen = set()
        build_order = [pk for pk in build_order if not (pk in seen or seen.add(pk))]

        for part_key in build_order:
            for unit in built_units[part_key]:
                for child_key, qty, _position in BOM.get(part_key, []):
                    bl = bom_line[(part[part_key].id, part[child_key].id)]
                    if child_key in PURCHASED:
                        lot = pick_lot(child_key, unit)
                        session.add(m.AsBuiltComponent(
                            serial_id=unit.id,
                            bom_line_id=bl.id,
                            consumed_supplier_lot_id=lot.id,
                            quantity=Decimal(qty),
                            created_by=SEED_ACTOR,
                        ))
                    else:
                        # Serialized sub-assembly. Consume one from the pool if
                        # this seed batch produced any; base/interface assemblies
                        # are not built here, so those positions stay open.
                        child_pool = pool.get(child_key, [])
                        if not child_pool:
                            continue
                        child_serial = child_pool.pop(0)
                        session.add(m.AsBuiltComponent(
                            serial_id=unit.id,
                            bom_line_id=bl.id,
                            consumed_serial_id=child_serial.id,
                            quantity=Decimal(qty),
                            created_by=SEED_ACTOR,
                        ))

        session.commit()

        print_summary(session, contaminated_bearing, contaminated_adhesive,
                      contam_bearing_units, adhesive_nc)
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Demo summary
# --------------------------------------------------------------------------- #

def ancestor_serials(session, serial_ids: set[int]) -> set[int]:
    """Every serial that transitively consumed any of ``serial_ids`` (backward trace)."""
    found: set[int] = set()
    frontier = list(serial_ids)
    while frontier:
        sid = frontier.pop()
        parents = session.execute(
            select(m.AsBuiltComponent.serial_id)
            .where(m.AsBuiltComponent.consumed_serial_id == sid)
        ).scalars().all()
        for pid in parents:
            if pid not in found:
                found.add(pid)
                frontier.append(pid)
    return found


def print_summary(session, contaminated_bearing, contaminated_adhesive,
                  contam_bearing_units, adhesive_nc) -> None:
    def serials_for_lot(lot):
        rows = session.execute(
            select(m.AsBuiltSerialRecord, m.WorkOrder.work_order_number)
            .join(m.AsBuiltComponent, m.AsBuiltComponent.serial_id == m.AsBuiltSerialRecord.id)
            .join(m.WorkOrder, m.WorkOrder.id == m.AsBuiltSerialRecord.work_order_id)
            .where(m.AsBuiltComponent.consumed_supplier_lot_id == lot.id)
            .order_by(m.AsBuiltSerialRecord.serial_number)
        ).all()
        return rows

    totals = {
        "parts": session.scalar(select(func.count(m.Part.id))),
        "supplier lots": session.scalar(select(func.count(m.SupplierLot.id))),
        "work orders": session.scalar(select(func.count(m.WorkOrder.id))),
        "as-built units": session.scalar(select(func.count(m.AsBuiltSerialRecord.id))),
        "as-built components": session.scalar(select(func.count(m.AsBuiltComponent.id))),
    }
    suppliers = session.scalar(
        select(func.count(m.SupplierLot.supplier_name.distinct()))
    )

    print("\n" + "=" * 70)
    print("qmstrace demo database rebuilt")
    print("=" * 70)
    for label, n in totals.items():
        print(f"  {label:<22}: {n}")
    print(f"  {'suppliers':<22}: {suppliers}")

    # --- Contaminated bearing ---
    bearing_rows = serials_for_lot(contaminated_bearing)
    direct_ids = {r[0].id for r in bearing_rows}
    arm_part_id = session.scalar(select(m.Part.id).where(m.Part.part_number == "SRA-1000"))
    downstream = ancestor_serials(session, direct_ids)
    downstream_arms = session.execute(
        select(m.AsBuiltSerialRecord.serial_number)
        .where(m.AsBuiltSerialRecord.id.in_(downstream or {-1}))
        .where(m.AsBuiltSerialRecord.part_id == arm_part_id)
        .order_by(m.AsBuiltSerialRecord.serial_number)
    ).scalars().all()

    print("\n" + "-" * 70)
    print("CONTAMINATED BEARING LOT  (failed incoming inspection, used anyway)")
    print("-" * 70)
    print(f"  lot number   : {contaminated_bearing.lot_number}")
    print(f"  supplier     : {contaminated_bearing.supplier_name}")
    print(f"  inspection   : REJECTED at incoming")
    print(f"  consumed into: {len(bearing_rows)} built units")
    print("  affected serials (direct consumers):")
    for rec, wo_no in bearing_rows:
        print(f"      {rec.serial_number}  ({wo_no})")
    print("  downstream finished arms (backward trace to SRA-1000):")
    for sn in downstream_arms:
        print(f"      {sn}")

    # --- Contaminated adhesive ---
    adhesive_rows = serials_for_lot(contaminated_adhesive)
    spanned_wos = sorted({wo for _rec, wo in adhesive_rows})
    print("\n" + "-" * 70)
    print("CONTAMINATED ADHESIVE LOT  (open nonconformance, multiple work orders)")
    print("-" * 70)
    print(f"  lot number   : {contaminated_adhesive.lot_number}")
    print(f"  supplier     : {contaminated_adhesive.supplier_name}")
    print(f"  nonconformance: {adhesive_nc.nc_number} (status: {adhesive_nc.status.value})")
    print(f"  consumed into: {len(adhesive_rows)} built units across "
          f"{len(spanned_wos)} work orders {spanned_wos}")
    print("  a few affected serials:")
    for rec, wo_no in adhesive_rows[:6]:
        print(f"      {rec.serial_number}  ({wo_no})")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    reset_database()
    seed()
