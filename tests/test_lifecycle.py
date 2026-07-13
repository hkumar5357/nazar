"""State-rule tests on synthetic in-memory feature frames.

Every frame here is MOCK synthetic data constructed in memory purely to
exercise the rule logic (no-fake-data rule: nothing is presented as real
and nothing is written to data/). Thresholds are arbitrary MOCK test
values, NOT the frozen calibration values — classify_series is
threshold-agnostic by design; the R3 freeze is enforced one level up in
classify_trend and tested in test_freeze_guard.py.
"""

import numpy as np
import pandas as pd

from pipeline.lifecycle import STATES, Thresholds, classify_series

# MOCK thresholds for rule-logic tests only (never a real calibration).
MOCK_TH = Thresholds(L1=0.5, L2=2.0, V0=0.05, V1=0.15, A1=-0.2)


def mock_features(composite, velocity_8w, accel, drawdown=0.0, breadth=0,
                  n_sources=3):
    """Build a MOCK feature frame with the exact feature column names.

    Scalars broadcast to the length of `composite`. peak_proximity is
    present because real feature frames carry it (BRIEF §5.2), though the
    state rules do not read it.
    """
    n = len(composite)

    def col(x):
        return list(x) if isinstance(x, (list, tuple, np.ndarray)) else [x] * n

    return pd.DataFrame(
        {
            "composite": col(composite),
            "velocity_8w": col(velocity_8w),
            "accel": col(accel),
            "peak_proximity": [1.0] * n,
            "drawdown": col(drawdown),
            "breadth": col(breadth),
            "n_sources": col(n_sources),
        },
        index=pd.date_range("2025-01-05", periods=n, freq="W"),
    )


def test_emerging_low_level_accelerating_ramp():
    # Low level (< L1), positive velocity, positive accel, velocity below
    # the heating floor V1 -> emerging every week.
    feats = mock_features(
        composite=[0.05 + 0.01 * t for t in range(30)],
        velocity_8w=0.03,
        accel=0.01,
        breadth=1,
    )
    states = classify_series(feats, MOCK_TH)
    assert (states == "emerging").all()
    assert states.index.equals(feats.index)
    assert set(states) <= set(STATES)


def test_heating_strong_rise_with_fresh_26w_high_and_breadth_2():
    # 20 flat weeks establish history, then a strong 10-week ramp: each ramp
    # week is a fresh 26-week high; velocity >= V1, accel >= 0, breadth 2.
    composite = [0.5] * 20 + [0.6, 0.8, 1.1, 1.4, 1.7, 2.0, 2.2, 2.4, 2.5, 2.6]
    feats = mock_features(
        composite=composite,
        velocity_8w=[0.0] * 20 + [0.3] * 10,
        accel=[0.0] * 20 + [0.1] * 10,
        breadth=[0] * 20 + [2] * 10,
    )
    states = classify_series(feats, MOCK_TH)
    assert states.iloc[-1] == "heating"
    # Flat prefix satisfies no rule -> shown honestly as undetermined.
    assert states.iloc[0] == "undetermined"


def test_heating_breadth_fallback_when_single_source():
    # With n_sources=1 the breadth requirement is min(2, 1) = 1, so a
    # single-source period can still reach Heating (pre-freeze clarification).
    composite = [0.5] * 20 + [0.6, 0.8, 1.1, 1.4, 1.7, 2.0, 2.2, 2.4, 2.5, 2.6]
    velocity = [0.0] * 20 + [0.3] * 10
    accel = [0.0] * 20 + [0.1] * 10

    single = mock_features(composite, velocity, accel,
                           breadth=[0] * 20 + [1] * 10, n_sources=1)
    assert classify_series(single, MOCK_TH).iloc[-1] == "heating"

    # Same breadth=1 with three sources available falls short of min(2, 3)=2.
    multi = mock_features(composite, velocity, accel,
                          breadth=[0] * 20 + [1] * 10, n_sources=3)
    assert classify_series(multi, MOCK_TH).iloc[-1] != "heating"


def test_heating_requires_fresh_26w_high():
    # Strong velocity but the composite plateaued 15 weeks ago: no new
    # 26-week high within the last 4 weeks -> not heating.
    composite = [0.5] * 10 + [0.6, 0.9, 1.3, 1.7, 2.1, 2.4, 2.6] + [2.6] * 15
    n = len(composite)
    feats = mock_features(
        composite=composite,
        velocity_8w=0.3,
        accel=0.1,
        breadth=2,
    )
    states = classify_series(feats, MOCK_TH)
    assert states.iloc[n - 1] == "undetermined"


