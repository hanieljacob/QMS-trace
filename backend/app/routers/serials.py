"""Serial-centric endpoints: search, and the full as-built tree."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.reports.dhr_pdf import render_dhr_pdf
from app.schemas.views import SerialSummary, SerialTree, serial_tree
from app.services import queries
from app.services.dhr import build_dhr
from app.services.genealogy import serial_genealogy

router = APIRouter(tags=["serials"])


@router.get(
    "/serials",
    response_model=list[SerialSummary],
    summary="Search as-built serial records",
    description=(
        "Find built units by serial number, part number, part name, or work "
        "order. Each result is one as-built serial record, a physical unit that "
        "was produced against a work order."
    ),
)
def search_serials(
    q: Optional[str] = Query(
        None, description="Free-text match on serial number, part, or work order."
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return."),
    db: Session = Depends(get_db),
) -> list[SerialSummary]:
    return [SerialSummary.from_record(r) for r in queries.search_serials(db, q, limit)]


@router.get(
    "/serials/{serial_number}/genealogy",
    response_model=SerialTree,
    summary="Full as-built tree (device history record) for a serial",
    description=(
        "Return the complete device history record for one serial number: every "
        "component position, the supplier lot consumed there (with its supplier, "
        "certificate of conformance status, incoming inspection result, and any "
        "nonconformance), and, for serialized sub-assemblies, the child unit's "
        "own genealogy, all the way down."
    ),
)
def get_serial_genealogy(
    serial_number: str, db: Session = Depends(get_db)
) -> SerialTree:
    try:
        node = serial_genealogy(db, serial_number)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"serial number not found: {serial_number}")
    return serial_tree(node)


@router.get(
    "/serials/{serial_number}/dhr.pdf",
    summary="Download the Device History Record as a PDF",
    description=(
        "Generate the auditor-facing Device History Record for one serial: a "
        "header (serial, part, work order, build date), the full as-built "
        "genealogy, incoming inspection results with electronic signatures, and "
        "nonconformances, with a generation timestamp and page numbers."
    ),
    responses={200: {"content": {"application/pdf": {}}, "description": "The DHR PDF."}},
    response_class=Response,
)
def download_dhr(serial_number: str, db: Session = Depends(get_db)) -> Response:
    try:
        document = build_dhr(db, serial_number)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"serial number not found: {serial_number}")
    pdf = render_dhr_pdf(document)
    filename = f"DHR_{serial_number}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
