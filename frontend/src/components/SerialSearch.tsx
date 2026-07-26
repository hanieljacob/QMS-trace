import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SerialSummary } from "../api/types";
import { useNav } from "../nav";

export function SerialSearch() {
  const nav = useNav();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SerialSummary[]>([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 1) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .searchSerials(term)
        .then((rows) => !cancelled && setResults(rows))
        .catch(() => !cancelled && setResults([]));
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const go = (serial: string) => {
    if (!serial) return;
    setOpen(false);
    setQ("");
    setResults([]);
    nav.openSerial(serial);
  };

  return (
    <div className="search" ref={boxRef}>
      <input
        className="search__input"
        placeholder="Search serial / part / work order…"
        value={q}
        spellCheck={false}
        autoCorrect="off"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter") go(results[0]?.serial_number ?? q.trim());
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && results.length > 0 && (
        <ul className="search__results">
          {results.map((r) => (
            <li key={r.serial_number} onMouseDown={() => go(r.serial_number)}>
              <span className="mono">{r.serial_number}</span>
              <span className="search__meta">
                {r.part_number} · {r.part_name}
              </span>
              <span className="search__wo mono">{r.work_order_number}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
