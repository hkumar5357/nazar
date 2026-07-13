"""Lifecycle state rules and the threshold-freeze guard (PROTOCOL R3).

This module turns a weekly feature frame (features.py, BRIEF §5.2) into a
lifecycle state per week, and enforces the single most important honesty
mechanism in NAZAR: demo trends can only ever be scored with the frozen
thresholds.

Protocol constraints implemented here:

- R1 (point-in-time): ``classify_series`` uses only expanding/trailing
  information at each week. The "new 26-week high" check looks strictly
  backwards, the Peaked rule requires the peak to have occurred strictly
  before the week being classified, and the Mature rule counts consecutive
  weeks ending at the current week. Nothing at week t sees week t+1.
- R3 (threshold freeze): ``classify_trend`` is the enforcement point.
  Thresholds are calibrated ONLY on the calibration trend (korean_skincare)
  and frozen to ``pipeline/thresholds_frozen.json`` at the m1-freeze commit.
  Before that file exists, scoring any demo trend raises FreezeGuardError;
  after it exists, passing explicit thresholds for a demo trend raises
  ValueError. Per-category tuning is therefore impossible by construction.
- R5 (LLM boundary): states come from time-series arithmetic only. No LLM
  output enters this module.
- R4 (run logging) is owned by the pipeline entry points (backtest,
  calibrate) via pipeline.runlog; the functions here are pure.

Pre-freeze rule clarifications (vs BRIEF §5.3), to be recorded as dated
PROTOCOL amendments at M1:

1. "accel strongly negative" in the Peaked rule is quantified as a
   calibrated threshold A1 (a negative number): ``accel <= A1``.
2. The Heating breadth requirement is ``breadth >= min(2, n_sources)`` so
   that periods where only one source has coverage (e.g. pytrends-only,
   before API keys arrive) are not structurally barred from Heating.
3. "made >= 90% of all-time high earlier" in the Peaked rule is replaced by
   a peak-height requirement: the expanding max of the composite must have
   reached >= L2 at some week strictly before t. (Any all-time high is
   trivially at 100% of itself; the L2 floor makes "built a high peak"
   meaningful.)
4. Explicit precedence when several raw rules fire on the same week:
   peaked > heating > mature > emerging > undetermined.

Structural constants (26-week high window, 4-week recency, 12-week Mature
run, 5-30% drawdown band, >= 8 prior weeks of history) are part of the
pre-registered rule *forms* from BRIEF §5.3 and are not calibrated; only
L1, L2, V0, V1, A1 are calibrated and frozen.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import trends_config

STATES = ("emerging", "heating", "peaked", "mature", "undetermined")

FROZEN_PATH = Path(__file__).parent / "thresholds_frozen.json"

# Feature columns classify_series needs (produced by features.py, BRIEF §5.2).
REQUIRED_COLUMNS = (
    "composite",
    "velocity_8w",
    "accel",
    "drawdown",
    "breadth",
    "n_sources",
)

# Pre-registered rule-form constants (BRIEF §5.3) — not calibrated, not frozen.
NEW_HIGH_WINDOW_WEEKS = 26  # "new 26-week high"
NEW_HIGH_MIN_HISTORY_WEEKS = 8  # prior weeks required before a high can count
HEATING_HIGH_LOOKBACK_WEEKS = 4  # new high must be within the last 4 weeks
MATURE_MIN_WEEKS = 12  # consecutive flat-high weeks required for Mature
PEAKED_DRAWDOWN_MIN = 0.05
PEAKED_DRAWDOWN_MAX = 0.30


class FreezeGuardError(RuntimeError):
    """Demo-trend scoring attempted without frozen thresholds (PROTOCOL R3)."""


@dataclass(frozen=True)
class Thresholds:
    """Calibrated lifecycle cutoffs — the five numbers frozen at m1-freeze.

    L1: emerging level ceiling (composite z units) — Emerging requires the
        composite to sit below L1.
    L2: high level floor — Mature and the Peaked peak-height requirement
        both demand the composite (or its earlier peak) at or above L2.
    V0: mature flatness band on |velocity| — Mature requires
        |velocity_8w| < V0.
    V1: heating velocity floor — Heating requires velocity_8w >= V1.
    A1: strongly-negative accel ceiling for Peaked (a negative number) —
        the "accel strongly negative at high level" branch fires when
        accel <= A1.
    """

    L1: float
    L2: float
    V0: float
    V1: float
    A1: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Thresholds":
        return cls(
            L1=float(d["L1"]),
            L2=float(d["L2"]),
            V0=float(d["V0"]),
            V1=float(d["V1"]),
            A1=float(d["A1"]),
        )


def load_frozen() -> Thresholds:
    """Read the frozen thresholds committed at m1-freeze.

    The file layout is {"thresholds": {...}} plus freeze metadata (date,
    calibration trend, rationale). Raises FreezeGuardError if the file does
    not exist yet — i.e. before the m1-freeze commit — or is malformed.
    """
    if not FROZEN_PATH.exists():
        raise FreezeGuardError(
            f"frozen thresholds not found at {FROZEN_PATH}. PROTOCOL R3: "
            "thresholds are calibrated on the calibration trend only and "
            "frozen (the m1-freeze commit) before anything else is scored."
        )
    payload = json.loads(FROZEN_PATH.read_text())
    if "thresholds" not in payload:
        raise FreezeGuardError(
            f"malformed freeze file {FROZEN_PATH}: missing 'thresholds' key"
        )
    return Thresholds.from_dict(payload["thresholds"])


def _new_26w_high_flags(composite: np.ndarray) -> np.ndarray:
    """new26(k): composite[k] strictly exceeds the max of the prior 25 weeks.

    R1 discipline: only weeks strictly before k are consulted, and at least
    NEW_HIGH_MIN_HISTORY_WEEKS non-NaN prior weeks must exist inside the
    window — otherwise the first readings after warmup would trivially
    count as record highs.
    """
    n = len(composite)
    flags = np.zeros(n, dtype=bool)
    for k in range(n):
        if np.isnan(composite[k]):
            continue
        window = composite[max(0, k - (NEW_HIGH_WINDOW_WEEKS - 1)) : k]
        valid = window[~np.isnan(window)]
        if len(valid) < NEW_HIGH_MIN_HISTORY_WEEKS:
            continue
        flags[k] = composite[k] > valid.max()
    return flags


def _prior_peak_reached(composite: np.ndarray, level: float) -> np.ndarray:
    """True at week t if expanding_max(composite) reached >= level STRICTLY
    before t (R1: the running max is updated only after each week is flagged,
    so week t never counts its own value as the earlier peak)."""
    n = len(composite)
    flags = np.zeros(n, dtype=bool)
    running_max = -np.inf
    for t in range(n):
        flags[t] = running_max >= level
        if not np.isnan(composite[t]):
            running_max = max(running_max, composite[t])
    return flags


def _mature_flags(
    composite: np.ndarray, velocity: np.ndarray, th: Thresholds
) -> np.ndarray:
    """True at week t if composite >= L2 and |velocity_8w| < V0 held for
    >= MATURE_MIN_WEEKS consecutive weeks ending at t. A NaN week breaks
    the run (an unmeasured week cannot count as flat-high)."""
    n = len(composite)
    flags = np.zeros(n, dtype=bool)
    run = 0
    for t in range(n):
        c, v = composite[t], velocity[t]
        flat_high = (
            not np.isnan(c)
            and not np.isnan(v)
            and c >= th.L2
            and abs(v) < th.V0
        )
        run = run + 1 if flat_high else 0
        flags[t] = run >= MATURE_MIN_WEEKS
    return flags


def classify_series(features: pd.DataFrame, th: Thresholds) -> pd.Series:
    """Assign one lifecycle state per week from a feature frame.

    Uses only expanding/trailing information at each week (R1). Weeks where
    composite, velocity_8w, or accel is NaN are 'undetermined'. When several
    raw rules fire on the same week, precedence is
    peaked > heating > mature > emerging > undetermined.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in features.columns]
    if missing:
        raise ValueError(f"features frame is missing columns: {missing}")

    composite = features["composite"].to_numpy(dtype=float)
    velocity = features["velocity_8w"].to_numpy(dtype=float)
    accel = features["accel"].to_numpy(dtype=float)
    drawdown = features["drawdown"].to_numpy(dtype=float)
    breadth = features["breadth"].to_numpy(dtype=float)
    n_sources = features["n_sources"].to_numpy(dtype=float)

    new26 = _new_26w_high_flags(composite)
    prior_peak = _prior_peak_reached(composite, th.L2)
    mature = _mature_flags(composite, velocity, th)

    states = []
    for t in range(len(features)):
        c, v, a = composite[t], velocity[t], accel[t]
        if np.isnan(c) or np.isnan(v) or np.isnan(a):
            states.append("undetermined")
            continue

        lookback_start = max(0, t - (HEATING_HIGH_LOOKBACK_WEEKS - 1))
        new_high_recently = bool(new26[lookback_start : t + 1].any())

        heating_raw = (
            v >= th.V1
            and a >= 0
            and breadth[t] >= min(2.0, n_sources[t])
            and new_high_recently
        )
        peaked_raw = bool(prior_peak[t]) and (
            (v <= 0 and PEAKED_DRAWDOWN_MIN <= drawdown[t] <= PEAKED_DRAWDOWN_MAX)
            or (a <= th.A1 and c >= th.L2)
        )
        emerging_raw = c < th.L1 and v > 0 and a > 0

        if peaked_raw:
            states.append("peaked")
        elif heating_raw:
            states.append("heating")
        elif mature[t]:
            states.append("mature")
        elif emerging_raw:
            states.append("emerging")
        else:
            states.append("undetermined")

    return pd.Series(states, index=features.index, name="state")


