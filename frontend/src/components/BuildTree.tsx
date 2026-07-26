import { useMemo, useState } from "react";
import type { SerialTree } from "../api/types";
import { useNav } from "../nav";
import {
  allUnitKeys,
  flatten,
  hasIssues,
  lotFailed,
  lotOpenNC,
  type Flags,
  type Row,
} from "./tree";

function fmtQty(q: number | string | null): string {
  if (q == null) return "";
  const n = Number(q);
  return Number.isFinite(n) ? String(n) : String(q);
}

function fmtDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

/** Red/amber chips that must read at a glance. */
function IssueChips({ flags, below }: { flags: Flags; below: boolean }) {
  if (!hasIssues(flags)) return null;
  const arrow = below ? "▾ " : "";
  return (
    <>
      {flags.failed > 0 && (
        <span className="chip chip--fail">
          {arrow}FAILED INSP{flags.failed > 1 ? ` ×${flags.failed}` : ""}
        </span>
      )}
      {flags.openNC > 0 && (
        <span className="chip chip--nc">
          {arrow}OPEN NC{flags.openNC > 1 ? ` ×${flags.openNC}` : ""}
        </span>
      )}
    </>
  );
}

export function BuildTree({ root }: { root: SerialTree }) {
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set([root.serial_number ?? "root"]),
  );
  const rows = useMemo(() => flatten(root, expanded), [root, expanded]);
  const nav = useNav();

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  return (
    <div className="tree">
      <div className="tree__toolbar">
        <button onClick={() => setExpanded(new Set(allUnitKeys(root)))}>Expand all</button>
        <button onClick={() => setExpanded(new Set([root.serial_number ?? "root"]))}>
          Collapse all
        </button>
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th className="grid__tree">Position / Part</th>
            <th>Serial / Lot</th>
            <th>Supplier</th>
            <th>CoC</th>
            <th className="grid__status">Status</th>
            <th className="grid__qty">Qty</th>
            <th className="grid__act"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <TreeRow key={row.key} row={row} expanded={expanded} onToggle={toggle} onOpenLot={nav.openLot} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TreeRow({
  row,
  expanded,
  onToggle,
  onOpenLot,
}: {
  row: Row;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  onOpenLot: (lot: string) => void;
}) {
  const indent = { paddingLeft: `${row.depth * 18 + 6}px` };

  if (row.type === "unit") {
    const isOpen = expanded.has(row.key);
    const alert = hasIssues(row.flags);
    // Distinguish "problem here vs below": if collapsed, chips describe the
    // hidden subtree; if expanded, only self-level open NCs remain to show here.
    const selfOpenNC = row.node.nonconformances.filter((nc) => nc.status === "open").length;
    return (
      <tr className={alert ? "row row--alert" : "row"}>
        <td className="grid__tree" style={indent}>
          {row.expandable ? (
            <button className="caret" onClick={() => onToggle(row.key)}>
              {isOpen ? "▾" : "▸"}
            </button>
          ) : (
            <span className="caret caret--none" />
          )}
          {row.position && <span className="pos">{row.position}</span>}
          <span className="part">
            <span className="mono">{row.node.part_number ?? "-"}</span>
            <span className="part__name">{row.node.part_name}</span>
          </span>
          {row.node.is_cycle && <span className="chip chip--warn">CYCLE</span>}
        </td>
        <td>
          <span className="mono strong">{row.node.serial_number ?? "-"}</span>
          <span className="sub mono">{row.node.work_order_number}</span>
        </td>
        <td className="muted">-</td>
        <td className="muted">-</td>
        <td className="grid__status">
          {isOpen ? (
            <>
              {selfOpenNC > 0 && <span className="chip chip--nc">OPEN NC ×{selfOpenNC}</span>}
              {/* below-badge on expanded parents when children still carry issues */}
              {hasIssues(row.flags) && (
                <IssueChips
                  flags={{ failed: row.flags.failed, openNC: row.flags.openNC - selfOpenNC }}
                  below
                />
              )}
            </>
          ) : (
            <IssueChips flags={row.flags} below />
          )}
        </td>
        <td className="grid__qty muted">{fmtDate(row.node.built_at)}</td>
        <td className="grid__act" />
      </tr>
    );
  }

  if (row.type === "orphan") {
    return (
      <tr className="row row--alert">
        <td className="grid__tree" style={indent}>
          {row.position && <span className="pos">{row.position}</span>}
          <span className="muted">missing reference</span>
        </td>
        <td colSpan={5} className="muted">
          {row.comp.note ?? "dangling reference"}
        </td>
        <td className="grid__act" />
      </tr>
    );
  }

  // Lot leaf row.
  const lot = row.comp.lot!;
  const failed = lotFailed(lot);
  const openNC = lotOpenNC(lot);
  return (
    <tr className={failed || openNC ? "row row--alert" : "row"}>
      <td className="grid__tree" style={indent}>
        <span className="caret caret--none" />
        {row.position && <span className="pos">{row.position}</span>}
        <span className="part">
          <span className="mono">{lot.part_number ?? "-"}</span>
          <span className="part__name">{lot.part_name}</span>
        </span>
      </td>
      <td>
        <span className="mono">{lot.lot_number ?? "-"}</span>
        <span className="sub muted">rcvd {fmtDate(lot.received_at)}</span>
      </td>
      <td className="supplier">{lot.supplier_name ?? "-"}</td>
      <td>
        {lot.certificate_status === "present" ? (
          <span className="coc coc--ok">CoC ✓</span>
        ) : (
          <span className="chip chip--warn">NO CoC</span>
        )}
      </td>
      <td className="grid__status">
        {failed && <span className="chip chip--fail" title={lot.inspection_notes ?? ""}>FAILED INSP</span>}
        {openNC && (
          <span className="chip chip--nc" title={lot.nonconformances.map((n) => `${n.nc_number}: ${n.description}`).join("\n")}>
            OPEN NC
          </span>
        )}
        {!failed && !openNC && lot.inspection_disposition && (
          <span className="disp">{lot.inspection_disposition}</span>
        )}
      </td>
      <td className="grid__qty">{fmtQty(row.comp.quantity)}</td>
      <td className="grid__act">
        {lot.lot_number && (
          <button className="jump" onClick={() => onOpenLot(lot.lot_number!)} title="Open recall scope for this lot">
            lot →
          </button>
        )}
      </td>
    </tr>
  );
}
