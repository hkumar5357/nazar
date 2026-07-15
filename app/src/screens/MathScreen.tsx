import { useMemo, useState } from "react";
import { AllData } from "../lib/data";
import { compute, verifyReferenceScenarios, LaunchInputs } from "../lib/launchMath";

const RUPEE = "₹";

function defaultsFromParams(data: AllData): LaunchInputs {
  const p: Partial<LaunchInputs> = {};
  for (const param of data.launchMath.params) {
    (p as unknown as Record<string, number>)[param.id] = param.default;
  }
  return p as LaunchInputs;
}

function fmtInr(x: number): string {
  return `${RUPEE}${x.toFixed(2)}`;
}

export default function MathScreen({ data }: { data: AllData }) {
  const { launchMath } = data;
  const [inputs, setInputs] = useState<LaunchInputs>(() => defaultsFromParams(data));

  const outputs = useMemo(() => compute(inputs), [inputs]);

  const mismatches = useMemo(
    () => verifyReferenceScenarios(launchMath.reference_scenarios),
    [launchMath.reference_scenarios]
  );

  const handleChange = (id: string, value: number) => {
    setInputs((prev) => ({ ...prev, [id]: value }));
  };

  const handleReset = () => {
    setInputs(defaultsFromParams(data));
  };

  const contributionPositive = outputs.contribution_per_order > 0;

  return (
    <div>
      <div
        className="panel"
        role="status"
        style={{
          border: "1px solid var(--amber)",
          color: "var(--amber)",
          background: "var(--amber-soft)",
          fontWeight: 600,
          fontSize: 13.5,
          marginBottom: 20,
        }}
      >
        {launchMath.banner}
      </div>

      <h2 style={{ fontSize: 18, marginBottom: 4 }}>
        One hypothetical RTD matcha launch
      </h2>
      <p className="muted" style={{ marginTop: 0, marginBottom: 20 }}>
        {launchMath.benchmarks_note}
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 20,
        }}
        className="math-grid"
      >
        <style>{`
          @media (max-width: 900px) {
            .math-grid { grid-template-columns: 1fr !important; }
          }
        `}</style>

        <div className="panel">
          <h3 style={{ fontSize: 15, marginTop: 0, marginBottom: 16 }}>
            Assumptions
          </h3>
          {launchMath.params.map((param) => {
            const value = (inputs as unknown as Record<string, number>)[param.id];
            return (
              <div key={param.id} style={{ marginBottom: 18 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    marginBottom: 6,
                  }}
                >
                  <label
                    htmlFor={`param-${param.id}`}
                    style={{ color: "var(--ink-2)", fontSize: 13.5 }}
                  >
                    {param.label}{" "}
                    <span className="muted">({param.unit})</span>
                  </label>
                  <span style={{ color: "var(--ink)", fontWeight: 600 }}>
                    {value}
                  </span>
                </div>
                <input
                  id={`param-${param.id}`}
                  type="range"
                  min={param.min}
                  max={param.max}
                  step={param.step}
                  value={value}
                  onChange={(e) =>
                    handleChange(param.id, parseFloat(e.target.value))
                  }
                  style={{
                    width: "100%",
                    accentColor: "var(--amber)",
                  }}
                />
                <div
                  className="muted"
                  style={{ fontSize: 11.5, marginTop: 6, lineHeight: 1.4 }}
                >
                  {param.source_note}
                </div>
              </div>
            );
          })}
          <button
            type="button"
            onClick={handleReset}
            style={{
              background: "transparent",
              color: "var(--muted)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              padding: "8px 14px",
              fontSize: 13,
              cursor: "pointer",
              marginTop: 4,
            }}
          >
            Reset to defaults
          </button>
        </div>

        <div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 16,
              marginBottom: 20,
            }}
          >
            <div className="panel">
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
                Contribution per order
              </div>
              <div
                style={{
                  fontSize: 28,
                  fontWeight: 700,
                  color: contributionPositive ? "var(--amber)" : "var(--mark-orange)",
                }}
              >
                {fmtInr(outputs.contribution_per_order)}
              </div>
            </div>
            <div className="panel">
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
                CAC payback (orders)
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: "var(--ink)" }}>
                {outputs.payback_orders === null
                  ? "—"
                  : outputs.payback_orders.toFixed(2)}
              </div>
              {outputs.payback_orders === null && (
                <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                  never at these numbers
                </div>
              )}
            </div>
            <div className="panel">
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
                CAC payback (months)
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: "var(--ink)" }}>
                {outputs.payback_months === null
                  ? "—"
                  : outputs.payback_months.toFixed(2)}
              </div>
              {outputs.payback_months === null && (
                <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                  never at these numbers
                </div>
              )}
            </div>
          </div>

          <div className="panel" style={{ marginBottom: 20 }}>
            <div
              className="muted"
              style={{
                fontSize: 12.5,
                display: "flex",
                gap: 20,
                flexWrap: "wrap",
              }}
            >
              <span>
                Net revenue:{" "}
                <span style={{ color: "var(--ink-2)" }}>
                  {fmtInr(outputs.net_revenue)}
                </span>
              </span>
              <span>
                COGS:{" "}
                <span style={{ color: "var(--ink-2)" }}>
                  {fmtInr(outputs.cogs)}
                </span>
              </span>
            </div>
            <details style={{ marginTop: 16 }}>
              <summary
                style={{
                  cursor: "pointer",
                  color: "var(--ink-2)",
                  fontSize: 13.5,
                }}
              >
                Formulas
              </summary>
              <ul style={{ marginTop: 10, paddingLeft: 18 }}>
                {Object.entries(launchMath.formulas).map(([key, formula]) => (
                  <li
                    key={key}
                    style={{
                      fontFamily:
                        "ui-monospace, SFMono-Regular, Menlo, monospace",
                      fontSize: 12.5,
                      color: "var(--ink-2)",
                      marginBottom: 8,
                      lineHeight: 1.5,
                    }}
                  >
                    {formula}
                  </li>
                ))}
              </ul>
            </details>
          </div>

          {mismatches.length > 0 ? (
            <div
              className="panel"
              style={{
                border: "1px solid var(--mark-orange)",
              }}
            >
              <div
                style={{
                  color: "var(--mark-orange)",
                  fontWeight: 600,
                  fontSize: 13.5,
                  marginBottom: 8,
                }}
              >
                Client math disagrees with pipeline math — do not trust this
                screen until fixed.
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {mismatches.map((m) => (
                  <li
                    key={m}
                    className="muted"
                    style={{ fontSize: 12.5, marginBottom: 4 }}
                  >
                    {m}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 12.5 }}>
              Client math verified against 3 pipeline reference scenarios.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
