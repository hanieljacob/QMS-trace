"""Supplier-lot endpoints: search, recall scope, and the full lot report."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.views import LotReport, LotSummary, RecallScope
from app.services import queries
from app.services.genealogy import lot_where_used

router = APIRouter(tags=["lots"])


@router.get(
    "/lots",
    response_model=list[LotSummary],
    summary="Search supplier lots",
    description=(
        "Find supplier lots by lot number, supplier, or part. Each result carries "
        "quality flags — latest incoming inspection disposition, whether a "
        "certificate of conformance is on file, and how many open nonconformances "
        "it has — so a bad lot stands out before you open it."
    ),
)
def search_lots(
    q: Optional[str] = Query(None, description="Free-text match on lot number, supplier, or part."),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[LotSummary]:
    return [LotSummary.from_hit(h) for h in queries.search_lots(db, q, limit)]


@router.get(
    "/lots/{lot_number}/report",
    response_model=LotReport,
    summary="Full lot report — blast radius, consuming units, and quality context",
    description=(
        "Everything the lot view needs in one call: the lot's incoming inspection "
        "results, certificate of conformance status, and nonconformances, the "
        "blast radius (how many units consumed it at any depth), and every "
        "consuming unit grouped by work order with build date and current status."
    ),
)
def get_lot_report(lot_number: str, db: Session = Depends(get_db)) -> LotReport:
    try:
        report = queries.lot_report(db, lot_number)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"lot number not found: {lot_number}")
    return LotReport.from_report(report)


@router.get(
    "/lots/{lot_number}/recall-scope",
    response_model=RecallScope,
    summary="Recall scope for a supplier lot",
    description=(
        "Given a supplier lot, return every serial that consumed it at any depth "
        "in the bill of materials — the blast radius for a recall — including the "
        "affected finished devices and each unit's depth below consumption."
    ),
)
def get_recall_scope(lot_number: str, db: Session = Depends(get_db)) -> RecallScope:
    try:
        usage = lot_where_used(db, lot_number)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"lot number not found: {lot_number}")
    return RecallScope.from_usage(usage)
