"""Parameterized launch-economics simulator for a hypothetical RTD-matcha
launch (BRIEF §5.6). Emits app/public/data/launch_math.json for the
dashboard's Math screen.

This module has no data-provenance problem in the R1-R4 sense: it pulls no
raw signal, runs no lifecycle math, and touches nothing PROTOCOL R5 governs
(no LLM anywhere in this file). Every input is a *parameter*, not a
measurement -- each default is a public benchmark RANGE stated honestly in
its own `source_note` (a range, not a fabricated citation to a specific
report). Because it is a simulation and not an estimate fit to real sales
data, the output is PERMANENTLY bannered "Simulation on public benchmarks --
not a forecast" (see BANNER below) regardless of how the sliders are set.

Formulas (all outputs rounded via round(x, 2)):

    cogs = matcha_cost_per_g * matcha_g_per_serve + packaging_inr + copack_inr
    net_revenue = price_inr * (1 - qcom_commission_pct / 100)
    contribution_per_order = net_revenue - cogs
    payback_orders = cac_inr / contribution_per_order
        -> None if contribution_per_order <= 0 (CAC is never recovered by a
           unit economics that loses money on every order)
    payback_months = payback_orders / (repeat_rate_pct/100 * orders_per_month_per_repeater)
        -> None whenever payback_orders is None.
        SIMPLIFICATION, stated plainly: this treats the repeat-purchase
        cohort as if it were the entire paying base placing
        orders_per_month_per_repeater orders every month from month one. It
        is a cohort-level payback approximation, not a full LTV model with
        cohort ramp-up, churn, or first-purchase-vs-repeat timing. Good
        enough for "is this even in the right order of magnitude", not for
        a real payback curve.

REFERENCE_SCENARIOS below is the cross-check: the React app recomputes
these three named scenarios client-side from the same PARAMS and formulas,
and its numbers must match the `outputs` embedded here exactly. A module
self-check (`_check_reference_scenarios`) enforces that at import time so
the two can never silently drift apart in this repo.

Entry point: `python -m pipeline.launch_math` (wrapped in runlog.run, R4).
Output bytes are deterministic: no generation timestamp inside the JSON,
fixed key ordering (dict insertion order), floats rounded via round(x, 2)
in compute() (the JSON has no unrounded floats to round(x, 6) further).
"""

from __future__ import annotations

import json
import sys

from pipeline import provenance, runlog

APP_DATA = runlog.REPO_ROOT / "app" / "public" / "data"
OUTPUT_PATH = APP_DATA / "launch_math.json"

BANNER = "Simulation on public benchmarks — not a forecast."

