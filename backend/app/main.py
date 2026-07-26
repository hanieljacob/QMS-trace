"""qmstrace API.

A thin FastAPI surface over the traceability engine. All business logic lives in
``app.services`` (genealogy traversals, audit/immutability, electronic
signatures, list queries); the route handlers only translate HTTP to those
calls and shape responses for the frontend views.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.routers import audit, inspections, lots, nonconformances, serials

app = FastAPI(
    title="qmstrace API",
    version="0.1.0",
    description=(
        "Traceability and device history for a small medical device "
        "manufacturer. The system answers two questions: given a serial number, "
        "return its full build history; given a supplier lot, return every serial "
        "that consumed it."
    ),
)

app.include_router(serials.router)
app.include_router(lots.router)
app.include_router(nonconformances.router)
app.include_router(inspections.router)
app.include_router(audit.router)


@app.get("/health", tags=["meta"], summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}
