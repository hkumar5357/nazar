"""Freeze-guard tests — PROTOCOL R3's enforcement point.

classify_trend is what makes the m1-freeze ordering real in code: demo
trends cannot be scored before pipeline/thresholds_frozen.json exists, and
can never be scored with ad-hoc thresholds afterwards. Only the
calibration trend (korean_skincare) may take explicit thresholds, because
calibration IS the act of exploring the grid on that one trend.

All tests monkeypatch lifecycle.FROZEN_PATH into tmp_path so the repo's
real freeze file (if/when it exists) is never read or written. Frames and
threshold values are MOCK synthetic test data, never presented as real.
"""

import json

import pandas as pd
import pytest

from pipeline import lifecycle
from pipeline.lifecycle import FreezeGuardError, Thresholds

# MOCK threshold sets for tests only. With MOCK_TH_EMERGING (L1=0.5) the
# frame below classifies as emerging everywhere; with MOCK_TH_STRICT
# (L1=-1.0, an impossible ceiling) the same frame is all undetermined —
# so the resulting states reveal which threshold set was actually used.
MOCK_TH_EMERGING = Thresholds(L1=0.5, L2=2.0, V0=0.05, V1=0.15, A1=-0.2)
MOCK_TH_STRICT = Thresholds(L1=-1.0, L2=2.0, V0=0.05, V1=0.15, A1=-0.2)


def mock_features(n=16):
    """MOCK in-memory frame: a low, gently accelerating ramp."""
    return pd.DataFrame(
        {
            "composite": [0.1 + 0.01 * t for t in range(n)],
            "velocity_8w": [0.02] * n,
            "accel": [0.01] * n,
            "peak_proximity": [1.0] * n,
            "drawdown": [0.0] * n,
            "breadth": [1] * n,
            "n_sources": [3] * n,
        }
    )


def write_frozen(path, thresholds):
    """Write a MOCK freeze file in the real {"thresholds": ...} layout."""
    path.write_text(
        json.dumps(
            {
                "thresholds": thresholds.to_dict(),
                "frozen_at": "2026-07-13T00:00:00+05:30",
                "calibration_trend": "korean_skincare",
                "note": "MOCK freeze file for tests only — not a real calibration",
            },
            indent=2,
        )
    )


@pytest.fixture
def frozen_path(monkeypatch, tmp_path):
    """Point lifecycle.FROZEN_PATH at a tmp file (which does not exist yet)."""
    path = tmp_path / "thresholds_frozen.json"
    monkeypatch.setattr(lifecycle, "FROZEN_PATH", path)
    return path


def test_no_freeze_file_blocks_demo_trend(frozen_path):
    with pytest.raises(FreezeGuardError, match="R3"):
        lifecycle.classify_trend("matcha", mock_features())


def test_no_freeze_file_load_frozen_raises(frozen_path):
    with pytest.raises(FreezeGuardError, match="R3"):
        lifecycle.load_frozen()


def test_no_freeze_file_calibration_trend_takes_explicit_thresholds(frozen_path):
    # Calibration must be possible BEFORE the freeze exists — that is the
    # whole point of the m1-freeze ordering.
    states = lifecycle.classify_trend(
        "korean_skincare", mock_features(), thresholds=MOCK_TH_EMERGING
    )
    assert len(states) == 16
    assert (states == "emerging").all()


def test_frozen_demo_trend_scores_with_frozen_values(frozen_path):
    write_frozen(frozen_path, MOCK_TH_EMERGING)
    states = lifecycle.classify_trend("matcha", mock_features())
    assert (states == "emerging").all()


def test_frozen_demo_trend_rejects_explicit_thresholds(frozen_path):
    write_frozen(frozen_path, MOCK_TH_EMERGING)
    # Even thresholds IDENTICAL to the frozen set are refused: the API for
    # demo trends simply has no threshold parameter in practice.
    with pytest.raises(
        ValueError, match="per-category thresholds are forbidden"
    ):
        lifecycle.classify_trend(
            "matcha", mock_features(), thresholds=MOCK_TH_EMERGING
        )


def test_frozen_calibration_trend_none_falls_back_to_frozen(frozen_path):
    # Freeze the STRICT set (emerging impossible). korean_skincare with
    # thresholds=None must pick it up -> all undetermined; with explicit
    # thresholds it still explores the grid -> emerging.
    write_frozen(frozen_path, MOCK_TH_STRICT)
    from_frozen = lifecycle.classify_trend("korean_skincare", mock_features())
    assert (from_frozen == "undetermined").all()

    explicit = lifecycle.classify_trend(
        "korean_skincare", mock_features(), thresholds=MOCK_TH_EMERGING
    )
    assert (explicit == "emerging").all()


def test_thresholds_roundtrip():
    d = MOCK_TH_EMERGING.to_dict()
    assert d == {"L1": 0.5, "L2": 2.0, "V0": 0.05, "V1": 0.15, "A1": -0.2}
    assert Thresholds.from_dict(d) == MOCK_TH_EMERGING
