import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { LotReport } from "../api/types";
import { useNav } from "../nav";

function fmtDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "-";
}

function StatusBadge({ status }: { status: string }) {
  if (status === "voided") return <span className="chip chip--warn">VOIDED</span>;
  if (status === "nc_open") return <span className="chip chip--nc">NC OPEN</span>;
  return <span className="ustatus">released</span>;
}

export function LotView({ lotNumber }: { lotNumber: string }) {
  const nav = useNav();
  const [report, setReport] = useState<LotReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setReport(null);
    setError(null);
    api
      .lotReport(lotNumber)
      .then((r) => !cancelled && setReport(r))
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Failed to load lot report.");
      });
    return () => {
      cancelled = true;
    };
  }, [lotNumber]);

  if (error) return <div className="notice notice--error">{error}</div>;
  if (!report) return <div className="notice">Loading lot report…</div>;

  const rejected = report.inspections.some((i) => i.disposition === "rejected");
  const hasOpenNC = report.nonconformances.some((n) => n.status === "open");
  const noCoC = report.certificate_status !== "present";
  const lotAlert = rejected || hasOpenNC || noCoC;

  return (
    <section>
      {/* Blast radius, the headline number. */}
      <div className="blast">
        <div className="blast__num">{report.blast_radius}</div>
        <div className="blast__label">
          units affected
          <span className="blast__sub">
            {report.direct_consumers} direct · {report.finished_device_count} finished device
            {report.finished_device_count === 1 ? "" : "s"}
          </span>
        </div>
        <div className="blast__lot">
          <span className="mono big">{report.lot_number}</span>
          <span className="muted">
            {report.part_number} · {report.part_name}, {report.supplier_name}
          </span>
        </div>
      </div>

      {/* Lot quality context, alongside. */}
      <div className={lotAlert ? "quality quality--alert" : "quality"}>
        <div className="quality__cell">
          <div className="quality__h">Incoming inspection</div>
          {report.inspections.length === 0 && <span className="muted">none recorded</span>}
          {report.inspections.map((i, idx) => (
            <div key={idx} className="quality__insp">
              {i.disposition === "rejected" ? (
                <span className="chip chip--fail">REJECTED</span>
              ) : (
                <span className="ustatus">{i.disposition}</span>
              )}
              <span className="muted"> {fmtDate(i.inspected_at)}</span>
              {i.notes && <div className="quality__notes">{i.notes}</div>}
            </div>
          ))}
        </div>

        <div className="quality__cell">
          <div className="quality__h">Certificate of conformance</div>
          {report.certificate_status === "present" ? (
            <>
              <span className="coc coc--ok">CoC ✓</span>
              {report.certificate_references.map((r) => (
                <div key={r} className="mono quality__ref">{r}</div>
              ))}
            </>
          ) : (
            <span className="chip chip--warn">NO CoC ON FILE</span>
          )}
        </div>

        <div className="quality__cell">
          <div className="quality__h">Nonconformances</div>
          {report.nonconformances.length === 0 && <span className="muted">none</span>}
          {report.nonconformances.map((nc) => (
            <div key={nc.nc_number} className="quality__nc">
              <span className={nc.status === "open" ? "chip chip--nc" : "chip"}>
                {nc.nc_number} · {nc.status}
              </span>
              <div className="quality__notes">{nc.description}</div>
            </div>
          ))}
        </div>

        <div className="quality__cell">
          <div className="quality__h">Received</div>
          <div>{fmtDate(report.received_at)}</div>
          <div className="muted">qty {report.quantity_received ?? "-"}</div>
        </div>
      </div>

      {/* Affected units grouped by work order. */}
      {report.work_order_groups.map((g) => (
        <div key={g.work_order_number} className="wogroup">
          <div className="wogroup__head">
            <span className="mono strong">{g.work_order_number}</span>
            <span className="muted">{g.unit_count} unit{g.unit_count === 1 ? "" : "s"}</span>
          </div>
          <table className="grid">
            <thead>
              <tr>
                <th>Serial</th>
                <th>Part</th>
                <th>Built</th>
                <th className="grid__qty">Depth</th>
                <th>Consumption</th>
                <th>Unit status</th>
              </tr>
            </thead>
            <tbody>
              {g.units.map((u) => (
                <tr key={u.serial_number ?? Math.random()} className={u.is_finished_device ? "row row--alert" : "row"}>
                  <td>
                    {u.serial_number ? (
                      <button className="link mono" onClick={() => nav.openSerial(u.serial_number!)}>
                        {u.serial_number}
                      </button>
                    ) : (
                      <span className="muted">orphan</span>
                    )}
                  </td>
                  <td>
                    <span className="mono">{u.part_number ?? "-"}</span>
                    <span className="part__name">{u.part_name}</span>
                    {u.is_finished_device && <span className="chip chip--fail">FINISHED DEVICE</span>}
                  </td>
                  <td className="muted">{fmtDate(u.built_at)}</td>
                  <td className="grid__qty">{u.depth}</td>
                  <td>
                    {u.direct ? (
                      <span className="chip chip--direct">direct</span>
                    ) : (
                      <span className="muted">via sub-assembly</span>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={u.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}
