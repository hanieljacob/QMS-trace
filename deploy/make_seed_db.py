"""Produce the pre-seeded SQLite database bundled into the Lambda package.

Runs the deterministic seed, then signs one incoming inspection so the shipped
demo shows a real, verifiable electronic signature (the app's sign-off endpoint
still works on Lambda, but only within a warm container, so we bake one in).

    python deploy/make_seed_db.py <output_path>

Must be run from the backend/ directory (so seed paths resolve).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Ensure backend/ is importable regardless of where this script lives.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

# Import the seed module (it chdirs to backend/ and rebuilds ./qmstrace.db).
import scripts.seed as seed  # noqa: E402


def main(output_path: str) -> None:
    seed.reset_database()
    seed.seed()

    from sqlalchemy import select

    from app.database import SessionLocal
    import app.models as m
    from app.services import esignature
    from app.services.audit import audit_context

    session = SessionLocal()
    try:
        lot = session.scalar(
            select(m.SupplierLot).where(m.SupplierLot.lot_number == "CMP610-NBA-02")
        )
        inspection = session.scalar(
            select(m.IncomingInspection).where(
                m.IncomingInspection.supplier_lot_id == lot.id
            )
        )
        with audit_context(session, actor="Dr. Rao"):
            esignature.sign_inspection(
                session, inspection,
                signer_name="Dr. Rao",
                meaning="Reviewed rejection; dispositioned use-as-is under NC",
            )
            session.commit()
    finally:
        session.close()

    built_db = Path("qmstrace.db")  # created by seed in the backend/ cwd
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(built_db, out)
    print(f"seed database written to {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