def classify_trend(
    trend: str,
    features: pd.DataFrame,
    thresholds: Thresholds | None = None,
) -> pd.Series:
    """Classify one trend's feature frame — THE FREEZE GUARD (PROTOCOL R3).

    Calibration trend (korean_skincare): explicit thresholds are allowed,
    because calibration is exactly the act of exploring the threshold grid
    on this one trend; with thresholds=None it falls back to the frozen set.

    Any other trend (the demo categories): frozen thresholds only. If the
    freeze file does not exist yet, scoring is refused outright — the
    m1-freeze commit must exist before any demo-category scoring, and that
    git-visible ordering is the pre-registration proof. Passing explicit
    thresholds for a demo trend is refused even after the freeze, so
    per-category tuning is impossible by construction.
    """
    if trend == trends_config.CALIBRATION_TREND:
        th = thresholds if thresholds is not None else load_frozen()
        return classify_series(features, th)

    if not FROZEN_PATH.exists():
        raise FreezeGuardError(
            f"refusing to score trend {trend!r}: {FROZEN_PATH} does not "
            "exist. PROTOCOL R3 requires thresholds to be calibrated on the "
            f"calibration trend ({trends_config.CALIBRATION_TREND!r}) and "
            "frozen — the m1-freeze commit — BEFORE any demo category is "
            "scored. Run calibration and freeze first."
        )
    if thresholds is not None:
        raise ValueError(
            "per-category thresholds are forbidden (PROTOCOL R3): demo "
            "trends are always scored with the frozen thresholds"
        )
    return classify_series(features, load_frozen())