# ---------------------------------------------------------------------------
# PARAMS: every slider the dashboard exposes. Each `source_note` states a
# public benchmark RANGE (BRIEF §5.6), never a fabricated point citation.
# ---------------------------------------------------------------------------
PARAMS = [
    {
        "id": "price_inr",
        "label": "RTD price per bottle",
        "unit": "₹/bottle",
        "default": 150,
        "min": 120,
        "max": 180,
        "step": 5,
        "source_note": (
            "RTD (ready-to-drink) matcha beverages on Indian quick-commerce "
            "apps commonly list at ₹120-180 per bottle (public benchmark "
            "range, comparable RTD tea/coffee category pricing)."
        ),
    },
    {
        "id": "matcha_cost_per_g",
        "label": "Matcha cost per gram",
        "unit": "₹/g",
        "default": 4.5,
        "min": 3,
        "max": 6,
        "step": 0.5,
        "source_note": (
            "Import-grade culinary matcha lands at ₹3-6/g on Indian "
            "import/specialty-ingredient listings (public benchmark range, "
            "not a single supplier quote)."
        ),
    },
    {
        "id": "matcha_g_per_serve",
        "label": "Matcha grams per serve",
        "unit": "g/serve",
        "default": 2,
        "min": 1.5,
        "max": 3,
        "step": 0.25,
        "source_note": (
            "2 g of matcha powder per ~250 ml serve is a common café/RTD "
            "dosing convention (public benchmark range, not a lab-measured "
            "recipe)."
        ),
    },
    {
        "id": "packaging_inr",
        "label": "Packaging cost per unit",
        "unit": "₹/unit",
        "default": 20,
        "min": 15,
        "max": 25,
        "step": 1,
        "source_note": (
            "Bottle, label, and cap for a small-batch RTD beverage in India "
            "commonly runs ₹15-25 per unit (public benchmark range)."
        ),
    },
    {
        "id": "copack_inr",
        "label": "Co-packing / filling cost per unit",
        "unit": "₹/unit",
        "default": 12,
        "min": 8,
        "max": 20,
        "step": 1,
        "source_note": (
            "Contract co-packing/filling for a small-batch beverage run "
            "commonly benchmarks ₹8-20 per unit (public benchmark range; "
            "varies with batch size and contract terms, neither observed "
            "here)."
        ),
    },
    {
        "id": "qcom_commission_pct",
        "label": "Quick-commerce commission",
        "unit": "%",
        "default": 30,
        "min": 25,
        "max": 35,
        "step": 1,
        "source_note": (
            "Indian quick-commerce platforms commonly take a 25-35% "
            "commission on listed price (public benchmark range across "
            "platforms and categories)."
        ),
    },
    {
        "id": "cac_inr",
        "label": "Creator-led CAC",
        "unit": "₹/order",
        "default": 250,
        "min": 150,
        "max": 400,
        "step": 10,
        "source_note": (
            "Creator-led customer acquisition for F&B trial purchases in "
            "India commonly benchmarks ₹150-400 per order (public "
            "benchmark range). Noted for comparison, not modelled here: "
            "paid-performance CAC for comparable D2C F&B launches typically "
            "runs higher, often ₹400-800+, which is why creator-led "
            "acquisition is the default assumption for this simulator."
        ),
    },
    {
        "id": "repeat_rate_pct",
        "label": "Repeat purchase rate",
        "unit": "%",
        "default": 25,
        "min": 10,
        "max": 50,
        "step": 1,
        "source_note": (
            "Repeat-purchase rate within the observation period for a new "
            "D2C F&B product commonly benchmarks 10-50% (public benchmark "
            "range; wide because it is highly product- and cohort-"
            "dependent, not narrowed to matcha specifically)."
        ),
    },
    {
        "id": "orders_per_month_per_repeater",
        "label": "Orders per month per repeater",
        "unit": "orders/month",
        "default": 2,
        "min": 1,
        "max": 4,
        "step": 0.5,
        "source_note": (
            "Repeat buyers of a habitual beverage product typically place "
            "1-4 orders per month (public benchmark range for habitual "
            "F&B repeat cadence)."
        ),
    },
]

PARAM_IDS = [p["id"] for p in PARAMS]
PARAM_DEFAULTS = {p["id"]: p["default"] for p in PARAMS}

FORMULAS = {
    "cogs": (
        "cogs = matcha_cost_per_g * matcha_g_per_serve + packaging_inr + copack_inr"
    ),
    "net_revenue": "net_revenue = price_inr * (1 - qcom_commission_pct / 100)",
    "contribution_per_order": "contribution_per_order = net_revenue - cogs",
    "payback_orders": (
        "payback_orders = cac_inr / contribution_per_order "
        "(None if contribution_per_order <= 0 -- CAC can never be "
        "recovered by an order that loses money)"
    ),
    "payback_months": (
        "payback_months = payback_orders / (repeat_rate_pct/100 * "
        "orders_per_month_per_repeater) (None whenever payback_orders is "
        "None; SIMPLIFICATION -- treats the repeat cohort as the entire "
        "paying base placing orders_per_month_per_repeater orders/month, "
        "not a full cohort-decay/LTV model)"
    ),
}


def compute(params: dict) -> dict:
    """Run the launch-economics formulas documented in the module docstring.

    `params` must supply every id in PARAM_IDS (extra keys are ignored, so
    callers can pass a full slider-state dict straight through). Returns a
    dict with cogs, net_revenue, contribution_per_order, payback_orders,
    and payback_months, all rounded via round(x, 2). payback_orders and
    payback_months are None when contribution_per_order <= 0.
    """
    missing = [pid for pid in PARAM_IDS if pid not in params]
    if missing:
        raise ValueError(f"compute() missing required params: {missing}")

    matcha_cost_per_g = float(params["matcha_cost_per_g"])
    matcha_g_per_serve = float(params["matcha_g_per_serve"])
    packaging_inr = float(params["packaging_inr"])
    copack_inr = float(params["copack_inr"])
    price_inr = float(params["price_inr"])
    qcom_commission_pct = float(params["qcom_commission_pct"])
    cac_inr = float(params["cac_inr"])
    repeat_rate_pct = float(params["repeat_rate_pct"])
    orders_per_month_per_repeater = float(params["orders_per_month_per_repeater"])

    cogs = matcha_cost_per_g * matcha_g_per_serve + packaging_inr + copack_inr
    net_revenue = price_inr * (1 - qcom_commission_pct / 100)
    contribution_per_order = net_revenue - cogs

    if contribution_per_order <= 0:
        payback_orders = None
        payback_months = None
    else:
        payback_orders = cac_inr / contribution_per_order
        monthly_orders_per_repeater = (
            repeat_rate_pct / 100
        ) * orders_per_month_per_repeater
        payback_months = (
            payback_orders / monthly_orders_per_repeater
            if monthly_orders_per_repeater > 0
            else None
        )

    return {
        "cogs": round(cogs, 2),
        "net_revenue": round(net_revenue, 2),
        "contribution_per_order": round(contribution_per_order, 2),
        "payback_orders": round(payback_orders, 2) if payback_orders is not None else None,
        "payback_months": round(payback_months, 2) if payback_months is not None else None,
    }


