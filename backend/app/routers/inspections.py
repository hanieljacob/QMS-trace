"""Incoming-inspection endpoints: electronic sign-off."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import IncomingInspection
from app.schemas.views import SignatureReceipt, SignoffRequest
from app.services import esignature
from app.services.audit import audit_context

router = APIRouter(tags=["inspections"])


@router.post(
    "/inspections/{inspection_id}/signoff",
    response_model=SignatureReceipt,
    status_code=201,
    summary="Electronically sign off an incoming inspection",
    description=(
        "Record an electronic signature over an incoming inspection: the signer's "
        "name, the meaning of the signature, the time, and a hash over the signed "
        "record. Once signed, the inspection is locked against modification."
    ),
)
def signoff_inspection(
    inspection_id: int, body: SignoffRequest, db: Session = Depends(get_db)
) -> SignatureReceipt:
    try:
        with audit_context(db, actor=body.signer_name):
            signature = esignature.signoff_inspection(
                db, inspection_id, body.signer_name, body.meaning
            )
            db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail=f"inspection not found: {inspection_id}")
    except esignature.AlreadySignedError:
        raise HTTPException(status_code=409, detail=f"inspection {inspection_id} is already signed")

    inspection = db.get(IncomingInspection, inspection_id)
    return SignatureReceipt(
        inspection_id=inspection_id,
        signer_name=signature.signer_name,
        meaning=signature.meaning,
        signed_at=signature.signed_at,
        record_hash=signature.record_hash,
        verified=esignature.verify_inspection_signature(db, inspection),
    )
