import { useEffect, useState } from "react";

import { EyeMark, FixtureBanner, Footer } from "./components/Chrome";
import { AllData, fixtureFlagged, loadAll } from "./lib/data";
import GoldenThread from "./screens/GoldenThread";
import MapBoard from "./screens/MapBoard";
import MathScreen from "./screens/MathScreen";
import Protocol from "./screens/Protocol";
import Radar from "./screens/Radar";

const TABS = [
  { id: "radar", label: "Radar" },
  { id: "golden", label: "Golden Thread" },
  { id: "map", label: "Map" },
  { id: "math", label: "Math" },
  { id: "protocol", label: "Protocol" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function App() {
  const [tab, setTab] = useState<TabId>("radar");
  const [data, setData] = useState<AllData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadAll().then(setData, (e) => setError(String(e)));
  }, []);

  return (
    <div style={{ maxWidth: 1160, margin: "0 auto", padding: "20px 24px" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          flexWrap: "wrap",
          marginBottom: 18,
        }}
      >
        <EyeMark size={30} />
        <h1 style={{ fontSize: 22, margin: 0 }}>
          <span lang="hi" style={{ color: "var(--amber)" }}>
            नज़र
          </span>{" "}
          NAZAR
        </h1>
        <span className="muted" style={{ fontSize: 13.5 }}>
          trend lifecycle radar · Nazar rakhna.
        </span>
        <nav style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
              style={{
                background: tab === t.id ? "var(--surface-2)" : "transparent",
                color: tab === t.id ? "var(--ink)" : "var(--ink-2)",
                border: "1px solid",
                borderColor: tab === t.id ? "var(--line)" : "transparent",
                borderRadius: 9,
                padding: "7px 14px",
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <div className="panel" style={{ color: "var(--mark-orange)" }}>
          Failed to load committed data: {error}
        </div>
      )}
      {!data && !error && <div className="muted">Loading committed data…</div>}

      {data && (
        <>
          <FixtureBanner flagged={fixtureFlagged(data)} />
          {tab === "radar" && <Radar data={data} />}
          {tab === "golden" && <GoldenThread data={data} />}
          {tab === "map" && <MapBoard data={data} />}
          {tab === "math" && <MathScreen data={data} />}
          {tab === "protocol" && <Protocol data={data} />}
        </>
      )}
      <Footer />
    </div>
  );
}
