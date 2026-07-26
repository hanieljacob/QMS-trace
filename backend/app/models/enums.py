"""Controlled vocabularies for status and type columns.

Rendered as portable ``VARCHAR`` + ``CHECK`` constraints (native_enum=False)
rather than database-native enum types, so SQLite behaves the same as any
future backend.
"""

from __future__ import annotations

import enum


class PartType(str, enum.Enum):
    """What kind of thing a part is."""

    raw_material = "raw_material"
    component = "component"
    finished_device = "finished_device"


class InspectionDisposition(str, enum.Enum):
    """Outcome of an incoming inspection on a supplier lot."""

    pending = "pending"
    accepted = "accepted"
    accepted_with_deviation = "accepted_with_deviation"
    rejected = "rejected"


class WorkOrderStatus(str, enum.Enum):
    """Lifecycle of a work order. ``cancelled`` is a state, not a delete."""

    open = "open"
    in_process = "in_process"
    completed = "completed"
    cancelled = "cancelled"


class NonconformanceStatus(str, enum.Enum):
    """Disposition of a nonconformance."""

    open = "open"
    use_as_is = "use_as_is"
    rework = "rework"
    scrap = "scrap"
    closed = "closed"


class AuditAction(str, enum.Enum):
    """The kind of write an audit event records.

    A soft-void is just an ``update`` that sets the void columns, so there is no
    separate delete/void action — the append-only trail treats it like any other
    field change.
    """

    insert = "insert"
    update = "update"
