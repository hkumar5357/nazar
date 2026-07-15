/**
 * Client-side mirror of pipeline/launch_math.py — same formulas, documented
 * there and in the exported launch_math.json. The Python module embeds three
 * reference scenarios with expected outputs; verifyReferenceScenarios()
 * recomputes them here and any drift > 0.011 (float/rounding tolerance)
 * is surfaced in the UI as an error. Simulation on public benchmarks —
 * not a forecast.
 */

export interface LaunchInputs {
  price_inr: number;
  matcha_cost_per_g: number;
  matcha_g_per_serve: number;
  packaging_inr: number;
  copack_inr: number;
  qcom_commission_pct: number;
  cac_inr: number;
  repeat_rate_pct: number;
  orders_per_month_per_repeater: number;
}

export interface LaunchOutputs {
  cogs: number;
  net_revenue: number;
  contribution_per_order: number;
  payback_orders: number | null;
  payback_months: number | null;
}

const round2 = (x: number) => Math.round(x * 100) / 100;

export function compute(p: LaunchInputs): LaunchOutputs {
  const cogs =
    p.matcha_cost_per_g * p.matcha_g_per_serve + p.packaging_inr + p.copack_inr;
  const net_revenue = p.price_inr * (1 - p.qcom_commission_pct / 100);
  const contribution_per_order = net_revenue - cogs;
  let payback_orders: number | null = null;
  let payback_months: number | null = null;
  if (contribution_per_order > 0) {
    payback_orders = p.cac_inr / contribution_per_order;
    const repeatOrdersPerMonth =
      (p.repeat_rate_pct / 100) * p.orders_per_month_per_repeater;
    payback_months =
      repeatOrdersPerMonth > 0 ? payback_orders / repeatOrdersPerMonth : null;
  }
  return {
    cogs: round2(cogs),
    net_revenue: round2(net_revenue),
    contribution_per_order: round2(contribution_per_order),
    payback_orders: payback_orders === null ? null : round2(payback_orders),
    payback_months: payback_months === null ? null : round2(payback_months),
  };
}

export function verifyReferenceScenarios(
  scenarios: {
    name: string;
    params: Record<string, number>;
    outputs: Record<string, number | null>;
  }[]
): string[] {
  const mismatches: string[] = [];
  for (const s of scenarios) {
    const ours = compute(s.params as unknown as LaunchInputs);
    for (const [key, expected] of Object.entries(s.outputs)) {
      const got = (ours as unknown as Record<string, number | null>)[key];
      if (got === undefined) continue;
      const same =
        expected === null || got === null
          ? expected === got
          : Math.abs(expected - got) <= 0.011;
      if (!same) {
        mismatches.push(
          `${s.name}.${key}: python says ${expected}, client says ${got}`
        );
      }
    }
  }
  return mismatches;
}
