import { useState } from "react";

import { AllData, TREND_LABELS } from "../lib/data";

type Creator = AllData["affinity"]["creators"][number];

const TREND_KEYS = Object.keys(TREND_LABELS);

function compactSubscribers(n: number): string {
  if (n >= 1_000_000) {
    const v = n / 1_000_000;
    return `${v % 1 === 0 ? v.toFixed(0) : v.toFixed(1)}M`;
  }
  if (n >= 1_000) {
    const v = n / 1_000;
    return `${v % 1 === 0 ? v.toFixed(0) : v.toFixed(1)}K`;
  }
  return String(n);
}

export default function MapBoard({ data }: { data: AllData }) {
  const { affinity } = data;
  const [trend, setTrend] = useState<string>(TREND_KEYS[0] ?? "matcha");
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null);

  const ranked = [...affinity.creators].sort(
    (a, b) => a.per_trend[trend].rank - b.per_trend[trend].rank,
  );
  const maxScore = Math.max(
    0.0001,
    ...affinity.creators.map((c) => c.per_trend[trend].score),
  );

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 6,
        }}
      >
        <h2 style={{ fontSize: 18, margin: 0 }}>Who carries this trend</h2>
        {affinity.provenance.contains_fixture_data && (
          <span
            className="badge"
            style={{
              color: "var(--amber)",
              borderColor: "var(--amber)",
              background: "var(--amber-soft)",
            }}
          >
            fixture creator data — YouTube key pending
          </span>
        )}
      </div>
      <p className="muted" style={{ fontSize: 13.5, margin: "0 0 20px" }}>
        Relative ranks from keyword-taxonomy topic vectors × engagement —
        ranks, not precision. Scores order creators within one trend only;
        they aren&rsquo;t comparable across trends or across creators as
        probabilities.
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        {TREND_KEYS.map((key) => {
          const selected = trend === key;
          return (
            <button
              key={key}
              type="button"
              aria-pressed={selected}
              onClick={() => setTrend(key)}
              style={{
                background: selected ? "var(--surface-2)" : "transparent",
                color: selected ? "var(--ink)" : "var(--ink-2)",
                border: "1px solid",
                borderColor: selected ? "var(--line)" : "transparent",
                borderRadius: 999,
                padding: "7px 16px",
                fontSize: 13.5,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {TREND_LABELS[key]}
            </button>
          );
        })}
      </div>

      <div className="panel" style={{ padding: "8px 20px" }}>
        {ranked.map((creator: Creator, idx: number) => {
          const entry = creator.per_trend[trend];
          const barPct = Math.max(2, (entry.score / maxScore) * 100);
          const isHovered = hoveredSlug === creator.slug;
          return (
            <div
              key={creator.slug}
              onMouseEnter={() => setHoveredSlug(creator.slug)}
              onMouseLeave={() => setHoveredSlug(null)}
              style={{
                position: "relative",
                display: "grid",
                gridTemplateColumns: "24px 1fr 180px 64px",
                alignItems: "center",
                gap: 14,
                padding: "12px 4px",
                borderBottom:
                  idx === ranked.length - 1 ? "none" : "1px solid var(--line)",
                background: isHovered ? "var(--surface-2)" : "transparent",
                borderRadius: 8,
              }}
            >
              <span
                className="muted"
                style={{
                  fontFamily:
                    "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                  fontSize: 13,
                  textAlign: "right",
                }}
              >
                {entry.rank}
              </span>

              <span
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 8,
                  flexWrap: "wrap",
                  minWidth: 0,
                }}
              >
                <span style={{ color: "var(--ink)", fontWeight: 600 }}>
                  {creator.name}
                </span>
                <span className="muted" style={{ fontSize: 11.5 }}>
                  {creator.niche}
                </span>
                {creator.is_control && (
                  <span
                    className="badge"
                    style={{
                      color: "var(--mark-orange)",
                      borderColor: "var(--mark-orange)",
                      fontSize: 11,
                      padding: "1px 8px",
                    }}
                  >
                    control
                  </span>
                )}
              </span>

              <span
                style={{
                  height: 6,
                  borderRadius: 999,
                  background: "var(--line)",
                  overflow: "hidden",
                }}
              >
                <span
                  style={{
                    display: "block",
                    height: "100%",
                    width: `${barPct}%`,
                    borderRadius: 999,
                    background: creator.is_control
                      ? "var(--mark-slate)"
                      : "var(--mark-teal)",
                  }}
                />
              </span>

              <span
                className="muted"
                style={{
                  fontSize: 12,
                  textAlign: "right",
                  fontFamily:
                    "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                }}
              >
                {entry.score.toFixed(4)}
              </span>

              {isHovered && (
                <div
                  role="tooltip"
                  style={{
                    position: "absolute",
                    right: 4,
                    top: "100%",
                    marginTop: 4,
                    zIndex: 1,
                    background: "var(--surface-2)",
                    border: "1px solid var(--line)",
                    color: "var(--ink)",
                    borderRadius: 8,
                    padding: "6px 10px",
                    fontSize: 12,
                    whiteSpace: "nowrap",
                  }}
                >
                  {compactSubscribers(creator.subscribers)} subscribers ·{" "}
                  {creator.engagement_factor.toFixed(2)}x engagement
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="panel" style={{ marginTop: 20 }}>
        <h3 style={{ fontSize: 16, margin: "0 0 14px" }}>
          Pre-registered validation (Amendment A3)
        </h3>
        {affinity.validation.map((check, idx) => {
          const isLowControl = check.check.toLowerCase().includes("bottom");
          return (
            <div key={idx}>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: 16,
                  padding: "10px 0",
                  borderBottom:
                    idx === affinity.validation.length - 1
                      ? "none"
                      : "1px solid var(--line)",
                }}
              >
                <span style={{ flex: "1 1 320px", color: "var(--ink-2)" }}>
                  {check.check}
                </span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  expected: {check.expected}
                </span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  actual: {check.actual}
                </span>
                <span
                  className="badge"
                  style={{
                    color: check.pass
                      ? "var(--mark-teal)"
                      : "var(--mark-orange)",
                    borderColor: check.pass
                      ? "var(--mark-teal)"
                      : "var(--mark-orange)",
                  }}
                >
                  {check.pass ? "PASS" : "FAIL"}
                </span>
              </div>
              {isLowControl && check.pass && (
                <p
                  className="muted"
                  style={{
                    fontStyle: "italic",
                    fontSize: 13,
                    margin: "2px 0 14px",
                  }}
                >
                  A model that can say &ldquo;bad fit&rdquo; is a model you
                  can trust when it says &ldquo;good fit&rdquo;.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
