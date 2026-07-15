import { Fragment } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AllData } from "../lib/data";

const THRESHOLD_ORDER = ["L1", "L2", "V0", "V1", "A1"] as const;

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  // Coverage/threshold dates are ISO date or date-time strings; show the date part.
  const datePart = iso.slice(0, 10);
  const d = new Date(datePart + "T00:00:00");
  if (Number.isNaN(d.getTime())) return datePart;
  return d.toLocaleDateString("en-IN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function coverageSpan(entry: Record<string, unknown> | null): string {
  if (!entry) return "—";
  const first = (entry["first_week"] ?? entry["first_item"]) as
    | string
    | undefined;
  const last = (entry["last_week"] ?? entry["last_item"]) as
    | string
    | undefined;
  if (!first || !last) return "—";
  return `${fmtDate(first)} → ${fmtDate(last)}`;
}

function coverageVolume(entry: Record<string, unknown> | null): string {
  if (!entry) return "—";
  if (typeof entry["weeks"] === "number") {
    const excluded = entry["partial_weeks_excluded"];
    const excludedNote =
      typeof excluded === "number" && excluded > 0
        ? ` (${excluded} partial excluded)`
        : "";
    return `${entry["weeks"]} weeks${excludedNote}`;
  }
  if (typeof entry["items"] === "number") {
    return `${entry["items"]} items`;
  }
  return "—";
}

const SOURCE_LABELS: Record<string, string> = {
  trends: "Google Trends",
  reddit: "Reddit",
  youtube: "YouTube",
};

