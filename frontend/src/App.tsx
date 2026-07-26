import { useCallback, useMemo, useState } from "react";
import { Search } from "./components/Search";
import { NavContext, useNav, type Nav, type Route } from "./nav";
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
        <Search />
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
  const nav = useNav();
  return (
    <div className="home">
      <p className="home__lead">
        qmstrace answers two questions about a build: <strong>what went into a
        unit</strong>, and <strong>where a supplier lot ended up</strong>. Use the
        search box above (toggle it between <strong>Serial</strong> and{" "}
        <strong>Lot</strong>), or start from an example below.
      </p>

      <div className="home__cards">
        <div className="home__card">
          <div className="home__card-h">Trace a serial &rarr; build history</div>
          <p>
            A finished unit's complete as-built genealogy, expandable by BOM
            level, with failed inspections and open nonconformances flagged inline
            and a downloadable Device History Record (PDF).
          </p>
          <p className="home__try">
            Try{" "}
            <button className="link mono" onClick={() => nav.openSerial("SRA-0001")}>
              SRA-0001
            </button>
            , a finished surgical robot arm. A rejected bearing lot and an open
            nonconformance surface deep in its tree.
          </p>
        </div>

        <div className="home__card">
          <div className="home__card-h">Trace a lot &rarr; recall scope</div>
          <p>
            Every unit that consumed a supplier lot, grouped by work order, with
            the blast radius up top and a link back to each unit's build history.
          </p>
          <p className="home__try">
            Try{" "}
            <button className="link mono" onClick={() => nav.openLot("CMP610-NBA-02")}>
              CMP610-NBA-02
            </button>
            , a bearing lot that failed incoming inspection but reached 16 units,
            including two finished arms.
          </p>
          <p className="home__try">
            Or{" "}
            <button className="link mono" onClick={() => nav.openLot("CMP660-TBA-02")}>
              CMP660-TBA-02
            </button>
            , an adhesive lot with an open nonconformance spanning several work
            orders.
          </p>
        </div>
      </div>

      <p className="home__note">
        Seeded demo data: 26 parts across a four-level bill of materials, 40
        supplier lots from 8 suppliers, 12 work orders, 60 built units.
      </p>
    </div>
  );
}
