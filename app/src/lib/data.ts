/**
 * Typed loaders for the committed static JSON in /public/data.
 *
 * The dashboard reads ONLY these files — every chart is reproducible from
 * the repo alone. Each artifact carries a provenance block; anything with
 * contains_fixture_data: true triggers the persistent FixtureBanner
 * (no-fake-data rule: mock data is never presented as real).
 */

export interface ProvenanceBlock {
  sources: Record<string, string>;
  contains_fixture_data: boolean;
}

export interface FeatureSnapshot {
  composite: number | null;
  n_sources: number;
  velocity_8w: number | null;
  accel: number | null;
  peak_proximity: number | null;
  drawdown: number | null;
  breadth: number;
}

export interface TimelineRow {
  T: string;
  week_scored?: string;
  state: string | null;
  features: FeatureSnapshot | null;
}

export interface StateTimeline {
  backtest_dates: string[];
  trends: Record<string, TimelineRow[]>;
  provenance: Record<string, ProvenanceBlock>;
}

export interface FirstFlags {
  trends: Record<
    string,
    {
      first_heating_week: string | null;
      first_heating_week_in_backtest_window: string | null;
      heating_week_count: number;
      first_classifiable_week: string | null;
      boundary_censored: boolean;
      censoring_note: string | null;
    }
  >;
  provenance: Record<string, ProvenanceBlock>;
}

export interface LeadTimeRow {
  event_id: string;
  trend: string;
  event_name: string;
  event_date: string;
  first_heating_week: string | null;
  lead_days: number | null;
  boundary_censored: boolean | null;
  first_heating_week_in_backtest_window: string | null;
  lead_days_conservative: number | null;
}

export interface LeadTimes {
  events: LeadTimeRow[];
  provenance: Record<string, ProvenanceBlock>;
}

export interface GoldenThreadChart {
  trend: string;
  weekly: { week: string; composite: number | null; state: string }[];
  heating_weeks: string[];
  first_heating_week: string | null;
  events: {
    event_id: string;
    event_name: string;
    event_date: string;
    source_url: string;
  }[];
  provenance: ProvenanceBlock;
}

export interface IntentSplit {
  trend: string;
  weekly: {
    week: string;
    cafe_experience: number;
    home_or_CPG: number;
    other: number;
  }[];
  method_used: string;
  label_provenance: string;
  provenance: ProvenanceBlock;
}

export interface AffinityBoard {
  creators: {
    slug: string;
    name: string;
    niche: string;
    is_control: boolean;
    subscribers: number;
    engagement_factor: number;
    per_trend: Record<string, { rank: number; score: number }>;
  }[];
  validation: {
    check: string;
    expected: string;
    actual: string;
    pass: boolean;
  }[];
  method_note: string;
  provenance: ProvenanceBlock;
}

export interface LaunchMathParam {
  id: string;
  label: string;
  unit: string;
  default: number;
  min: number;
  max: number;
  step: number;
  source_note: string;
}

export interface LaunchMathData {
  banner: string;
  params: LaunchMathParam[];
  reference_scenarios: {
    name: string;
    params: Record<string, number>;
    outputs: Record<string, number | null>;
  }[];
  formulas: Record<string, string>;
  provenance: ProvenanceBlock;
  benchmarks_note: string;
}

export interface ProtocolData {
  markdown: string;
  thresholds_frozen: {
    frozen_at: string;
    calibration_trend: string;
    thresholds: Record<string, number>;
    grid_rank: number;
    grid_score: number;
    rule_clarifications: string[];
    rationale: string;
  } | null;
  coverage: {
    generated_at: string;
    coverage: Record<string, Record<string, Record<string, unknown> | null>>;
  } | null;
  qa_agreement: { agreement_rate: number; sample_size: number } | null;
  costs: {
    build_hours: number;
    api_spend_inr: number;
    notes?: string;
  } | null;
}

export interface AllData {
  stateTimeline: StateTimeline;
  firstFlags: FirstFlags;
  leadTimes: LeadTimes;
  goldenThread: GoldenThreadChart;
  intentSplit: IntentSplit;
  affinity: AffinityBoard;
  launchMath: LaunchMathData;
  protocol: ProtocolData;
}

async function fetchJson<T>(name: string): Promise<T> {
  const res = await fetch(`/data/${name}`);
  if (!res.ok) throw new Error(`failed to load ${name}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function loadAll(): Promise<AllData> {
  const [
    stateTimeline,
    firstFlags,
    leadTimes,
    goldenThread,
    intentSplit,
    affinity,
    launchMath,
    protocol,
  ] = await Promise.all([
    fetchJson<StateTimeline>("state_timeline.json"),
    fetchJson<FirstFlags>("first_flags.json"),
    fetchJson<LeadTimes>("lead_times.json"),
    fetchJson<GoldenThreadChart>("goldenthread_chart.json"),
    fetchJson<IntentSplit>("intent_split_matcha.json"),
    fetchJson<AffinityBoard>("affinity_board.json"),
    fetchJson<LaunchMathData>("launch_math.json"),
    fetchJson<ProtocolData>("protocol.json"),
  ]);
  return {
    stateTimeline,
    firstFlags,
    leadTimes,
    goldenThread,
    intentSplit,
    affinity,
    launchMath,
    protocol,
  };
}

/** Names of loaded artifacts that carry fixture-derived data (for the banner). */
export function fixtureFlagged(data: AllData): string[] {
  const flagged: string[] = [];
  const blocks: [string, ProvenanceBlock | Record<string, ProvenanceBlock>][] = [
    ["state timeline", data.stateTimeline.provenance],
    ["golden thread", data.goldenThread.provenance],
    ["intent split (labels)", data.intentSplit.provenance],
    ["creator affinity", data.affinity.provenance],
  ];
  for (const [name, block] of blocks) {
    const list =
      "sources" in block && typeof block.contains_fixture_data === "boolean"
        ? [block as ProvenanceBlock]
        : Object.values(block as Record<string, ProvenanceBlock>);
    if (list.some((b) => b.contains_fixture_data)) flagged.push(name);
  }
  return flagged;
}

export const STATE_COLORS: Record<string, string> = {
  emerging: "var(--state-emerging)",
  heating: "var(--state-heating)",
  peaked: "var(--state-peaked)",
  mature: "var(--state-mature)",
  undetermined: "var(--state-undetermined)",
};

export const STATE_LABELS: Record<string, string> = {
  emerging: "Emerging",
  heating: "Heating",
  peaked: "Peaked",
  mature: "Mature",
  undetermined: "Dormant / Undetermined",
};

export const TREND_LABELS: Record<string, string> = {
  matcha: "Matcha",
  protein_snacks: "Protein snacks",
  genz_fragrance: "Gen-Z fragrance",
};
