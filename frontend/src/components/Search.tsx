import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { LotSummary, SerialSummary } from "../api/types";
import { useNav } from "../nav";

type Mode = "serial" | "lot";

export function Search() {
  const nav = useNav();
  const [mode, setMode] = useState<Mode>("serial");
  const [q, setQ] = useState("");
  const [serials, setSerials] = useState<SerialSummary[]>([]);
  const [lots, setLots] = useState<LotSummary[]>([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 1) {
      setSerials([]);
      setLots([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      if (mode === "serial") {
        api.searchSerials(term).then((r) => !cancelled && setSerials(r)).catch(() => !cancelled && setSerials([]));
      } else {
        api.searchLots(term).then((r) => !cancelled && setLots(r)).catch(() => !cancelled && setLots([]));
      }
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q, mode]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const reset = () => {
    setOpen(false);
    setQ("");
    setSerials([]);
    setLots([]);
  };
  const goSerial = (sn: string) => {
    if (!sn) return;
    reset();
    nav.openSerial(sn);
  };
  const goLot = (ln: string) => {
    if (!ln) return;
    reset();
    nav.openLot(ln);
  };

  const onEnter = () => {
    if (mode === "serial") goSerial(serials[0]?.serial_number ?? q.trim());
    else goLot(lots[0]?.lot_number ?? q.trim());
  };

  return (
    <div className="search" ref={boxRef}>
      <div className="seg">
        <button className={mode === "serial" ? "seg__on" : ""} onClick={() => { setMode("serial"); setOpen(true); }}>
          Serial
        </button>
        <button className={mode === "lot" ? "seg__on" : ""} onClick={() => { setMode("lot"); setOpen(true); }}>
          Lot
        </button>
      </div>
      <input
        className="search__input"
        placeholder={mode === "serial" ? "serial / part / work order…" : "lot / supplier / part…"}
        value={q}
        spellCheck={false}
        autoCorrect="off"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onEnter();
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && mode === "serial" && serials.length > 0 && (
        <ul className="search__results">
          {serials.map((r) => (
            <li key={r.serial_number} onMouseDown={() => goSerial(r.serial_number)}>
              <span className="mono">{r.serial_number}</span>
              <span className="search__meta">{r.part_number} · {r.part_name}</span>
              <span className="search__wo mono">{r.work_order_number}</span>
            </li>
          ))}
        </ul>
      )}
      {open && mode === "lot" && lots.length > 0 && (
        <ul className="search__results">
          {lots.map((r) => {
            const bad = r.inspection_disposition === "rejected" || r.open_nc_count > 0 || r.certificate_status !== "present";
            return (
              <li key={r.lot_number} onMouseDown={() => goLot(r.lot_number)}>
                <span className="mono">{r.lot_number}</span>
                <span className="search__meta">{r.part_number} · {r.supplier_name}</span>
                <span className="search__flags">
                  {r.inspection_disposition === "rejected" && <span className="chip chip--fail">FAILED</span>}
                  {r.open_nc_count > 0 && <span className="chip chip--nc">NC {r.open_nc_count}</span>}
                  {r.certificate_status !== "present" && <span className="chip chip--warn">NO CoC</span>}
                  {!bad && <span className="ok-dot">●</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
