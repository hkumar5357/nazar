"""Walk-forward backtest (BRIEF §5.4) — the moment of truth.

At each backtest date T (first of the month, Jan 2025 → Jul 2026) every
feature and state is recomputed from data timestamped ≤ T (PROTOCOL R1).
States come from ``lifecycle.classify_trend`` — the freeze-guard entry
point — so demo trends are only ever scored with the frozen thresholds
(R3). This module is the FIRST code path that scores demo categories, and
it exists only in commits that descend from the ``m1-freeze`` tag.

Two honesty mechanics worth spelling out:

- **Real data only.** The backtest reads real-provenance pulls exclusively
  (currently Google Trends; Reddit/YouTube join when API keys arrive and
  real pulls exist). Its artifacts therefore carry
  ``contains_fixture_data: false`` and are final-presentable. Nothing
  fixture-derived can leak in here.

- **Weekly flag history via the invariance property.** tests/test_features.py
  proves bit-for-bit that features at week w computed on a series truncated
  at w equal the features at w computed on the full series; every window in
  ``lifecycle.classify_series`` is likewise trailing/expanding-only. The
  weekly state series computed once on the full panel is therefore
  IDENTICAL to a week-by-week walk-forward — that is what makes the weekly
  first-Heating date an honest point-in-time flag date, at weekly rather
  than monthly resolution. The monthly table below additionally recomputes
  everything from truncated data at each T, exercising the machinery
  end-to-end rather than trusting the proof.

Artifacts (``data/backtest/``, committed; no generation timestamps inside,
so a clean-clone rerun reproduces them byte-for-byte):

- ``state_timeline.json``   trend × month states + feature snapshots
- ``first_flags.json``      first Heating week per trend + censoring notes
- ``lead_times.json``       per locked event: event_date − first_heating
- ``goldenthread_chart.json`` matcha weekly composite + states + events

Entry point: ``python -m pipeline.backtest`` (logged to runs/, R4).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from pipeline import features, lifecycle, provenance, runlog
from pipeline.ingest.news_events import load_events
from pipeline.trends_config import DEMO_TRENDS

BACKTEST_DIR = runlog.REPO_ROOT / "data" / "backtest"

BACKTEST_START = datetime.date(2025, 1, 1)
BACKTEST_END = datetime.date(2026, 7, 1)


def month_starts(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    out, cur = [], start.replace(day=1)
    while cur <= end:
        out.append(cur)
        cur = (cur.replace(day=28) + datetime.timedelta(days=7)).replace(day=1)
    return out


def _round(x, nd=6):
    if x is None:
        return None
    try:
        if x != x:  # NaN
            return None
    except TypeError:
        return x
    return round(float(x), nd)


def _real_pulls(trend: str) -> dict:
    pulls = features.load_pulls(trend)
    return {s: p for s, p in pulls.items() if provenance.is_real(p.provenance)}


def _features_and_states(trend: str, pulls: dict, as_of=None):
    panel, prov_map = features.build_weekly_panel(pulls, as_of=as_of)
    feats = features.compute_features(panel)
    states = lifecycle.classify_trend(trend, feats)  # freeze guard (R3)
    return feats, states, prov_map


def run_backtest() -> dict:
    ts = month_starts(BACKTEST_START, BACKTEST_END)
    events = load_events()

    state_timeline: dict = {}
    first_flags: dict = {}
    provenance_blocks: dict = {}
    chart = None

    for trend in DEMO_TRENDS:
        pulls = _real_pulls(trend)
        if not pulls:
            raise SystemExit(f"no real-provenance pulls for {trend!r}")

        # Monthly walk-forward: recompute everything from truncated data.
        rows = []
        for T in ts:
            feats, states, _ = _features_and_states(trend, pulls, as_of=T)
            if len(states) == 0:
                rows.append({"T": T.isoformat(), "state": None, "features": None})
                continue
            last = feats.index[-1]
            f = feats.iloc[-1]
            rows.append(
                {
                    "T": T.isoformat(),
                    "week_scored": last.date().isoformat(),
                    "state": states.iloc[-1],
                    "features": {
                        "composite": _round(f["composite"]),
                        "n_sources": int(f["n_sources"]),
                        "velocity_8w": _round(f["velocity_8w"]),
                        "accel": _round(f["accel"]),
                        "peak_proximity": _round(f["peak_proximity"]),
                        "drawdown": _round(f["drawdown"]),
                        "breadth": int(f["breadth"]),
                    },
                }
            )
        state_timeline[trend] = rows

        # Weekly flag history on the full panel (= weekly walk-forward, by
        # the invariance property; see module docstring).
        feats_full, states_full, prov_map = _features_and_states(trend, pulls)
        provenance_blocks[trend] = provenance.summarize(prov_map)
        heating_weeks = [
            idx.date().isoformat()
            for idx, s in states_full.items()
            if s == "heating"
        ]
        in_window = [w for w in heating_weeks if w >= BACKTEST_START.isoformat()]
        determined = states_full[states_full != "undetermined"]
        first_classifiable = (
            determined.index[0].date().isoformat() if len(determined) else None
        )
        # Boundary censoring: history begins 2022-01 and the feature stack
        # needs ~20 weeks of warmup, so a trend that was ALREADY rising in
        # mid-2022 flags at (or within weeks of) the first classifiable
        # week. Such a flag date is a lower bound, not a detection date —
        # said out loud here and in every lead-time row derived from it.
        censored = bool(
            heating_weeks
            and first_classifiable
            and (
                datetime.date.fromisoformat(heating_weeks[0])
                - datetime.date.fromisoformat(first_classifiable)
            ).days
            <= 28
        )
        first_flags[trend] = {
            "first_heating_week": heating_weeks[0] if heating_weeks else None,
            "first_heating_week_in_backtest_window": (
                in_window[0] if in_window else None
            ),
            "heating_week_count": len(heating_weeks),
            "first_classifiable_week": first_classifiable,
            "boundary_censored": censored,
            "censoring_note": (
                "first Heating fires within 4 weeks of the first classifiable "
                "week: the trend was already building when the observation "
                "window opened (history starts 2022-01), so this flag date is "
                "a lower bound, not a detection date. The conservative "
                "in-window flag is reported alongside."
                if censored
                else None
            ),
        }

        if trend == "matcha":
            chart = {
                "trend": "matcha",
                "weekly": [
                    {
                        "week": idx.date().isoformat(),
                        "composite": _round(feats_full.loc[idx, "composite"]),
                        "state": states_full.loc[idx],
                    }
                    for idx in feats_full.index
                ],
                "heating_weeks": heating_weeks,
                "first_heating_week": first_flags[trend]["first_heating_week"],
                "events": [
                    {
                        "event_id": e["event_id"],
                        "event_name": e["event_name"],
                        "event_date": e["event_date"],
                        "source_url": e["source_url"],
                    }
                    for e in events
                    if e["trend"] == "matcha"
                ],
                "provenance": provenance_blocks[trend],
            }

    # Lead times: event_date minus the event's trend's first Heating flag.
    # Two variants, both reported (PROTOCOL C3 + §5 all-metrics rule):
    # - lead_days: vs the first flag EVER (boundary-censored lower bound
    #   when the trend was already building at window start)
    # - lead_days_conservative: vs the first flag inside the backtest
    #   window (Jan 2025+) — the number to quote when in doubt
    lead_times = []
    for e in events:
        ff = first_flags.get(e["trend"], {})
        flag = ff.get("first_heating_week")
        flag_cons = ff.get("first_heating_week_in_backtest_window")
        event_date = datetime.date.fromisoformat(e["event_date"])
        lead = (
            (event_date - datetime.date.fromisoformat(flag)).days if flag else None
        )
        lead_cons = (
            (event_date - datetime.date.fromisoformat(flag_cons)).days
            if flag_cons
            else None
        )
        lead_times.append(
            {
                "event_id": e["event_id"],
                "trend": e["trend"],
                "event_name": e["event_name"],
                "event_date": e["event_date"],
                "first_heating_week": flag,
                "lead_days": lead,
                "boundary_censored": ff.get("boundary_censored"),
                "first_heating_week_in_backtest_window": flag_cons,
                "lead_days_conservative": lead_cons,
            }
        )

    return {
        "state_timeline": {
            "backtest_dates": [t.isoformat() for t in ts],
            "trends": state_timeline,
            "provenance": provenance_blocks,
        },
        "first_flags": {"trends": first_flags, "provenance": provenance_blocks},
        "lead_times": {"events": lead_times, "provenance": provenance_blocks},
        "goldenthread_chart": chart,
    }


def main() -> int:
    with runlog.run("backtest", notes="walk-forward Jan 2025 - Jul 2026") as ctx:
        for trend in DEMO_TRENDS:
            for pull in _real_pulls(trend).values():
                ctx.add_input(pull.path)

        artifacts = run_backtest()

        # Final-presentability gate: these artifacts must be fixture-free.
        for trend, block in artifacts["state_timeline"]["provenance"].items():
            provenance.assert_all_real(block["sources"], context=f"backtest:{trend}")

        BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in artifacts.items():
            path = BACKTEST_DIR / f"{name}.json"
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            )
            ctx.add_output(path)
            print(f"[backtest] wrote {path.relative_to(runlog.REPO_ROOT)}")

        for trend, ff in artifacts["first_flags"]["trends"].items():
            print(f"[backtest] {trend}: first_heating={ff['first_heating_week']} "
                  f"({ff['heating_week_count']} heating weeks)")
        for lt in artifacts["lead_times"]["events"]:
            print(f"[backtest] lead {lt['event_id']}: {lt['lead_days']} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
