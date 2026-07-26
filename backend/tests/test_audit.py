"""Tests for the append-only audit layer and electronic signatures.

These use isolated in-memory databases (the audit/immutability listeners live on
the ``Session`` class, so they apply to any session). The key proofs:

* an update cannot land without producing an audit event, and cannot land at all
  without a reason;
* an electronically signed inspection cannot be silently modified, the ORM path
  is blocked, and a Core-level tamper is caught by the integrity hash.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

import app.database  # noqa: F401  (ensures the audit listeners are registered)
import app.models as m
from app.services.audit import (
    AuditError,
    ImmutableRecordError,
    SignatureError,
    audit_context,
)
from app.services.esignature import (
    compute_inspection_hash,
    sign_inspection,
    verify_inspection_signature,
)
from app.database import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


# --------------------------------------------------------------------------- #
# Small builders
# --------------------------------------------------------------------------- #

def _make_lot(s) -> m.SupplierLot:
    part = m.Part(part_number="CMP-1", name="Bearing",
                  part_type=m.PartType.raw_material, created_by="seed")
    s.add(part)
    s.flush()
    lot = m.SupplierLot(
        part_id=part.id, lot_number="LOT-1", supplier_name="Acme",
        quantity_received=Decimal("100"), received_at=datetime.date(2026, 1, 1),
        created_by="seed",
    )
    s.add(lot)
    s.commit()
    return lot


def _make_inspection(s, lot) -> m.IncomingInspection:
    insp = m.IncomingInspection(
        supplier_lot_id=lot.id,
        inspected_at=datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
        disposition=m.InspectionDisposition.accepted,
        result_notes="within spec",
        created_by="qa.inspector",
    )
    s.add(insp)
    s.commit()
    return insp


def _audit_rows(s, table, record_id, action=None):
    q = select(m.AuditEvent).where(
        m.AuditEvent.table_name == table, m.AuditEvent.record_id == record_id
    )
    if action is not None:
        q = q.where(m.AuditEvent.action == action)
    return s.scalars(q).all()


# --------------------------------------------------------------------------- #
# Inserts are audited
# --------------------------------------------------------------------------- #

def test_insert_writes_field_level_audit(session):
    lot = _make_lot(session)
    rows = _audit_rows(session, "supplier_lot", lot.id, m.AuditAction.insert)
    fields = {r.field_name: r for r in rows}
    assert fields["lot_number"].new_value == "LOT-1"
    assert fields["supplier_name"].new_value == "Acme"
    assert all(r.old_value is None and r.reason is None for r in rows)
    assert all(r.created_by == "seed" for r in rows)  # actor falls back to created_by


# --------------------------------------------------------------------------- #
# Updates: audited, and impossible without a reason
# --------------------------------------------------------------------------- #

def test_update_writes_audit_event_with_old_new_and_reason(session):
    lot = _make_lot(session)
    with audit_context(session, actor="qa.lopez", reason="recount after receiving"):
        lot.quantity_received = Decimal("240")
        session.commit()

    updates = _audit_rows(session, "supplier_lot", lot.id, m.AuditAction.update)
    assert len(updates) == 1
    row = updates[0]
    assert row.field_name == "quantity_received"
    assert Decimal(row.old_value) == Decimal("100")
    assert Decimal(row.new_value) == Decimal("240")
    assert row.reason == "recount after receiving"
    assert row.created_by == "qa.lopez"


def test_update_without_reason_is_blocked_and_rolls_back(session):
    lot = _make_lot(session)
    # Actor set, but no reason.
    with audit_context(session, actor="qa.lopez"):
        lot.quantity_received = Decimal("240")
        with pytest.raises(AuditError):
            session.commit()
    session.rollback()

    # The change did not land, and no update audit event was written.
    fresh = session.get(m.SupplierLot, lot.id)
    session.refresh(fresh)
    assert fresh.quantity_received == Decimal("100")
    assert _audit_rows(session, "supplier_lot", lot.id, m.AuditAction.update) == []


def test_soft_void_is_an_audited_update(session):
    lot = _make_lot(session)
    with audit_context(session, actor="qa.lopez", reason="duplicate receipt"):
        lot.voided_at = datetime.datetime.now(datetime.timezone.utc)
        lot.voided_by = "qa.lopez"
        lot.void_reason = "duplicate receipt"
        session.commit()
    updates = _audit_rows(session, "supplier_lot", lot.id, m.AuditAction.update)
    changed = {r.field_name for r in updates}
    assert {"voided_at", "voided_by", "void_reason"} <= changed


# --------------------------------------------------------------------------- #
# No hard deletes
# --------------------------------------------------------------------------- #

def test_hard_delete_is_blocked(session):
    lot = _make_lot(session)
    session.delete(lot)
    with pytest.raises(AuditError):
        session.commit()
    session.rollback()
    assert session.get(m.SupplierLot, lot.id) is not None


# --------------------------------------------------------------------------- #
# Audit events are themselves immutable
# --------------------------------------------------------------------------- #

def test_audit_event_cannot_be_modified(session):
    lot = _make_lot(session)
    event_row = _audit_rows(session, "supplier_lot", lot.id)[0]
    with audit_context(session, actor="attacker", reason="cover tracks"):
        event_row.new_value = "tampered"
        with pytest.raises(ImmutableRecordError):
            session.commit()
    session.rollback()


# --------------------------------------------------------------------------- #
# Electronic signatures
# --------------------------------------------------------------------------- #

def test_signing_records_signer_meaning_time_and_hash(session):
    lot = _make_lot(session)
    insp = _make_inspection(session, lot)
    sig = sign_inspection(session, insp, signer_name="Dr. Rao",
                          meaning="Performed and approved incoming inspection")
    session.commit()

    assert sig.signer_name == "Dr. Rao"
    assert sig.meaning == "Performed and approved incoming inspection"
    assert sig.signed_at is not None
    assert sig.record_hash == compute_inspection_hash(insp)
    assert verify_inspection_signature(session, insp) is True


def test_signed_inspection_cannot_be_modified_via_orm(session):
    lot = _make_lot(session)
    insp = _make_inspection(session, lot)
    sign_inspection(session, insp, signer_name="Dr. Rao", meaning="approved")
    session.commit()

    with audit_context(session, actor="someone", reason="change my mind"):
        insp.disposition = m.InspectionDisposition.rejected
        with pytest.raises(SignatureError):
            session.commit()
    session.rollback()

    fresh = session.get(m.IncomingInspection, insp.id)
    session.refresh(fresh)
    assert fresh.disposition == m.InspectionDisposition.accepted


def test_tampering_below_the_orm_is_caught_by_the_hash(session):
    lot = _make_lot(session)
    insp = _make_inspection(session, lot)
    sign_inspection(session, insp, signer_name="Dr. Rao", meaning="approved")
    session.commit()
    assert verify_inspection_signature(session, insp) is True

    # Tamper via a raw Core UPDATE, bypassing the ORM (and its guards).
    session.execute(
        text("UPDATE incoming_inspection SET disposition = :d WHERE id = :i"),
        {"d": m.InspectionDisposition.rejected.value, "i": insp.id},
    )
    session.commit()
    session.expire_all()

    # The signature no longer matches the record: tampering is detectable.
    tampered = session.get(m.IncomingInspection, insp.id)
    assert tampered.disposition == m.InspectionDisposition.rejected
    assert verify_inspection_signature(session, tampered) is False
