"""Electronic signatures over inspection records.

The signature captures *who* signed, the *meaning* of the signature, *when*, and
a SHA-256 hash over the signed record's content. Verifying recomputes the hash
and compares, any later change to the record (even one that bypassed the ORM)
shows up as a mismatch.
"""

from __future__ import annotations

import datetime
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models as m

SIGNED_TABLE = "incoming_inspection"


class AlreadySignedError(RuntimeError):
    """The inspection already carries an electronic signature."""


def compute_inspection_hash(inspection: "m.IncomingInspection") -> str:
    """SHA-256 over the fields an inspection signature attests to.

    Kept explicit (rather than hashing every column) so the signed content is a
    deliberate, documented set rather than an accident of the schema.
    """
    payload = {
        "table": SIGNED_TABLE,
        "record_id": inspection.id,
        "supplier_lot_id": inspection.supplier_lot_id,
        "inspected_at": inspection.inspected_at.isoformat() if inspection.inspected_at else None,
        "disposition": inspection.disposition.value if inspection.disposition else None,
        "result_notes": inspection.result_notes,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sign_inspection(
    session: Session,
    inspection: "m.IncomingInspection",
    signer_name: str,
    meaning: str,
) -> "m.ElectronicSignature":
    """Record an electronic signature over ``inspection``.

    The caller is expected to commit. Once committed, the session layer will
    refuse further modifications to that inspection.
    """
    if inspection.id is None:
        raise ValueError("inspection must be persisted before it can be signed")
    signature = m.ElectronicSignature(
        table_name=SIGNED_TABLE,
        record_id=inspection.id,
        signer_name=signer_name,
        meaning=meaning,
        signed_at=datetime.datetime.now(datetime.timezone.utc),
        record_hash=compute_inspection_hash(inspection),
        created_by=signer_name,
    )
    session.add(signature)
    return signature


def signoff_inspection(
    session: Session,
    inspection_id: int,
    signer_name: str,
    meaning: str,
) -> "m.ElectronicSignature":
    """Look up an inspection and sign it off (no commit, the caller commits).

    Raises ``LookupError`` if the inspection does not exist and
    ``AlreadySignedError`` if it has already been signed.
    """
    inspection = session.get(m.IncomingInspection, inspection_id)
    if inspection is None:
        raise LookupError(f"inspection not found: {inspection_id}")
    if record_is_signed(session, SIGNED_TABLE, inspection_id):
        raise AlreadySignedError(f"inspection {inspection_id} is already signed")
    return sign_inspection(session, inspection, signer_name, meaning)


def latest_signature(session: Session, table_name: str, record_id: int):
    return session.scalar(
        select(m.ElectronicSignature)
        .where(m.ElectronicSignature.table_name == table_name)
        .where(m.ElectronicSignature.record_id == record_id)
        .order_by(m.ElectronicSignature.signed_at.desc(), m.ElectronicSignature.id.desc())
    )


def record_is_signed(session: Session, table_name: str, record_id: int) -> bool:
    if record_id is None:
        return False
    return session.scalar(
        select(m.ElectronicSignature.id)
        .where(m.ElectronicSignature.table_name == table_name)
        .where(m.ElectronicSignature.record_id == record_id)
        .limit(1)
    ) is not None


def verify_inspection_signature(session: Session, inspection: "m.IncomingInspection"):
    """Return True/False if signed (hash matches / not), or None if unsigned."""
    signature = latest_signature(session, SIGNED_TABLE, inspection.id)
    if signature is None:
        return None
    return signature.record_hash == compute_inspection_hash(inspection)
