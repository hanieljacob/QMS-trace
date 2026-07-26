// Response shapes mirroring the qmstrace API's frontend-facing view models
// (app/schemas/views.py). These are the shapes the screens consume, not the
// database tables.

export interface SerialSummary {
  serial_number: string;
  part_number: string | null;
  part_name: string | null;
  work_order_number: string | null;
  built_at: string | null;
}

export interface NonconformanceView {
  nc_number: string;
  status: string;
  description: string;
}

export interface ConsumedLot {
  lot_number: string | null;
  part_number: string | null;
  part_name: string | null;
  supplier_name: string | null;
  received_at: string | null;
  certificate_status: string; // "present" | "absent"
  inspection_disposition: string | null; // e.g. "accepted" | "rejected"
  inspection_notes: string | null;
  nonconformances: NonconformanceView[];
}

export interface BuildComponent {
  position: string | null;
  quantity: number | string | null;
  kind: "lot" | "serial" | "orphan";
  lot: ConsumedLot | null;
  child: SerialTree | null;
  note: string | null;
}

export interface SerialTree {
  serial_number: string | null;
  part_number: string | null;
  part_name: string | null;
  work_order_number: string | null;
  built_at: string | null;
  is_cycle: boolean;
  nonconformances: NonconformanceView[];
  components: BuildComponent[];
}

export interface LotSummary {
  lot_number: string;
  part_number: string | null;
  part_name: string | null;
  supplier_name: string | null;
  received_at: string | null;
  inspection_disposition: string | null;
  certificate_status: string;
  open_nc_count: number;
}

export interface InspectionResult {
  inspected_at: string | null;
  disposition: string | null;
  notes: string | null;
}

export interface AffectedUnit {
  serial_number: string | null;
  part_number: string | null;
  part_name: string | null;
  built_at: string | null;
  depth: number;
  direct: boolean;
  status: string; // "released" | "nc_open" | "voided"
  is_finished_device: boolean;
}

export interface WorkOrderGroup {
  work_order_number: string;
  unit_count: number;
  units: AffectedUnit[];
}

export interface LotReport {
  lot_number: string | null;
  part_number: string | null;
  part_name: string | null;
  supplier_name: string | null;
  received_at: string | null;
  quantity_received: number | string | null;
  certificate_status: string;
  certificate_references: string[];
  inspections: InspectionResult[];
  nonconformances: NonconformanceView[];
  blast_radius: number;
  direct_consumers: number;
  finished_device_count: number;
  finished_devices: string[];
  work_order_groups: WorkOrderGroup[];
}
