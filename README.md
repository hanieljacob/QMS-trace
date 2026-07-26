# qmstrace

A traceability and device history system for a small medical device
manufacturer. It exists to answer two questions quickly and defensibly.

**1. Given a serial number, what is inside this unit?**
Every part, supplier lot, work order, incoming inspection, certificate, and
nonconformance that went into building it, down through every level of the
bill of materials.

**2. Given a supplier lot, which units consumed it?**
Every serial that used material from that lot, at any depth, so you can scope a
recall.

At a small device company these are usually days of spreadsheet work. The
records that answer them are scattered: paper travelers on the shop floor,
certificate-of-conformance binders from suppliers, incoming-inspection logs, and
a handful of disconnected spreadsheets for the bill of materials and work
orders. Answering "what is in serial X" means walking a multi-level BOM by hand
and cross-referencing lot numbers across several documents. Answering "where did
lot Y go" is worse, it is the same walk in reverse, for every unit that might
have touched the lot, and getting it wrong during a recall means either shipping
suspect product or scrapping good product. qmstrace turns both into a single
lookup that returns a complete, audit-ready answer.

## What it is

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 over SQLite, Alembic migrations.
- Frontend: React, Vite, TypeScript.
- PDF export: ReportLab.
- One seeded, deterministic demo dataset: 26 parts across a four-level BOM, 40
  supplier lots from 8 suppliers, 12 work orders, 60 as-built units.

The dataset is seeded with two planted problems so the traceability actually has
something to find (see the demo path).

## Demo path

Use these exact values against the seeded dataset.

**Forward trace, serial to build history.**
Search the serial `SRA-0001` (a finished Surgical Robot Arm). Its build history
opens as an expandable tree by BOM level. Two problems are flagged inline
without expanding anything:

- The precision-bearing lot `CMP610-NBA-02` (Nordic Bearings AB) is marked
  FAILED INSPECTION and NO CoC. It failed incoming inspection and was consumed
  into the build anyway.
- The structural-adhesive lot `CMP660-TBA-02` (ThermoBond Adhesives) is marked
  OPEN NC.

Use "Download Device History Record (PDF)" to get the auditor-facing document
for this unit.

**Backward trace, lot to recall scope.**
Switch the search to Lot and open `CMP610-NBA-02`. The blast radius is the
headline number: 16 units affected, 9 of them direct consumers, and two finished
devices reached, `SRA-0001` and `SRA-0002`. The nine direct consumers are
`SMM-0001` through `SMM-0005`, `HDG-0001`, `HDG-0002`, `BCG-0001`, and
`BCG-0002`. Every row links back to that unit's own build history.

Then open lot `CMP660-TBA-02`. It carries open nonconformance `NC-1001` and was
consumed across four work orders (`WO-2004`, `WO-2005`, `WO-2009`, `WO-2012`),
affecting 10 units including both finished arms.

**Audit trail and sign-off (API).**
Signing an inspection and reading an audit trail are API operations (there is no
UI for them yet):

    # Electronically sign off an incoming inspection
    curl -X POST .../inspections/1/signoff \
      -H 'content-type: application/json' \
      -d '{"signer_name":"Dr. Rao","meaning":"Performed and approved incoming inspection"}'

    # Read the append-only audit trail for any record
    curl .../audit/supplier_lot/14

## Traceability model

The two queries are served by one traversal each, kept as pure functions over a
database session (`backend/app/services/genealogy.py`):

- `serial_genealogy` walks down the as-built tree.
- `lot_where_used` walks up from a lot to every consuming serial.

The bill of materials nests by recursion (a part that is a component on one line
is the parent of its own lines), so depth is not capped. An as-built component
records what was actually consumed at each position, either a supplier lot or a
serialized sub-assembly, enforced as exactly one by a database check constraint.
That is what lets the trace follow a unit through every level and back up.

