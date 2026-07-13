"""Threshold calibration on the held-out calibration trend ONLY (PROTOCOL R3).

Calibration chooses the lifecycle cutoffs (L1, L2, V0, V1, A1) so that the
calibration trend's KNOWN arc — Korean skincare in India: explosive 2022-23,
mature/plateau by 2025 (BRIEF §5.3) — is reproduced. The expected arc below
was written down from that prior BEFORE any feature values were inspected;
it is scored mechanically over a small grid, the top candidates are printed
for human inspection, and the chosen combo is frozen to
pipeline/thresholds_frozen.json. After the `m1-freeze` tag, the cutoffs never
change (a re-freeze on richer real data gets a new tag + dated amendment).

Rules this module enforces:
- Calibration reads REAL-provenance pulls only. Thresholds are never
  calibrated on MOCK_ fixtures.
- Only the calibration trend is ever scored here (the freeze guard in
  lifecycle.py additionally blocks demo trends until the freeze file exists).

Usage:
    python -m pipeline.calibrate                    # score grid, print top 5
    python -m pipeline.calibrate --freeze N --rationale "..."   # freeze combo N
"""

from __future__ import annotations

import argparse
import datetime
import itertools
import json
import sys

from pipeline import features, lifecycle, provenance, runlog
from pipeline.trends_config import CALIBRATION_TREND

# ---------------------------------------------------------------------------
# Pre-registered expected arc (from the BRIEF's stated prior, not from data):
#   - Heating must fire at least once in 2022-07-01 .. 2023-12-31
#   - By 2025 the trend is mature/plateau: most complete weeks in
#     2025-01-01 .. 2026-06-30 should classify Mature
#   - Heating firing in 2026 contradicts the known plateau -> penalty
# ---------------------------------------------------------------------------
HEATING_WINDOW = ("2022-07-01", "2023-12-31")
MATURE_WINDOW = ("2025-01-01", "2026-06-30")
LATE_HEATING_FROM = "2026-01-01"

GRID = {
    "L1": [0.3, 0.5, 0.8, 1.0],
    "L2": [0.8, 1.0, 1.2, 1.5],
    "V0": [0.01, 0.02, 0.03, 0.05],
    "V1": [0.05, 0.08, 0.10, 0.15],
    "A1": [-0.05, -0.08, -0.12],
}


def score_states(states) -> dict:
    """Mechanical agreement score against the pre-registered arc (max 90):
    40 for Heating firing inside its window, up to 50 for the Mature share
    of 2025-26 weeks, minus up to 20 for contradictory Heating in 2026."""
    idx = states.index

    def window(lo, hi):
        return states[(idx >= lo) & (idx <= hi)]

    heating_w = window(*HEATING_WINDOW)
    mature_w = window(*MATURE_WINDOW)
    late = states[idx >= LATE_HEATING_FROM]

    heating_fired = bool((heating_w == "heating").any())
    mature_share = float((mature_w == "mature").mean()) if len(mature_w) else 0.0
    late_heating_weeks = int((late == "heating").sum())

    score = (
        40.0 * heating_fired
        + 50.0 * mature_share
        - min(2.0 * late_heating_weeks, 20.0)
    )
    return {
        "score": round(score, 2),
        "heating_fired_in_window": heating_fired,
        "first_heating": str(states[states == "heating"].index.min().date())
        if (states == "heating").any()
        else None,
        "mature_share_2025_26": round(mature_share, 3),
        "late_heating_weeks_2026": late_heating_weeks,
    }


def state_year_table(states) -> dict:
    """Compact per-year state counts for human inspection."""
    out = {}
    for year, sub in states.groupby(states.index.year):
        counts = sub.value_counts().to_dict()
        out[int(year)] = {k: int(v) for k, v in sorted(counts.items())}
    return out