# ---------------------------------------------------------------------------
# REFERENCE_SCENARIOS: three named full param sets with computed outputs
# embedded. The React dashboard recomputes these client-side from the same
# PARAMS/formulas and must match byte-for-byte on the numbers -- this is
# the cross-check that keeps the Python model and the JS slider math honest
# against each other. Unset params in each scenario fall back to PARAM_DEFAULTS.
# ---------------------------------------------------------------------------


def _scenario_params(overrides: dict) -> dict:
    p = dict(PARAM_DEFAULTS)
    p.update(overrides)
    return p


_DEFAULTS_PARAMS = _scenario_params({})
_LEAN_PARAMS = _scenario_params(
    {"price_inr": 120, "qcom_commission_pct": 35, "cac_inr": 400}
)
_FAVOURABLE_PARAMS = _scenario_params(
    {"price_inr": 180, "qcom_commission_pct": 25, "cac_inr": 150}
)

REFERENCE_SCENARIOS = [
    {
        "id": "defaults",
        "label": "Defaults",
        "description": "Every slider at its default value.",
        "params": _DEFAULTS_PARAMS,
        "outputs": compute(_DEFAULTS_PARAMS),
    },
    {
        "id": "lean",
        "label": "Lean (stress case)",
        "description": (
            "Low price, high commission, high CAC -- the pessimistic "
            "corner of the benchmark ranges."
        ),
        "params": _LEAN_PARAMS,
        "outputs": compute(_LEAN_PARAMS),
    },
    {
        "id": "favourable",
        "label": "Favourable",
        "description": (
            "High price, low commission, low CAC -- the optimistic corner "
            "of the benchmark ranges."
        ),
        "params": _FAVOURABLE_PARAMS,
        "outputs": compute(_FAVOURABLE_PARAMS),
    },
]


def _check_reference_scenarios() -> None:
    """Enforce that every embedded scenario output matches a fresh
    compute() call on its own params, so REFERENCE_SCENARIOS can never
    silently drift from the formulas above (the React cross-check assumes
    this holds)."""
    for scenario in REFERENCE_SCENARIOS:
        recomputed = compute(scenario["params"])
        if recomputed != scenario["outputs"]:
            raise AssertionError(
                f"REFERENCE_SCENARIOS[{scenario['id']!r}] outputs "
                f"{scenario['outputs']} do not match compute() "
                f"{recomputed}"
            )


_check_reference_scenarios()


def build_output() -> dict:
    """Assemble the deterministic JSON payload written to
    app/public/data/launch_math.json. No generation timestamp is embedded
    (R4 run metadata, including timing, lives in runs/ instead)."""
    return {
        "banner": BANNER,
        "params": PARAMS,
        "reference_scenarios": REFERENCE_SCENARIOS,
        "formulas": FORMULAS,
        # The simulator consumes no pipeline data at all — no raw pulls, no
        # fixtures — so its provenance block has an empty source map (and
        # therefore contains_fixture_data: false). The defaults are
        # author-asserted public benchmark RANGES stated in each param's
        # source_note; they are assumptions, not measurements, which is why
        # the banner above is permanent and non-negotiable.
        "provenance": provenance.summarize({}),
        "benchmarks_note": (
            "All defaults are author-asserted public benchmark ranges "
            "(see each param's source_note), not measured data."
        ),
    }


def main(argv=None) -> int:
    with runlog.run(
        "launch_math",
        notes="parameterized RTD-matcha launch-economics simulator (BRIEF §5.6)",
    ) as ctx:
        output = build_output()
        APP_DATA.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        )
        ctx.add_output(OUTPUT_PATH)
        ctx.set("reference_scenarios", [s["id"] for s in REFERENCE_SCENARIOS])
        print(f"[launch_math] wrote {OUTPUT_PATH.relative_to(runlog.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
