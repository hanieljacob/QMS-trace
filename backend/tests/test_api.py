"""API tests over the seeded demo database, driving the real FastAPI app."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.models as m
from app.database import SessionLocal
from app.main import app

BACKEND = Path(__file__).resolve().parent.parent

CONTAM_BEARING_LOT = "CMP610-NBA-02"
CONTAM_ADHESIVE_LOT = "CMP660-TBA-02"


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    subprocess.run(
        [sys.executable, "scripts/seed.py"],
        cwd=BACKEND, check=True, capture_output=True,
    )


@pytest.fixture
def client():
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

def test_search_serials(client):
    r = client.get("/serials", params={"q": "SRA-0001"})
    assert r.status_code == 200
    rows = r.json()
    assert any(row["serial_number"] == "SRA-0001" for row in rows)
    hit = next(row for row in rows if row["serial_number"] == "SRA-0001")
    assert hit["part_number"] == "SRA-1000"
    assert hit["work_order_number"]


# --------------------------------------------------------------------------- #
# As-built tree
# --------------------------------------------------------------------------- #

def test_serial_genealogy_tree(client):
    r = client.get("/serials/SRA-0001/genealogy")
    assert r.status_code == 200
    tree = r.json()
    assert tree["part_number"] == "SRA-1000"
    assert len(tree["components"]) == 7

    # The contaminated bearing lot, with its failed inspection, is reachable deep
    # in the tree.
    def find_lot(node, lot_number):
        for comp in node["components"]:
            if comp["kind"] == "lot" and comp["lot"]["lot_number"] == lot_number:
                return comp["lot"]
            if comp["kind"] == "serial" and comp["child"]:
                hit = find_lot(comp["child"], lot_number)
                if hit:
                    return hit
        return None

    lot = find_lot(tree, CONTAM_BEARING_LOT)
    assert lot is not None
    assert lot["inspection_disposition"] == "rejected"
    assert lot["certificate_status"] == "absent"


def test_serial_genealogy_404(client):
    r = client.get("/serials/NOPE-9999/genealogy")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Recall scope
# --------------------------------------------------------------------------- #

def test_recall_scope_bearing(client):
    r = client.get(f"/lots/{CONTAM_BEARING_LOT}/recall-scope")
    assert r.status_code == 200
    scope = r.json()
    assert scope["supplier_name"] == "Nordic Bearings AB"
    assert scope["total_affected"] == 16
    assert scope["direct_consumers"] == 9
    assert scope["finished_devices"] == ["SRA-0001", "SRA-0002"]
    assert len(scope["affected_serials"]) == 16


def test_recall_scope_404(client):
    r = client.get("/lots/NOPE/recall-scope")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Nonconformances
# --------------------------------------------------------------------------- #

def test_list_nonconformances_open(client):
    r = client.get("/nonconformances", params={"status": "open"})
    assert r.status_code == 200
    rows = r.json()
    assert any(row["nc_number"] == "NC-1001" for row in rows)
    nc = next(row for row in rows if row["nc_number"] == "NC-1001")
    assert nc["subject_type"] == "supplier_lot"
    assert nc["subject_reference"] == CONTAM_ADHESIVE_LOT
    assert nc["status"] == "open"


# --------------------------------------------------------------------------- #
# Sign-off
# --------------------------------------------------------------------------- #

def _an_inspection_id() -> int:
    s = SessionLocal()
    try:
        return s.scalar(select(m.IncomingInspection.id).order_by(m.IncomingInspection.id).limit(1))
    finally:
        s.close()


def test_inspection_signoff_and_conflict(client):
    inspection_id = _an_inspection_id()
    body = {"signer_name": "Dr. Rao", "meaning": "Performed and approved incoming inspection"}

    r = client.post(f"/inspections/{inspection_id}/signoff", json=body)
    assert r.status_code == 201
    receipt = r.json()
    assert receipt["signer_name"] == "Dr. Rao"
    assert receipt["verified"] is True
    assert len(receipt["record_hash"]) == 64

    # Signing again is a conflict.
    r2 = client.post(f"/inspections/{inspection_id}/signoff", json=body)
    assert r2.status_code == 409


def test_signoff_missing_inspection(client):
    r = client.post("/inspections/999999/signoff",
                    json={"signer_name": "x", "meaning": "y"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Audit trail
# --------------------------------------------------------------------------- #

def test_read_audit_trail(client):
    s = SessionLocal()
    try:
        part_id = s.scalar(select(m.Part.id).where(m.Part.part_number == "SRA-1000"))
    finally:
        s.close()

    r = client.get(f"/audit/part/{part_id}")
    assert r.status_code == 200
    entries = r.json()
    assert entries, "expected audit entries for the finished-device part"
    assert all(e["action"] == "insert" for e in entries)
    pn = next(e for e in entries if e["field"] == "part_number")
    assert pn["new_value"] == "SRA-1000"
    assert pn["old_value"] is None
    assert pn["actor"] == "seed"
