import { useMemo } from "react";
import {
  ComposedChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { AllData, STATE_LABELS } from "../lib/data";

/** Short, chart-safe names for the matcha mainstream-marker events. */
const EVENT_SHORT_NAMES: Record<string, string> = {
  matcha_costa_global: "Costa Coffee UK range",
  matcha_starbucks_india: "Starbucks India menu",
  matcha_media_india: "India food media staple",
};

/** Compact month + 2-digit year for the tight rotated axis labels. */
function formatDateShort(dateStr: string): string {
  const dt = new Date(`${dateStr}T00:00:00Z`);
  const month = dt.toLocaleDateString("en-GB", {
    month: "short",
    timeZone: "UTC",
  });
  const year = dt.getUTCFullYear().toString().slice(2);
  return `${month} '${year}`;
}

interface ChartRow {
  week: string;
  composite: number | null;
  heatingDot: number | null;
  state: string;
}

interface TooltipPayloadEntry {
  payload: ChartRow;
}

function GoldenTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  return (
    <div
      style={{
        background: "var(--surface-2)",
        border: "1px solid var(--line)",
        color: "var(--ink)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 12.5,
      }}
    >
      <div style={{ color: "var(--muted)", marginBottom: 4 }}>{row.week}</div>
      <div>
        composite:{" "}
        {row.composite !== null ? row.composite.toFixed(3) : "no data"}
      </div>
      <div>state: {STATE_LABELS[row.state] ?? row.state}</div>
    </div>
  );
}

interface IntentRow {
  week: string;
  cafe_experience: number;
  home_or_CPG: number;
  other: number;
}

interface IntentTooltipPayloadEntry {
  name: string;
  value: number;
  color: string;
}

function IntentTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: IntentTooltipPayloadEntry[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div
      style={{
        background: "var(--surface-2)",
        border: "1px solid var(--line)",
        color: "var(--ink)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 12.5,
      }}
    >
      <div style={{ color: "var(--muted)", marginBottom: 4 }}>{label}</div>
      {payload.map((entry) => (
        <div key={entry.name} style={{ display: "flex", gap: 8 }}>
          <span style={{ color: entry.color }}>&#9679;</span>
          <span>
            {entry.name}: {entry.value.toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export default function GoldenThread({ data }: { data: AllData }) {
  const { goldenThread, leadTimes, intentSplit, firstFlags } = data;

  const matchaLeadEvents = useMemo(
    () => leadTimes.events.filter((e) => e.trend === "matcha"),
    [leadTimes.events],
  );

  const firstFlagInfo = firstFlags.trends["matcha"];

  const chartData: ChartRow[] = useMemo(() => {
    const heating = new Set(goldenThread.heating_weeks);
    return goldenThread.weekly.map((w) => ({
      week: w.week,
      composite: w.composite,
      heatingDot: heating.has(w.week) ? w.composite : null,
      state: w.state,
    }));
  }, [goldenThread]);

  const yearTicks = useMemo(() => {
    const seen = new Set<string>();
    const ticks: string[] = [];
    for (const row of chartData) {
      const year = row.week.slice(0, 4);
      if (!seen.has(year)) {
        seen.add(year);
        ticks.push(row.week);
      }
    }
    return ticks;
  }, [chartData]);

  // Snap an arbitrary calendar date to the nearest week bucket present in
  // the chart data, so ReferenceLine (category axis) actually renders.
  const nearestWeek = useMemo(() => {
    return (dateStr: string): string => {
      const target = new Date(`${dateStr}T00:00:00Z`).getTime();
      let best = chartData[0]?.week ?? dateStr;
      let bestDiff = Infinity;
      for (const row of chartData) {
        const diff = Math.abs(
          new Date(`${row.week}T00:00:00Z`).getTime() - target,
        );
        if (diff < bestDiff) {
          bestDiff = diff;
          best = row.week;
        }
      }
      return best;
    };
  }, [chartData]);

  const firstFlagWeek = firstFlagInfo?.first_heating_week_in_backtest_window;

  // Intent split: aggregate weekly counts into 4-week buckets before taking
  // shares — per-week counts are small integers and their shares whipsaw.
  // Binning sums the raw counts (no smoothing of values, no interpolation);
  // buckets where nothing was tagged at all are skipped (no signal to split).
  const intentChartData = useMemo(() => {
    const buckets: {
      week: string;
      cafe_experience: number;
      home_or_CPG: number;
      other: number;
    }[] = [];
    for (let i = 0; i < intentSplit.weekly.length; i += 4) {
      const chunk = intentSplit.weekly.slice(i, i + 4);
      const sum = (k: "cafe_experience" | "home_or_CPG" | "other") =>
        chunk.reduce((a, w) => a + w[k], 0);
      buckets.push({
        week: chunk[0].week,
        cafe_experience: sum("cafe_experience"),
        home_or_CPG: sum("home_or_CPG"),
        other: sum("other"),
      });
    }
    return buckets
      .map((w) => {
        const total = w.cafe_experience + w.home_or_CPG + w.other;
        if (total === 0) return null;
        return {
          week: w.week,
          cafe_experience: (w.cafe_experience / total) * 100,
          home_or_CPG: (w.home_or_CPG / total) * 100,
          other: (w.other / total) * 100,
        };
      })
      .filter((r): r is NonNullable<typeof r> => r !== null);
  }, [intentSplit.weekly]);

  const intentYearTicks = useMemo(() => {
    const seen = new Set<string>();
    const ticks: string[] = [];
    for (const row of intentChartData) {
      const year = row.week.slice(0, 4);
      if (!seen.has(year)) {
        seen.add(year);
        ticks.push(row.week);
      }
    }
    return ticks;
  }, [intentChartData]);

  const homeShare = (rows: IntentRow[]): number => {
    const home = rows.reduce((a, r) => a + r.home_or_CPG, 0);
    const total = rows.reduce(
      (a, r) => a + r.cafe_experience + r.home_or_CPG + r.other,
      0,
    );
    return total > 0 ? (home / total) * 100 : 0;
  };
  const firstShare = homeShare(intentSplit.weekly.slice(0, 26));
  const lastShare = homeShare(intentSplit.weekly.slice(-26));
  const shiftedUp = lastShare - firstShare >= 5;

  return (
    <div>
      <h2 style={{ marginBottom: 12 }}>
        Matcha: flagged before the mainstream
      </h2>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 10,
        }}
      >
        {matchaLeadEvents.map((e) => (
          <span
            key={e.event_id}
            className="badge"
            style={{ color: "var(--ink)", borderColor: "var(--amber)" }}
          >
            flagged {e.lead_days_conservative} days before{" "}
            {EVENT_SHORT_NAMES[e.event_id] ?? e.event_name}
          </span>
        ))}
      </div>

      <p className="muted" style={{ fontSize: 13, marginBottom: 24 }}>
        Conservative variant: first in-window flag{" "}
        {firstFlagInfo?.first_heating_week_in_backtest_window ?? "—"}. The raw
        first flag ({firstFlagInfo?.first_heating_week ?? "—"}) is
        boundary-censored — the trend was already building when observation
        began (see Protocol).
      </p>

      <div className="panel" style={{ marginBottom: 24 }}>
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart
            data={chartData}
            margin={{ top: 150, right: 24, bottom: 8, left: 16 }}
          >
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis
              dataKey="week"
              ticks={yearTicks}
              tickFormatter={(w: string) => w.slice(0, 4)}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={{ stroke: "var(--line)" }}
              tickLine={{ stroke: "var(--line)" }}
            />
            <YAxis
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={{ stroke: "var(--line)" }}
              tickLine={{ stroke: "var(--line)" }}
              label={{
                value: "composite index (z)",
                angle: -90,
                position: "insideLeft",
                fill: "var(--muted)",
                fontSize: 12,
              }}
            />
            <Tooltip content={<GoldenTooltip />} />
            <Legend wrapperStyle={{ color: "var(--ink-2)", fontSize: 12.5 }} />
            {goldenThread.events.map((event) => (
              <ReferenceLine
                key={event.event_id}
                x={nearestWeek(event.event_date)}
                stroke="var(--ink-2)"
                strokeDasharray="4 4"
                label={{
                  value: `${EVENT_SHORT_NAMES[event.event_id] ?? event.event_name} · ${formatDateShort(event.event_date)}`,
                  angle: -90,
                  position: "top",
                  fill: "var(--ink-2)",
                  fontSize: 11,
                }}
              />
            ))}
            {firstFlagWeek && (
              <ReferenceLine
                x={firstFlagWeek}
                stroke="var(--mark-amber)"
                strokeDasharray="2 3"
                label={{
                  value: "first in-window flag",
                  angle: -90,
                  position: "top",
                  fill: "var(--ink-2)",
                  fontSize: 11,
                }}
              />
            )}
            <Line
              type="monotone"
              dataKey="composite"
              name="Composite"
              stroke="var(--mark-amber)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="heatingDot"
              name="Heating flag"
              stroke="none"
              dot={{ r: 4.5, fill: "var(--mark-amber)", stroke: "none" }}
              activeDot={{ r: 5.5, fill: "var(--mark-amber)" }}
              connectNulls={false}
              isAnimationActive={false}
              legendType="circle"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="panel">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 4,
          }}
        >
          <h3 style={{ margin: 0 }}>Cafe vs home/CPG intent</h3>
          {intentSplit.provenance.contains_fixture_data && (
            <span
              className="badge"
              style={{ color: "var(--amber)", borderColor: "var(--amber)" }}
            >
              fixture labels &mdash; heuristic h1, LLM key pending
            </span>
          )}
        </div>

        <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
          {shiftedUp
            ? `Home/CPG intent share moved from ~${firstShare.toFixed(0)}% to ~${lastShare.toFixed(0)}% — conversation is shifting from cafe visits toward at-home consumption: the CPG whitespace.`
            : `Home/CPG intent share moved from ~${firstShare.toFixed(0)}% to ~${lastShare.toFixed(0)}% — no whitespace shift visible yet.`}
        </p>

        <ResponsiveContainer width="100%" height={320}>
          <AreaChart
            data={intentChartData}
            margin={{ top: 8, right: 24, bottom: 8, left: 16 }}
          >
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis
              dataKey="week"
              ticks={intentYearTicks}
              tickFormatter={(w: string) => w.slice(0, 4)}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={{ stroke: "var(--line)" }}
              tickLine={{ stroke: "var(--line)" }}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={{ stroke: "var(--line)" }}
              tickLine={{ stroke: "var(--line)" }}
              label={{
                value: "share of tagged mentions, 4-week buckets (%)",
                angle: -90,
                position: "insideLeft",
                fill: "var(--muted)",
                fontSize: 12,
              }}
            />
            <Tooltip content={<IntentTooltip />} />
            <Legend wrapperStyle={{ color: "var(--ink-2)", fontSize: 12.5 }} />
            <Area
              type="monotone"
              dataKey="cafe_experience"
              name="Cafe experience"
              stackId="intent"
              stroke="var(--mark-amber)"
              strokeWidth={1.5}
              fill="var(--mark-amber)"
              fillOpacity={0.55}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="home_or_CPG"
              name="Home / CPG"
              stackId="intent"
              stroke="var(--mark-teal)"
              strokeWidth={1.5}
              fill="var(--mark-teal)"
              fillOpacity={0.55}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="other"
              name="Other"
              stackId="intent"
              stroke="var(--mark-violet)"
              strokeWidth={1.5}
              fill="var(--mark-violet)"
              fillOpacity={0.55}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