export default function Protocol({ data }: { data: AllData }) {
  const { protocol } = data;
  const frozen = protocol.thresholds_frozen;
  const coverage = protocol.coverage;
  const qa = protocol.qa_agreement;
  const costs = protocol.costs;

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>The contract, pre-registered</h2>
      <p className="muted" style={{ marginTop: 0, marginBottom: 20, fontSize: 13.5 }}>
        Committed alone as this repo&rsquo;s first commit, before any code.
        Amendments are dated and the freeze tag precedes all demo scoring
        &mdash; verifiable in git history.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        {/* Frozen thresholds */}
        <div className="panel">
          <h3 style={{ marginTop: 0, fontSize: 15 }}>Frozen thresholds</h3>
          {frozen ? (
            <>
              <dl
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr",
                  columnGap: 10,
                  rowGap: 4,
                  margin: "12px 0",
                  fontFamily:
                    "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                  fontSize: 13,
                }}
              >
                {THRESHOLD_ORDER.map((k) => (
                  <Fragment key={k}>
                    <dt className="muted">{k}</dt>
                    <dd style={{ margin: 0, color: "var(--ink)" }}>
                      {frozen.thresholds[k] ?? "—"}
                    </dd>
                  </Fragment>
                ))}
              </dl>
              <p style={{ fontSize: 13, color: "var(--ink-2)", margin: "4px 0" }}>
                Frozen {fmtDate(frozen.frozen_at)} on calibration trend{" "}
                <strong style={{ color: "var(--ink)" }}>
                  {frozen.calibration_trend.replace(/_/g, " ")}
                </strong>
                . Grid rank {frozen.grid_rank}, score {frozen.grid_score}/90.
              </p>
              <details>
                <summary
                  style={{
                    cursor: "pointer",
                    fontSize: 13,
                    color: "var(--amber)",
                    fontWeight: 600,
                  }}
                >
                  Why these
                </summary>
                <p
                  style={{
                    fontSize: 13,
                    color: "var(--ink-2)",
                    lineHeight: 1.6,
                    marginBottom: 0,
                  }}
                >
                  {frozen.rationale}
                </p>
              </details>
            </>
          ) : (
            <p className="muted" style={{ fontSize: 13.5 }}>
              Thresholds not yet frozen.
            </p>
          )}
        </div>

        {/* Label QA */}
        <div className="panel">
          <h3 style={{ marginTop: 0, fontSize: 15 }}>Label QA</h3>
          {qa === null ? (
            <p style={{ fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.6 }}>
              No real LLM labels yet (key pending). The 50-item hand-check
              sample generates only from real labels &mdash; heuristic
              placeholders are never QA&rsquo;d as if they were the model.
            </p>
          ) : (
            <>
              <div
                style={{
                  fontSize: 34,
                  fontWeight: 700,
                  color: "var(--ink)",
                  margin: "8px 0 4px",
                }}
              >
                {(qa.agreement_rate * 100).toFixed(0)}%
              </div>
              <p className="muted" style={{ fontSize: 13, margin: 0 }}>
                agreement on a {qa.sample_size}-item hand-check sample
              </p>
            </>
          )}
        </div>

        {/* Honest costs */}
        <div className="panel">
          <h3 style={{ marginTop: 0, fontSize: 15 }}>Honest costs</h3>
          {costs === null ? (
            <p style={{ fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.6 }}>
              Computed at M5: build hours + API spend in rupees.
            </p>
          ) : (
            <>
              <p style={{ fontSize: 13.5, color: "var(--ink-2)", margin: "8px 0 4px" }}>
                <span style={{ color: "var(--ink)", fontWeight: 600 }}>
                  {costs.build_hours}
                </span>{" "}
                build hours
              </p>
              <p style={{ fontSize: 13.5, color: "var(--ink-2)", margin: "4px 0" }}>
                <span style={{ color: "var(--ink)", fontWeight: 600 }}>
                  &#8377;{costs.api_spend_inr.toLocaleString("en-IN")}
                </span>{" "}
                API spend
              </p>
              {costs.notes && (
                <p className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
                  {costs.notes}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Coverage table */}
      <div className="panel" style={{ marginBottom: 24 }}>
        <h3 style={{ marginTop: 0, fontSize: 15 }}>Data coverage</h3>
        {coverage ? (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["Trend", "Source", "Provenance", "Span", "Volume"].map(
                    (h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: "left",
                          fontSize: 12,
                          fontWeight: 600,
                          textTransform: "uppercase",
                          letterSpacing: "0.03em",
                          color: "var(--muted)",
                          padding: "6px 10px",
                          borderBottom: "1px solid var(--line)",
                        }}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {Object.entries(coverage.coverage).flatMap(
                  ([trend, sources]) =>
                    Object.entries(sources).map(([source, entry]) => (
                      <tr
                        key={`${trend}-${source}`}
                        style={{ borderBottom: "1px solid var(--line)" }}
                      >
                        <td
                          style={{
                            padding: "8px 10px",
                            fontSize: 13.5,
                            color: "var(--ink)",
                          }}
                        >
                          {trend.replace(/_/g, " ")}
                        </td>
                        <td
                          style={{
                            padding: "8px 10px",
                            fontSize: 13.5,
                            color: "var(--ink-2)",
                          }}
                        >
                          {SOURCE_LABELS[source] ?? source}
                        </td>
                        <td style={{ padding: "8px 10px", fontSize: 13.5 }}>
                          {entry?.["provenance"] === "fixture" ? (
                            <span
                              className="badge"
                              style={{
                                color: "var(--amber)",
                                borderColor: "var(--amber)",
                              }}
                            >
                              FIXTURE
                            </span>
                          ) : entry?.["provenance"] === "real" ? (
                            <span style={{ color: "var(--mark-teal)" }}>
                              real
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td
                          style={{
                            padding: "8px 10px",
                            fontSize: 13.5,
                            color: "var(--ink-2)",
                          }}
                        >
                          {coverageSpan(entry)}
                        </td>
                        <td
                          style={{
                            padding: "8px 10px",
                            fontSize: 13.5,
                            color: "var(--ink-2)",
                          }}
                        >
                          {coverageVolume(entry)}
                        </td>
                      </tr>
                    )),
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 13.5 }}>
            No coverage snapshot recorded yet.
          </p>
        )}
      </div>

      {/* Full protocol markdown */}
      <div className="panel" style={{ maxWidth: 820 }}>
        <h3 style={{ marginTop: 0, fontSize: 15 }}>The full protocol</h3>
        <div className="protocol-md">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {protocol.markdown}
          </ReactMarkdown>
        </div>
        <style>{`
          .protocol-md h1,
          .protocol-md h2,
          .protocol-md h3 {
            color: color-mix(in srgb, var(--amber) 85%, var(--ink));
            margin-top: 1.6em;
            margin-bottom: 0.5em;
          }
          .protocol-md h1:first-child,
          .protocol-md h2:first-child {
            margin-top: 0;
          }
          .protocol-md p,
          .protocol-md li {
            color: var(--ink-2);
            font-size: 14.5px;
            line-height: 1.65;
          }
          .protocol-md ul,
          .protocol-md ol {
            padding-left: 1.4em;
          }
          .protocol-md li {
            margin: 6px 0;
          }
          .protocol-md strong {
            color: var(--ink);
          }
          .protocol-md code {
            background: var(--surface-2);
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 13px;
            color: var(--ink);
          }
          .protocol-md pre {
            background: var(--surface-2);
            border-radius: 8px;
            padding: 12px 14px;
            overflow-x: auto;
          }
          .protocol-md pre code {
            background: none;
            padding: 0;
          }
          .protocol-md a {
            color: var(--amber);
          }
          .protocol-md hr {
            border: none;
            border-top: 1px solid var(--line);
            margin: 20px 0;
          }
          .protocol-md table {
            border-collapse: collapse;
            width: 100%;
            margin: 12px 0;
          }
          .protocol-md th,
          .protocol-md td {
            border: 1px solid var(--line);
            padding: 6px 10px;
            font-size: 13.5px;
            text-align: left;
            color: var(--ink-2);
          }
          .protocol-md th {
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
          }
        `}</style>
      </div>
    </div>
  );
}
