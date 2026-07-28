# qmstrace

A traceability and device history system for a small medical device
manufacturer. Demo application.

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy over SQLite
- **Frontend:** React, Vite, TypeScript
- **Deployment target:** AWS

## Purpose, the two queries this app exists to answer

Everything in this system is built to serve exactly two lookups. When in
doubt about a design decision, favor whichever choice makes these two
queries simpler, faster, or more trustworthy.

1. **Forward trace (serial → history):** Given a **serial number**,
   return its full build history, every part, supplier lot, work order,
   inspection, certificate, and nonconformance that went into that unit.
2. **Backward trace (lot → serials):** Given a **supplier lot**, return
   every **serial number** that consumed material from that lot.

## Domain vocabulary

Use these terms consistently across code, database, API, and UI. Do not
invent synonyms.

- **Part**, A distinct item that can be stocked, purchased, or built.
  Identified by a part number. May be a raw material, a component, or a
  finished device.
- **Bill of materials (BOM)**, The list of parts (and quantities)
  required to build a given parent part.
- **Supplier lot**, A quantity of a purchased part received from a
  supplier under a single lot/batch identifier. The unit of incoming
  traceability.
- **Certificate of conformance (CoC)**, A supplier's documented
  attestation that a supplier lot meets its specification. Attached to a
  supplier lot.
- **Work order**, An authorization and record for building a quantity
  of a part. Consumes supplier lots and/or sub-assemblies and produces
  as-built serial records.
- **As-built serial record**, The record of a single physical unit
  produced, identified by a serial number, capturing exactly which
  supplier lots and child serials were consumed to build it.
- **Incoming inspection**, The recorded inspection of a supplier lot on
  receipt, with a disposition (e.g. accept / reject).
- **Nonconformance (NC)**, A recorded deviation from specification,
  raised against a part, supplier lot, or serial.
- **Device history record (DHR)**, The compiled, complete build and
  quality history of a single as-built unit (serial number). This is the
  output of the forward trace.

## Constraints

These are non-negotiable for this project.

- **No hard deletes anywhere.** Records are never physically removed.
  Use soft-delete / status fields; deletion is a state, not a `DELETE`.
- **Every write is an audit event.** Every create, update, and
  soft-delete is recorded as an immutable audit event capturing what
  changed, when, and to which record.
- **Keep the dependency list minimal.** Prefer the standard library and
  the core stack (FastAPI, SQLAlchemy, React, Vite) over adding new
  packages. Justify any new dependency.
- **No auth, no multi-tenancy.** This project has no authentication,
  authorization, users, or tenant isolation. Do not add them.
