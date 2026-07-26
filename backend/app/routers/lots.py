"""Supplier-lot endpoints: recall scope."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.views import RecallScope
from app.services.genealogy import lot_where_used

router = APIRouter(tags=["lots"])


@router.get(
    "/lots/{lot_number}/recall-scope",
    response_model=RecallScope,
    summary="Recall scope for a supplier lot",
    description=(
        "Given a supplier lot, return every serial that consumed it at any depth "
        "in the bill of materials — the blast radius for a recall. Includes the "
        "affected finished devices, direct consumers, and each affected unit's "
        "depth below the point of consumption."
    ),
)
def get_recall_scope(lot_number: str, db: Session = Depends(get_db)) -> RecallScope:
    try:
        usage = lot_where_used(db, lot_number)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"lot number not found: {lot_number}")
    return RecallScope.from_usage(usage)