def load_calibration_features():
    """Features for the calibration trend from REAL pulls only."""
    pulls = features.load_pulls(CALIBRATION_TREND)
    real = {s: p for s, p in pulls.items() if provenance.is_real(p.provenance)}
    dropped = sorted(set(pulls) - set(real))
    if not real:
        raise SystemExit(
            "calibration requires at least one REAL-provenance pull for "
            f"{CALIBRATION_TREND}; found none (fixtures are never calibrated on)"
        )
    panel, prov_map = features.build_weekly_panel(real)
    feats = features.compute_features(panel)
    return feats, real, prov_map, dropped


def run_grid(feats):
    results = []
    for L1, L2, V0, V1, A1 in itertools.product(
        GRID["L1"], GRID["L2"], GRID["V0"], GRID["V1"], GRID["A1"]
    ):
        if L1 >= L2:
            continue
        th = lifecycle.Thresholds(L1=L1, L2=L2, V0=V0, V1=V1, A1=A1)
        states = lifecycle.classify_series(feats, th)
        res = score_states(states)
        results.append({"thresholds": th.to_dict(), **res})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", type=int, metavar="N",
                    help="freeze the N-th ranked combo (1-based) from this grid run")
    ap.add_argument("--rationale", type=str, default="",
                    help="human rationale recorded in thresholds_frozen.json")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args(argv)

    if args.freeze and not args.rationale:
        ap.error("--freeze requires --rationale (the freeze file records why)")

    with runlog.run("calibrate", notes="grid calibration on " + CALIBRATION_TREND) as ctx:
        feats, real_pulls, prov_map, dropped = load_calibration_features()
        for p in real_pulls.values():
            ctx.add_input(p.path)
        ctx.set("provenance", prov_map)
        ctx.set("dropped_fixture_sources", dropped)
        if dropped:
            print(f"NOTE: ignored fixture-provenance sources: {dropped}\n")

        results = run_grid(feats)
        ctx.set("grid_size", len(results))
        grid_path = ctx.dir / "grid_results.json"
        grid_path.write_text(json.dumps(results, indent=2) + "\n")
        ctx.add_output(grid_path)

        print(f"grid: {len(results)} combos scored on {CALIBRATION_TREND} "
              f"(real sources: {sorted(real_pulls)})\n")
        for rank, res in enumerate(results[: args.top], start=1):
            th = lifecycle.Thresholds.from_dict(res["thresholds"])
            states = lifecycle.classify_series(feats, th)
            print(f"#{rank}  score={res['score']}  {res['thresholds']}")
            print(f"    first_heating={res['first_heating']}  "
                  f"mature_share_2025_26={res['mature_share_2025_26']}  "
                  f"late_heating_2026={res['late_heating_weeks_2026']}")
            print(f"    per-year states: {json.dumps(state_year_table(states))}\n")

        if args.freeze:
            chosen = results[args.freeze - 1]
            frozen = {
                "frozen_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).astimezone().isoformat(),
                "calibration_trend": CALIBRATION_TREND,
                "calibration_inputs": [
                    {
                        "path": str(p.path.relative_to(runlog.REPO_ROOT)),
                        "sha256": runlog.sha256_file(p.path),
                        "provenance": p.provenance,
                    }
                    for p in real_pulls.values()
                ],
                "thresholds": chosen["thresholds"],
                "grid_rank": args.freeze,
                "grid_score": chosen["score"],
                "rules_version": "v1",
                "rule_clarifications": [
                    "state precedence: peaked > heating > mature > emerging > undetermined",
                    "breadth requirement is min(2, n_sources) (single-source reality pre-keys)",
                    "peaked requires the expanding max composite to have reached L2 before now",
                    "A1 quantifies 'strongly negative accel'; 'high level' means composite >= L2",
                    "peak_proximity/drawdown computed on min-shifted composite (z can be negative)",
                ],
                "rationale": args.rationale,
            }
            lifecycle.FROZEN_PATH.write_text(json.dumps(frozen, indent=2) + "\n")
            ctx.add_output(lifecycle.FROZEN_PATH)
            print(f"FROZEN -> {lifecycle.FROZEN_PATH}")
            print("Next: commit + tag m1-freeze BEFORE scoring any demo trend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
