"""Electronic signatures.

An electronic signature binds a signer, the meaning of their signing, and a
timestamp to a specific record, together with a hash taken over that record's
content at the moment of signing. If the underlying record is later changed, the
stored hash no longer matches, the signature is broken and the tampering is
detectable.

Like the audit trail, signatures are append-only: no ``SoftVoidMixin``, and the
session layer refuses to update them.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
import datetime

from app.database import Base
from app.models.base import TimestampMixin


class ElectronicSignature(TimestampMixin, Base):
    """A signer's attestation over one record, with an integrity hash."""

    __tablename__ = "electronic_signature"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The record that was signed (generic reference, e.g. "incoming_inspection").
    table_name: Mapped[str] = mapped_column(String(80), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Why the signer signed, e.g. "Performed and approved incoming inspection".
    meaning: Mapped[str] = mapped_column(String(200), nullable=False)
    signed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # SHA-256 hex digest over the signed record's content at signing time.
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
