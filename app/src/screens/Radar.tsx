import { useState } from "react";

import { StateBadge } from "../components/Chrome";
import {
  AllData,
  STATE_COLORS,
  STATE_LABELS,
  TREND_LABELS,
  TimelineRow,
} from "../lib/data";

/** Lifecycle order, left to right. */
const LANE_ORDER = ["emerging", "heating", "peaked", "mature", "undetermined"];

const MONTH_ABBR = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** "2026-07-01" -> "Jul 2026" (or "Jul 26" with twoDigitYear). */
function monthLabel(iso: string, twoDigitYear = false): string {
  const [y, m] = iso.split("-");
  const mi = parseInt(m, 10) - 1;
  const year = twoDigitYear ? y.slice(2) : y;
  return `${MONTH_ABBR[mi] ?? m} ${year}`;
}

function fmtNum(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(3);
}

const PLOT_HEIGHT = 168;
const DOT_INSET = 18;

export default function Radar({ data }: { data: AllData }) {
  const [hovered, setHovered] = useState<string | null>(null);

  const { backtest_dates, trends } = data.stateTimeline;
  const trendKeys = Object.keys(trends);
  const asOf = backtest_dates[backtest_dates.length - 1];

  // Last row per trend = the current call.
  const lastRows: Record<string, TimelineRow> = {};
  trendKeys.forEach((k) => {
    const rows = trends[k];
    lastRows[k] = rows[rows.length - 1];
  });

  // Shared velocity axis across all current calls.
  const velocities = trendKeys
    .map((k) => lastRows[k].features?.velocity_8w)
    .filter((v): v is number => typeof v === "number");
  const vMin = velocities.length ? Math.min(...velocities) : 0;
  const vMax = velocities.length ? Math.max(...velocities) : 1;
  const vPad = vMax - vMin < 1e-9 ? 0.05 : (vMax - vMin) * 0.25;
  const domainMin = vMin - vPad;
  const domainMax = vMax + vPad;

  function velocityTop(v: number | null | undefined): number {
    if (v === null || v === undefined || domainMax === domainMin) {
      return PLOT_HEIGHT / 2;
    }
    const norm = (v - domainMin) / (domainMax - domainMin);
    const clamped = Math.min(1, Math.max(0, norm));
    // higher velocity -> higher up (smaller top offset)
    return DOT_INSET + (1 - clamped) * (PLOT_HEIGHT - DOT_INSET * 2);
  }

  // Group trends into their current-state lane.
  const laneTrends: Record<string, string[]> = {};
  LANE_ORDER.forEach((s) => (laneTrends[s] = []));
  trendKeys.forEach((k) => {
    const state = lastRows[k].state ?? "undetermined";
    const lane = LANE_ORDER.includes(state) ? state : "undetermined";
    laneTrends[lane].push(k);
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Header */}
      <div className="panel">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 8,
            alignItems: "baseline",
          }}
        >
          <h2 style={{ margin: 0, fontSize: 18 }}>Where each trend sits</h2>
          <span className="muted" style={{ fontSize: 13 }}>
            As of {monthLabel(asOf)} · T = {asOf}
          </span>
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
          Thresholds were frozen on a fourth trend (Korean skincare) never
          shown here — see Protocol.
        </p>
      </div>

      {/* The map */}
      <div className="panel">
        <h3 style={{ marginTop: 0, marginBottom: 14, fontSize: 15 }}>
          Lifecycle map
        </h3>
        <div style={{ display: "flex", gap: 10 }}>
          <div
            style={{
              width: 54,
              flexShrink: 0,
              paddingTop: 30,
              textAlign: "right",
              paddingRight: 4,
            }}
          >
            <span className="muted" style={{ fontSize: 11 }}>
              ↑ velocity
            </span>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(5, 1fr)",
              gap: 10,
              flex: 1,
              minWidth: 0,
            }}
          >
            {LANE_ORDER.map((state) => {
              const keys = laneTrends[state];
              return (
                <div
                  key={state}
                  style={{
                    background: "var(--surface-2)",
                    border: "1px solid var(--line)",
                    borderRadius: 10,
                    padding: "10px 6px",
                    display: "flex",
                    flexDirection: "column",
                    minWidth: 0,
                  }}
                >
                  <div
                    style={{
                      fontSize: 12.5,
                      fontWeight: 650,
                      color: STATE_COLORS[state],
                      marginBottom: 8,
                      textAlign: "center",
                    }}
                  >
                    {STATE_LABELS[state]}
                  </div>
                  <div style={{ display: "flex", gap: 4 }}>
                    {keys.length === 0 && (
                      <div style={{ flex: 1, height: PLOT_HEIGHT }} />
                    )}
                    {keys.map((k) => {
                      const row = lastRows[k];
                      const f = row.features;
                      const top = velocityTop(f?.velocity_8w ?? null);
                      const breadth = f?.breadth ?? 0;
                      const size = Math.min(14 * (breadth + 1), 30);
                      const isHovered = hovered === k;
                      return (
                        <div
                          key={k}
                          style={{
                            flex: 1,
                            minWidth: 0,
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                          }}
                        >
                          <div
                            style={{
                              position: "relative",
                              height: PLOT_HEIGHT,
                              width: "100%",
                            }}
                          >
                            <div
                              onMouseEnter={() => setHovered(k)}
                              onMouseLeave={() => setHovered(null)}
                              style={{
                                position: "absolute",
                                top,
                                left: "50%",
                                transform: "translate(-50%, -50%)",
                                width: size,
                                height: size,
                                borderRadius: "50%",
                                background: STATE_COLORS[state],
                                boxShadow: "0 0 0 2px var(--surface-2)",
                                cursor: "pointer",
                                zIndex: isHovered ? 30 : 1,
                              }}
                            >
                              {isHovered && (
                                <div
                                  role="tooltip"
                                  style={{
                                    position: "absolute",
                                    bottom: "calc(100% + 8px)",
                                    left: "50%",
                                    transform: "translateX(-50%)",
                                    background: "var(--surface-2)",
                                    border: "1px solid var(--line)",
                                    color: "var(--ink)",
                                    borderRadius: 8,
                                    padding: "8px 10px",
                                    fontSize: 12,
                                    lineHeight: 1.5,
                                    whiteSpace: "nowrap",
                                    zIndex: 40,
                                    boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
                                  }}
                                >
                                  <div
                                    style={{
                                      fontWeight: 650,
                                      marginBottom: 4,
                                      color: "var(--ink)",
                                    }}
                                  >
                                    {TREND_LABELS[k] ?? k}
                                  </div>
                                  <div className="muted">
                                    composite:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {fmtNum(f?.composite)}
                                    </span>
                                  </div>
                                  <div className="muted">
                                    velocity_8w:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {fmtNum(f?.velocity_8w)}
                                    </span>
                                  </div>
                                  <div className="muted">
                                    accel:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {fmtNum(f?.accel)}
                                    </span>
                                  </div>
                                  <div className="muted">
                                    peak_proximity:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {fmtNum(f?.peak_proximity)}
                                    </span>
                                  </div>
                                  <div className="muted">
                                    drawdown:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {fmtNum(f?.drawdown)}
                                    </span>
                                  </div>
                                  <div className="muted">
                                    breadth:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {f ? f.breadth : "—"}
                                    </span>
                                  </div>
                                  <div className="muted">
                                    n_sources:{" "}
                                    <span style={{ color: "var(--ink-2)" }}>
                                      {f ? f.n_sources : "—"}
                                    </span>
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                          <div
                            style={{
                              fontSize: 12,
                              color: "var(--ink)",
                              textAlign: "center",
                              marginTop: 4,
                            }}
                          >
                            {TREND_LABELS[k] ?? k}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Last 19 months strip */}
      <div className="panel">
        <h3 style={{ marginTop: 0, marginBottom: 4, fontSize: 15 }}>
          Last 19 months
        </h3>
        <p className="muted" style={{ fontSize: 12.5, margin: "0 0 14px" }}>
          Monthly walk-forward state per trend — the honest context behind
          today's call, including the months it spent undetermined. Circles
          mark Heating months; hover any cell for its month and state.
        </p>
        <div style={{ overflowX: "auto" }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              width: "fit-content",
            }}
          >
            {trendKeys.map((k) => {
              const rows = trends[k];
              return (
                <div
                  key={k}
                  style={{ display: "flex", alignItems: "center", gap: 12 }}
                >
                  <div
                    style={{
                      width: 130,
                      flexShrink: 0,
                      fontSize: 13,
                      color: "var(--ink-2)",
                    }}
                  >
                    {TREND_LABELS[k] ?? k}
                  </div>
                  <div style={{ display: "flex", gap: 2 }}>
                    {rows.map((row, i) => {
                      const s = row.state ?? "undetermined";
                      const color = STATE_COLORS[s] ?? STATE_COLORS.undetermined;
                      return (
                        <div
                          key={i}
                          title={`${row.T.slice(0, 7)}: ${STATE_LABELS[s] ?? s}`}
                          style={{
                            width: 12,
                            height: 12,
                            // shape is the non-color cue: Heating months are
                            // circles (amber/orange sit in the CVD floor band)
                            borderRadius: s === "heating" ? "50%" : 3,
                            background: color,
                            opacity: s === "undetermined" ? 0.5 : 1,
                          }}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 130, flexShrink: 0 }} />
              <div style={{ display: "flex", gap: 2 }}>
                {backtest_dates.map((d, i) => {
                  const [, m] = d.split("-");
                  const showLabel = m === "01" || m === "07";
                  return (
                    <div
                      key={i}
                      style={{ width: 12, position: "relative", height: 14 }}
                    >
                      {showLabel && (
                        <span
                          className="muted"
                          style={{
                            position: "absolute",
                            top: 0,
                            left: "50%",
                            transform: "translateX(-50%)",
                            fontSize: 11,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {monthLabel(d, true)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div
        className="panel"
        style={{ display: "flex", gap: 10, flexWrap: "wrap" }}
      >
        {LANE_ORDER.map((s) => (
          <StateBadge key={s} state={s} />
        ))}
      </div>
    </div>
  );
}
