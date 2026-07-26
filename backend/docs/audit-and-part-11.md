# Audit trail, electronic signatures, and 21 CFR Part 11

This project keeps an append-only audit trail of every change and supports
electronic signatures on inspection sign-off. This note explains how those
features line up with FDA **21 CFR Part 11** (electronic records / electronic
signatures), and, just as importantly, where this demo deliberately does *not*
meet Part 11 so no one mistakes it for a validated system.

## How it works, in one paragraph

Audit and immutability are enforced at the SQLAlchemy **session** level
(`app/services/audit.py`), not by convention. A `before_flush` listener blocks
hard deletes, blocks changes to append-only records (audit events, signatures)
and to signed inspections, and refuses any update that lacks a reason for
change. An `after_flush` listener then writes one `audit_event` row per changed
field, table, record id, field, old value, new value, actor, timestamp, and
(on updates) the reason. Because this lives on the session, no application code
can forget to call it. Electronic signatures (`app/services/esignature.py`)
store the signer, the meaning of the signature, the time, and a SHA-256 hash
over the signed record; verifying recomputes the hash, so any later change,
even one made with raw SQL, breaks the signature.

## Mapping to Part 11 expectations

| Part 11 clause | Expectation | How qmstrace addresses it |
|---|---|---|
| **§11.10(e)** | Computer-generated, time-stamped audit trails for record create/modify actions; changes must not obscure prior values; retain the trail. | `audit_event` is generated automatically at the session level, timestamped, with `old_value` **and** `new_value` (prior values preserved, never overwritten). Rows are append-only. |
| **§11.10(e)** | Reason for change recorded on modifications. | Updates are rejected unless a reason is supplied (`audit_context(..., reason=...)`); the reason is stored on every update audit row. |
| **§11.10(c)** | Protection of records to enable accurate retrieval throughout retention. | No hard deletes anywhere, deletion is a soft-void *state* and is itself an audited update. Audit and signature rows cannot be modified. |
| **§11.10(a)** | Validation of systems to ensure accuracy and reliability. | Behavior is pinned by tests: an update cannot land without an audit event or without a reason; a signed inspection cannot be silently modified (`tests/test_audit.py`). |
| **§11.10(b)** | Ability to generate accurate, complete copies of records. | The genealogy traversals assemble the full device history record for a serial and the complete where-used list for a lot (`app/services/genealogy.py`). |
| **§11.50** | Signed records show the signer's name, the date/time, and the meaning of the signature. | `electronic_signature` stores `signer_name`, `signed_at`, and `meaning`. |
| **§11.70** | Signatures are linked to their records so they cannot be excised, copied, or transferred to falsify. | The signature stores a SHA-256 hash over the signed record's content; if the record changes, `verify_inspection_signature` returns `False`. The signed record is also locked against further edits through the ORM. |

## What this demo does NOT provide (honest gaps)

This is a demonstration app, not a compliant QMS. Notably:

- **No authentication, access control, or unique user identities** (§11.10(d),
  (g); §11.100; §11.300). By design this project has no auth (see `CLAUDE.md`).
  The audit **actor** is a free-text label, not an authenticated, uniquely
  attributable identity, and signatures are not bound to a verified login or a
  second authentication factor. This is the single biggest gap.
- **Enforcement covers the ORM unit of work, not raw SQL.** A deliberate Core
  `UPDATE`/`INSERT` bypasses the session listeners (and therefore the audit
  trail). That is exactly why signed records carry an independent integrity
  hash, so tampering below the ORM is still *detectable* even though it is not
  *prevented*. A production system would also restrict database-level write
  access.
- **No operational controls**, training records, SOPs, records retention/
  archival policy, system validation lifecycle, and periodic review are out of
  scope.

In short: the *record-level* Part 11 mechanics (audit trail, reason for change,
no-obscuring-of-history, signature manifestation and record linking) are
implemented and tested; the *identity and access* half of Part 11 is
intentionally absent.
