"""Audit-trail read endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.views import AuditEntry
from app.services import queries

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/{table_name}/{record_id}",
    response_model=list[AuditEntry],
    summary="Read the audit trail for any record",
    description=(
        "Return the complete append-only audit trail for one record, oldest "
        "change first: every field-level insert and update with its old and new "
        "value, the actor, the timestamp, and, for updates, the reason for "
        "change. `table_name` is the record's table (e.g. 'supplier_lot', "
        "'incoming_inspection') and `record_id` its primary key."
    ),
)
def read_audit_trail(
    table_name: str, record_id: int, db: Session = Depends(get_db)
) -> list[AuditEntry]:
    return [AuditEntry.from_event(e) for e in queries.get_audit_trail(db, table_name, record_id)]
