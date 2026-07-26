# Data model

Each table below is described in domain terms, what it represents on the shop
floor, not how it is stored. See `CLAUDE.md` for the vocabulary and the two
queries the whole system exists to answer.

Two rules hold for every table:

- **created_at / created_by**, every record remembers when it was created and
  by whom (a free-text actor label; there is no auth in this project).
- **No hard deletes**, every domain table carries `voided_at` / `voided_by` /
  `void_reason`. "Deleting" something means marking it voided; the record stays.
  The one exception is the audit trail, which is append-only and never voided.

## Tables

### part
A distinct item that can be stocked, purchased, or built, raw material,
component, or finished device, identified by a part number. One table holds all
three; the `part_type` says which it is.

### bom_line
One component position in a parent part's bill of materials: "this parent needs
this quantity of this child at this position." Because a child part can be the
parent of its own lines, a bill of materials nests to any depth, three or four
levels is routine.

### supplier_lot
A quantity of a purchased part received from a supplier under a single lot
number. This is the unit of incoming traceability and the starting point of the
backward trace (lot → every serial that consumed it).

### certificate_of_conformance
A supplier's documented attestation that a given supplier lot meets its
specification. Each certificate belongs to one supplier lot.

### incoming_inspection
The inspection performed on a supplier lot when it arrives, recording who
inspected it, when, and the disposition (accepted, rejected, accepted with
deviation, or still pending).

### work_order
The authorization and record for building a quantity of a part. A work order is
what produces as-built serial records, and it moves through states (open, in
process, completed, cancelled) rather than ever being deleted.

### as_built_serial_record
One physical unit that was actually built, identified by its serial number and
tied to the work order that produced it. Walking a serial's consumed components
is the forward trace, the full build history of that unit.

### as_built_component
What was actually consumed at one component position of a built unit. Each row
points to *either* a supplier lot (a purchased component) *or* a child serial (a
serialized sub-assembly), exactly one, which is what lets the trace follow a
device down through every level of its build and back up again.

### nonconformance
A recorded deviation from specification, raised against *either* a supplier lot
*or* a single serial (exactly one), with a disposition such as use-as-is,
rework, scrap, or closed.

### audit_event
An append-only log of every write in the system, each create, update, or void,
with what changed, when, and by whom. This table is never edited or deleted; it
is the evidence that the other tables are trustworthy.

## Not a table: the device history record

The **device history record (DHR)** is the compiled, complete build-and-quality
history of one serial number, the *output* of the forward trace. It is assembled
on demand by walking `as_built_serial_record` → `as_built_component` (down
through sub-assemblies and supplier lots) and gathering the related inspections,
certificates, and nonconformances. It is derived from the tables above, not
stored as its own table.
