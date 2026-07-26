"""Nonconformance listing."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.enums import NonconformanceStatus
from app.schemas.views import NonconformanceListItem
from app.services import queries

router = APIRouter(tags=["nonconformances"])


@router.get(
    "/nonconformances",
    response_model=list[NonconformanceListItem],
    summary="List nonconformances",
    description=(
        "List recorded nonconformances — deviations raised against a supplier lot "
        "or a single serial — with the subject resolved to its lot or serial "
        "number. Optionally filter by disposition status."
    ),
)
def list_nonconformances(
    status: Optional[NonconformanceStatus] = Query(
        None, description="Filter by disposition, e.g. 'open', 'use_as_is', 'closed'."
    ),
    db: Session = Depends(get_db),
) -> list[NonconformanceListItem]:
    return [
        NonconformanceListItem.from_nc(nc)
        for nc in queries.list_nonconformances(db, status)
    ]
