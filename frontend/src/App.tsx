import { useCallback, useMemo, useState } from "react";
import { SerialSearch } from "./components/SerialSearch";
import { NavContext, type Nav, type Route } from "./nav";
import { SerialView } from "./pages/SerialView";
import { LotView } from "./pages/LotView";

export function App() {
  const [stack, setStack] = useState<Route[]>([{ kind: "home" }]);
  const current = stack[stack.length - 1];

  const nav = useMemo<Nav>(
    () => ({
      openSerial: (id) => setStack((s) => [...s, { kind: "serial", id }]),
      openLot: (id) => setStack((s) => [...s, { kind: "lot", id }]),
      back: () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)),
      canBack: stack.length > 1,
    }),
    [stack.length],
  );

  const crumb = useCallback((r: Route) => {
    if (r.kind === "serial") return `serial ${r.id}`;
    if (r.kind === "lot") return `lot ${r.id}`;
    return "home";
  }, []);

  return (
    <NavContext.Provider value={nav}>
      <header className="topbar">
        <div className="topbar__brand">qmstrace</div>
        <SerialSearch />
        <div className="topbar__trail">
          {stack.map((r, i) => (
            <span key={i} className="crumb" data-current={i === stack.length - 1}>
              {i > 0 && <span className="crumb__sep">/</span>}
              {crumb(r)}
            </span>
          ))}
        </div>
      </header>

      <main className="main">
        {nav.canBack && (
          <button className="back" onClick={nav.back}>
            ← back
          </button>
        )}
        {current.kind === "home" && <Home />}
        {current.kind === "serial" && <SerialView serialNumber={current.id} />}
        {current.kind === "lot" && <LotView lotNumber={current.id} />}
      </main>
    </NavContext.Provider>
  );
}

function Home() {
  return (
    <div className="empty">
      <p>
        Search a <strong>serial number</strong> above to view its complete build
        history.
      </p>
      <p className="empty__hint">
        Try <code>SRA-0001</code> — a finished surgical robot arm.
      </p>
    </div>
  );
}