def test_peaked_after_high_peak_with_drawdown_and_negative_velocity():
    # Rise to 2.5 (>= L2) by week 19, then decline to a 15% drawdown with
    # velocity <= 0 -> peaked.
    rise = [0.2 + 0.121 * t for t in range(20)]  # ends near 2.5
    decline = [2.45, 2.40, 2.35, 2.30, 2.25, 2.20, 2.16, 2.125]
    feats = mock_features(
        composite=rise + decline,
        velocity_8w=[0.3] * 20 + [-0.1] * 8,
        accel=[0.05] * 20 + [-0.1] * 8,
        drawdown=[0.0] * 20 + [0.02, 0.05, 0.08, 0.10, 0.12, 0.13, 0.14, 0.15],
        breadth=[2] * 20 + [0] * 8,
    )
    states = classify_series(feats, MOCK_TH)
    assert states.iloc[-1] == "peaked"


def test_peaked_via_strongly_negative_accel_at_high_level():
    # Second Peaked branch: accel <= A1 while composite still >= L2, even
    # with positive velocity and drawdown below the 5% band floor.
    rise = [0.2 + 0.121 * t for t in range(20)]
    feats = mock_features(
        composite=rise + [2.3],
        velocity_8w=[0.3] * 20 + [0.05],
        accel=[0.05] * 20 + [-0.5],
        drawdown=[0.0] * 20 + [0.03],
        breadth=2,
    )
    states = classify_series(feats, MOCK_TH)
    assert states.iloc[-1] == "peaked"


def test_mature_high_flat_for_12_weeks():
    # Ramp to a high level, then hold flat (|velocity| < V0) at >= L2.
    # Mature only fires once the flat-high run reaches 12 consecutive weeks.
    ramp = [0.5, 0.7, 0.9, 1.1, 1.3, 1.5, 1.7, 1.9, 2.1]
    plateau = [2.2] * 21  # weeks 9..29
    feats = mock_features(
        composite=ramp + plateau,
        velocity_8w=[0.2] * 9 + [0.0] * 21,
        accel=[0.05] * 9 + [0.0] * 21,
        breadth=0,
    )
    states = classify_series(feats, MOCK_TH)
    # Week 15: flat-high run is only 7 weeks -> not yet mature.
    assert states.iloc[15] == "undetermined"
    # Week 20: run reaches 12 -> mature from here on.
    assert states.iloc[20] == "mature"
    assert states.iloc[-1] == "mature"


def test_nan_warmup_is_undetermined():
    # Warmup: composite NaN for 3 weeks, velocity/accel NaN for 8 weeks
    # (as expanding z-scores and trailing slopes produce). Any NaN among
    # composite/velocity_8w/accel -> undetermined, never a guessed state.
    n = 20
    feats = mock_features(
        composite=[np.nan] * 3 + [0.1 + 0.01 * t for t in range(n - 3)],
        velocity_8w=[np.nan] * 8 + [0.03] * (n - 8),
        accel=[np.nan] * 8 + [0.01] * (n - 8),
        breadth=1,
    )
    states = classify_series(feats, MOCK_TH)
    assert (states.iloc[:8] == "undetermined").all()
    # Once all inputs are present this low accelerating ramp is emerging.
    assert states.iloc[-1] == "emerging"


def test_precedence_collision_resolves_to_peaked():
    # A week where BOTH mature_raw and peaked_raw hold: composite has sat
    # flat-high (>= L2, |velocity| < V0) for well over 12 weeks, but it got
    # there by declining ~12.5% from an earlier >= L2 peak with velocity <= 0.
    # Precedence peaked > mature must pick peaked.
    rise = [0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
    plateau = [2.1] * 20  # weeks 10..29: drawdown (2.4-2.1)/2.4 = 0.125
    feats = mock_features(
        composite=rise + plateau,
        velocity_8w=[0.2] * 10 + [-0.01] * 20,
        accel=[0.05] * 10 + [0.0] * 20,
        drawdown=[0.0] * 10 + [0.125] * 20,
        breadth=0,
    )
    states = classify_series(feats, MOCK_TH)
    assert states.iloc[-1] == "peaked"

    # Same frame with drawdown outside the 5-30% band: peaked_raw no longer
    # fires and the very same week classifies as mature — proving the
    # collision above was resolved by precedence, not by mature never firing.
    no_drawdown = feats.copy()
    no_drawdown["drawdown"] = 0.02
    assert classify_series(no_drawdown, MOCK_TH).iloc[-1] == "mature"


def test_missing_columns_rejected():
    feats = mock_features([0.1] * 10, 0.0, 0.0).drop(columns=["breadth"])
    try:
        classify_series(feats, MOCK_TH)
    except ValueError as e:
        assert "breadth" in str(e)
    else:
        raise AssertionError("expected ValueError for missing column")
