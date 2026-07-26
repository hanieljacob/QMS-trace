"""Model package.

Importing this package registers every table on ``Base.metadata`` — Alembic and
``create_all`` both rely on that side effect.
"""

from __future__ import annotations

from app.models.audit import AuditEvent
from app.models.enums import (
    AuditAction,
    InspectionDisposition,
    NonconformanceStatus,
    PartType,
    WorkOrderStatus,
)
from app.models.nonconformance import Nonconformance
from app.models.part import BomLine, Part
from app.models.serial import AsBuiltComponent, AsBuiltSerialRecord
from app.models.signature import ElectronicSignature
from app.models.supplier_lot import (
    CertificateOfConformance,
    IncomingInspection,
    SupplierLot,
)
from app.models.work_order import WorkOrder

__all__ = [
    "AsBuiltComponent",
    "AsBuiltSerialRecord",
    "AuditAction",
    "AuditEvent",
    "BomLine",
    "CertificateOfConformance",
    "ElectronicSignature",
    "IncomingInspection",
    "Nonconformance",
    "NonconformanceStatus",
    "Part",
    "PartType",
    "InspectionDisposition",
    "SupplierLot",
    "WorkOrder",
    "WorkOrderStatus",
]
