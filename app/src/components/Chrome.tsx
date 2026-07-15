/** Shared chrome: eye mark, fixture banner, state badge, footer. */

import { STATE_COLORS, STATE_LABELS } from "../lib/data";

export function EyeMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <ellipse
        cx="16"
        cy="16"
        rx="14"
        ry="9"
        fill="none"
        stroke="var(--amber)"
        strokeWidth="2"
      />
      <circle cx="16" cy="16" r="4.5" fill="var(--amber)" />
    </svg>
  );
}

/**
 * The no-fake-data rule, rendered: shown whenever any loaded artifact
 * carries contains_fixture_data. Removing this banner requires real data,
 * not a CSS change — export.py --final refuses fixture-derived artifacts.
 */
export function FixtureBanner({ flagged }: { flagged: string[] }) {
  if (flagged.length === 0) return null;
  return (
    <div
      role="status"
      style={{
        background: "var(--amber-soft)",
        border: "1px solid var(--amber)",
        color: "var(--amber)",
        borderRadius: 10,
        padding: "10px 16px",
        margin: "0 0 20px",
        fontWeight: 600,
        fontSize: 13.5,
      }}
    >
      FIXTURE DATA — NOT REAL · API keys pending; these slices run on clearly
      marked development fixtures: {flagged.join(", ")}. Google Trends data and
      everything derived from it is real.
    </div>
  );
}

export function StateBadge({ state }: { state: string | null }) {
  const key = state ?? "undetermined";
  return (
    <span
      className="badge"
      style={{ color: STATE_COLORS[key], borderColor: STATE_COLORS[key] }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 99,
          background: STATE_COLORS[key],
          display: "inline-block",
        }}
      />
      {STATE_LABELS[key] ?? key}
    </span>
  );
}

export function Footer() {
  return (
    <footer
      className="muted"
      style={{
        borderTop: "1px solid var(--line)",
        marginTop: 40,
        padding: "16px 0 8px",
        fontSize: 13,
        display: "flex",
        flexWrap: "wrap",
        gap: 12,
        justifyContent: "space-between",
      }}
    >
      <span>
        Built as an independent application artifact for the OFF/BEAT team. Not
        affiliated.
      </span>
      <span>
        Built by Harsh Sinha ·{" "}
        <a href="https://github.com/hkumar5357/nazar">github.com/hkumar5357/nazar</a>
      </span>
    </footer>
  );
}
