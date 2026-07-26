"""Session-level, unbypassable audit + immutability enforcement.

This wires two ``Session`` events so that the audit trail and record
immutability are properties of *the session itself*, not of remembering to call
a helper:

* ``before_flush`` — inspects everything about to be written. It blocks hard
  deletes, blocks modification of append-only records (audit events, signatures)
  and of signed inspections, and requires a reason on every update. It captures
  the field-level changes.
* ``after_flush`` — once primary keys are assigned, it writes one append-only
  ``audit_event`` row per changed field, via a Core insert (which does not
  re-enter the ORM unit of work, so there is no recursion).

Actor and reason travel on ``session.info`` (see :func:`audit_context`):

    with audit_context(session, actor="qa.lopez", reason="corrected lot qty"):
        lot.quantity_received = Decimal("240")
        session.commit()

Inserts do not require a reason; their actor falls back to the row's own
``created_by`` if none is set on the session.

Known boundary: this covers the ORM unit of work. A deliberate Core
``UPDATE``/``INSERT`` statement bypasses these events — which is exactly why
signed records also carry an independent integrity hash (see
``app.services.esignature``).
"""

from __future__ import annotations

import datetime
import enum
from contextlib import contextmanager

from sqlalchemy import event, inspect
from sqlalchemy.orm import Mapper, Session
from sqlalchemy.orm.attributes import get_history

import app.models as m
from app.services.esignature import SIGNED_TABLE, record_is_signed


class AuditError(RuntimeError):
    """A write violates an audit/immutability rule and must not land."""


class ImmutableRecordError(AuditError):
    """An append-only record was modified or deleted."""


class SignatureError(AuditError):
    """A signed record was modified."""


# --------------------------------------------------------------------------- #
# Context: who is making the change, and why
# --------------------------------------------------------------------------- #

@contextmanager
def audit_context(session: Session, actor: str, reason: str | None = None):
    """Attach an actor (and, for updates, a reason) to a unit of work."""
    prev_actor = session.info.get("audit_actor")
    prev_reason = session.info.get("audit_reason")
    session.info["audit_actor"] = actor
    session.info["audit_reason"] = reason
    try:
        yield session
    finally:
        session.info["audit_actor"] = prev_actor
        session.info["audit_reason"] = prev_reason


def _actor_for(session: Session, obj) -> str | None:
    return session.info.get("audit_actor") or getattr(obj, "created_by", None)


def _reason_for(session: Session, obj) -> str | None:
    return getattr(obj, "_audit_reason", None) or session.info.get("audit_reason")


# --------------------------------------------------------------------------- #
# Value serialization
# --------------------------------------------------------------------------- #

def _to_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def _pk(obj) -> int | None:
    return getattr(obj, "id", None)


def _collect_changes(obj):
    """Return [(field, old, new), ...] for the changed columns of ``obj``.

    ``get_history`` with the default ``PASSIVE_OFF`` loads the committed value
    when needed, so the *old* value is captured even for an attribute that was
    expired (e.g. after a prior commit) before being reassigned.
    """
    state = inspect(obj)
    changes = []
    for attr in state.mapper.column_attrs:
        history = get_history(obj, attr.key)
        if history.has_changes():
            old = history.deleted[0] if history.deleted else None
            new = history.added[0] if history.added else None
            changes.append((attr.key, old, new))
    return changes


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #

def _guard_immutable(session: Session, obj) -> None:
    if isinstance(obj, (m.AuditEvent, m.ElectronicSignature)):
        raise ImmutableRecordError(
            f"{obj.__tablename__} rows are append-only and cannot be modified"
        )
    if isinstance(obj, m.IncomingInspection) and record_is_signed(
        session, SIGNED_TABLE, _pk(obj)
    ):
        raise SignatureError(
            f"incoming_inspection {_pk(obj)} is electronically signed and "
            f"cannot be modified"
        )


# --------------------------------------------------------------------------- #
# Session events
# --------------------------------------------------------------------------- #

def _before_flush(session: Session, flush_context, instances) -> None:
    # No hard deletes anywhere — records are voided, never removed.
    if session.deleted:
        names = ", ".join(sorted({o.__tablename__ for o in session.deleted}))
        raise AuditError(
            f"hard deletes are not permitted (attempted on: {names}); "
            f"void the record instead"
        )

    pending_updates = []
    for obj in session.dirty:
        if not session.is_modified(obj, include_collections=False):
            continue
        _guard_immutable(session, obj)
        changes = _collect_changes(obj)
        if not changes:
            continue
        reason = _reason_for(session, obj)
        if not reason:
            raise AuditError(
                f"update to {obj.__tablename__} (id={_pk(obj)}) requires a "
                f"reason for change"
            )
        pending_updates.append((obj, changes, reason, _actor_for(session, obj)))

    pending_inserts = list(session.new)
    session.info["_pending_audit"] = (pending_inserts, pending_updates)


def _after_flush(session: Session, flush_context) -> None:
    pending = session.info.pop("_pending_audit", None)
    if not pending:
        return
    inserts, updates = pending
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = []

    for obj in inserts:
        table = obj.__tablename__
        rid = _pk(obj)
        actor = _actor_for(session, obj)
        for column in inspect(obj).mapper.columns:
            rows.append({
                "table_name": table,
                "record_id": rid,
                "action": m.AuditAction.insert,
                "field_name": column.key,
                "old_value": None,
                "new_value": _to_text(getattr(obj, column.key)),
                "reason": None,
                "created_at": now,
                "created_by": actor,
            })

    for obj, changes, reason, actor in updates:
        table = obj.__tablename__
        rid = _pk(obj)
        for field, old, new in changes:
            rows.append({
                "table_name": table,
                "record_id": rid,
                "action": m.AuditAction.update,
                "field_name": field,
                "old_value": _to_text(old),
                "new_value": _to_text(new),
                "reason": reason,
                "created_at": now,
                "created_by": actor,
            })

    if rows:
        # Core insert: append-only, and it does not re-enter the ORM flush.
        session.execute(m.AuditEvent.__table__.insert(), rows)


def _enable_active_history(*_args) -> None:
    """Make every column remember its previous value when reassigned.

    Without this, SQLAlchemy discards the committed value on assignment (unless
    it happens to be loaded), and the audit trail would record ``old_value`` as
    null. This runs on the ``after_configured`` mapper event — after all models
    are imported and configured, but before the first attribute assignment on a
    loaded object — which is where ``active_history`` has to be in place.
    """
    for mapper in m.AuditEvent.registry.mappers:
        class_manager = mapper.class_manager
        for attr in mapper.column_attrs:
            class_manager[attr.key].impl.active_history = True


_REGISTERED = False


def register() -> None:
    """Install the audit/immutability listeners on every ``Session`` (idempotent).

    Safe to call at import time: nothing here touches model classes eagerly —
    ``_enable_active_history`` runs later, on ``after_configured``.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Mapper, "after_configured", _enable_active_history, once=True)
    _REGISTERED = True
