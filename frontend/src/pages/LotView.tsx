import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { RecallScope } from "../api/types";
import { useNav } from "../nav";

export function LotView({ lotNumber }: { lotNumber: string }) {
  const nav = useNav();
  const [scope, setScope] = useState<RecallScope | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setScope(null);
    setError(null);
    api
      .recallScope(lotNumber)
      .then((s) => !cancelled && setScope(s))
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Failed to load recall scope.");
      });
    return () => {
      cancelled = true;
    };
  }, [lotNumber]);

  if (error) return <div className="notice notice--error">{error}</div>;
  if (!scope) return <div className="notice">Loading recall scope…</div>;

  const finished = new Set(scope.finished_devices);

  return (
    <section>
      <div className="unithead">
        <div className="unithead__id">
          <span className="mono big">{scope.lot_number}</span>
          <span className="unithead__part">{scope.supplier_name}</span>
        </div>
        <div className="unithead__meta">
          <span>affected units <b>{scope.total_affected}</b></span>
          <span>direct consumers <b>{scope.direct_consumers}</b></span>
          <span>max depth <b>{scope.max_depth}</b></span>
        </div>
        <div className="unithead__flags">
          {scope.finished_devices.length > 0 ? (
            <span className="chip chip--fail">
              {scope.finished_devices.length} FINISHED DEVICE
              {scope.finished_devices.length > 1 ? "S" : ""} AFFECTED
            </span>
          ) : (
            <span className="chip chip--ok">no finished devices affected</span>
          )}
        </div>
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>Serial</th>
            <th>Part</th>
            <th>Work order</th>
            <th>Built</th>
            <th className="grid__qty">Depth</th>
            <th>Consumption</th>
          </tr>
        </thead>
        <tbody>
          {scope.affected_serials.map((s) => {
            const isFinished = s.serial_number != null && finished.has(s.serial_number);
            return (
              <tr key={s.serial_number ?? Math.random()} className={isFinished ? "row row--alert" : "row"}>
                <td>
                  {s.serial_number ? (
                    <button className="link mono" onClick={() => nav.openSerial(s.serial_number!)}>
                      {s.serial_number}
                    </button>
                  ) : (
                    <span className="muted">— orphan —</span>
                  )}
                </td>
                <td>
                  <span className="mono">{s.part_number ?? "—"}</span>
                  <span className="part__name">{s.part_name}</span>
                  {isFinished && <span className="chip chip--fail">FINISHED</span>}
                </td>
                <td className="mono">{s.work_order_number ?? "—"}</td>
                <td className="muted">{s.built_at ? s.built_at.slice(0, 10) : "—"}</td>
                <td className="grid__qty">{s.depth}</td>
                <td>
                  {s.direct ? (
                    <span className="chip chip--direct">direct</span>
                  ) : (
                    <span className="muted">via sub-assembly</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