Both traversals bulk-load their subtree in a fixed handful of queries rather than
one query per node, so a deep unit costs the same few round trips as a shallow
one.

## Audit trail and electronic signatures

The audit trail is enforced at the SQLAlchemy session level
(`backend/app/services/audit.py`), not by asking callers to remember to log
things. A `before_flush` listener inspects every pending write and an
`after_flush` listener records it, so no code path can bypass it.

- Every insert and update writes one append-only `audit_event` row per changed
  field: table, record id, field, old value, new value, actor, timestamp, and a
  reason for change that is required on updates. An update with no reason is refused.
- Nothing is hard-deleted. Deletion is a soft-void state, and voiding is itself
  an audited update. Audit rows and signatures are immutable; the session refuses
  to modify them.

Electronic signatures (`backend/app/services/esignature.py`) capture the signer,
the meaning of the signature, the timestamp, and a SHA-256 hash over the signed
record's content. Verifying recomputes the hash, so any later change to the
record, even one made with raw SQL that bypassed the ORM, is detectable, and a
signed inspection is locked against modification through the ORM. This
implements the record-level half of 21 CFR Part 11 (audit trail, reason for
change, no obscuring of prior values, signature manifestation and record
linking); the mapping and its gaps are written up in
`backend/docs/audit-and-part-11.md`.

## Running it locally

Backend:

    cd backend
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python scripts/seed.py        # rebuilds and seeds the demo database
    .venv/bin/uvicorn app.main:app --port 8000

Frontend (proxies /api to the backend):

    cd frontend
    npm install
    npm run dev                             # http://localhost:5173

Interactive API docs are at `http://localhost:8000/docs`.

## Tests

    cd backend
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest

The suite (29 tests) asserts exact recall counts against the seeded contaminated
lots, proves an update cannot land without an audit event or a reason, proves a
signed inspection cannot be silently modified, exercises the API endpoints, and
checks that the generated Device History Record is a valid PDF. Genealogy
traversals are tested for cycle and orphan-reference handling.

## Deployment

Live demo: https://bshhrmvk8k.execute-api.us-east-1.amazonaws.com/

Deployed as a single AWS Lambda that serves both the API (mounted under `/api`)
and the built SPA (static files at `/`); the pre-seeded SQLite database is copied
to `/tmp` at cold start. Reads are always correct; writes (sign-off, audit)
persist only for a warm container's lifetime, which is why one signed inspection
is baked into the seed.

The public front door is an API Gateway HTTP API, which invokes the function
through the standard Invoke API. (The cheaper Lambda Function URL, direct or
behind CloudFront, was blocked by an account-level restriction on external
Function URL invocation, `deploy/deploy_lambda.sh` and `deploy/deploy_cloudfront.sh`
remain for accounts without that restriction.) Cost is within free-tier for demo
traffic: Lambda is always-free at this volume, and API Gateway HTTP API is free
for 1M requests/month for the first 12 months, then about \$1 per million.

    ./deploy/build_lambda.sh        # build the zip (Linux wheels + app + SPA + db)
    ./deploy/deploy_lambda.sh       # create/update the Lambda function
    ./deploy/deploy_apigateway.sh   # put a public API Gateway URL in front of it
    ./deploy/teardown.sh            # delete everything so nothing can accrue charges

## Deliberately out of scope

There is no authentication, authorization, or multi-tenancy, and that is the
first thing a real deployment would add, the audit "actor" is currently a
caller-supplied string rather than a verified identity, which is the single
biggest gap against a production quality system. This was left out on purpose to
keep the project focused on the traceability engine and the record-integrity
model rather than on user management, and for the same reason the dependency
list is kept small, the device history record is derived on demand rather than
stored, audit enforcement covers the ORM rather than arbitrary raw SQL (which is
why signatures also carry an independent integrity hash), and there is no CI,
metrics, or infrastructure hardening. None of these are hard to add; they are
just not what this project is trying to demonstrate.
