import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { SerialTree } from "../api/types";
import { BuildTree } from "../components/BuildTree";
import { hasIssues, subtreeFlags } from "../components/tree";

export function SerialView({ serialNumber }: { serialNumber: string }) {
  const [tree, setTree] = useState<SerialTree | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTree(null);
    setError(null);
    api
      .serialGenealogy(serialNumber)
      .then((t) => !cancelled && setTree(t))
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Failed to load build history.");
      });
    return () => {
      cancelled = true;
    };
  }, [serialNumber]);

  if (error) return <div className="notice notice--error">{error}</div>;
  if (!tree) return <div className="notice">Loading build history…</div>;

  const flags = subtreeFlags(tree);
  const alert = hasIssues(flags);

  return (
    <section>
      <div className={alert ? "unithead unithead--alert" : "unithead"}>
        <div className="unithead__id">
          <span className="mono big">{tree.serial_number}</span>
          <span className="unithead__part">
            {tree.part_number} · {tree.part_name}
          </span>
        </div>
        <div className="unithead__meta">
          <span>work order <b className="mono">{tree.work_order_number ?? "—"}</b></span>
          <span>built <b>{tree.built_at ? tree.built_at.slice(0, 10) : "—"}</b></span>
        </div>
        <div className="unithead__flags">
          {alert ? (
            <>
              {flags.failed > 0 && (
                <span className="chip chip--fail">
                  {flags.failed} FAILED INSPECTION{flags.failed > 1 ? "S" : ""}
                </span>
              )}
              {flags.openNC > 0 && (
                <span className="chip chip--nc">
                  {flags.openNC} OPEN NONCONFORMANCE{flags.openNC > 1 ? "S" : ""}
                </span>
              )}
            </>
          ) : (
            <span className="chip chip--ok">no open issues</span>
          )}
        </div>
      </div>
      <BuildTree root={tree} />
    </section>
  );
}
