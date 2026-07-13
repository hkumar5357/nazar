"""Tests for pipeline.features. Hermetic: all data is synthetic and
in-memory (Pull objects carry provenance='fixture' per the no-fake-data
rule; nothing touches data/ or the network).

The centerpiece is the no-lookahead test (PROTOCOL R1): features computed
on a panel truncated at week T must be EXACTLY the row-T features of the
full panel. If any statistic peeked past T, this test breaks.
"""

import datetime

import numpy as np
import pandas as pd
import pytest

from pipeline import features
from pipeline.ingest.base import Pull

TREND = "matcha"  # any slug from trends_config works; tests never read files


def sundays(start: str, n: int) -> pd.DatetimeIndex:
    """n consecutive weekly Sundays starting at `start` (a Sunday)."""
    return pd.date_range(start, periods=n, freq="7D", name="week_start")


def ts(iso: str) -> int:
    """Unix timestamp for an ISO-8601 instant (reddit created_utc style)."""
    return int(datetime.datetime.fromisoformat(iso).timestamp())


def make_synthetic_panel(n: int = 150, seed: int = 7) -> pd.DataFrame:
    """3-source weekly panel with varied shapes: ramp-then-plateau,
    rise-then-fall with NaN stretches, and a noisy random walk."""
    rng = np.random.default_rng(seed)
    idx = sundays("2022-01-02", n)
    t = np.arange(n, dtype=float)

    trends = 10.0 + 0.8 * t + 5.0 * np.sin(t / 6.0) + rng.normal(0.0, 1.5, n)
    if n > 120:
        trends[120:] = trends[119] + rng.normal(0.0, 1.0, n - 120)  # plateau

    reddit = np.where(t < 90, t ** 1.3, 90.0 ** 1.3 - 3.0 * (t - 90))
    reddit = reddit + rng.normal(0.0, 4.0, n)
    reddit[:10] = np.nan          # source starts late
    reddit[40:55] = np.nan        # mid-series outage

    youtube = 20.0 + np.cumsum(rng.normal(0.3, 2.0, n))

    return pd.DataFrame(
        {"trends": trends, "reddit": reddit, "youtube": youtube}, index=idx
    )


# ---------------------------------------------------------------------------
# THE invariant: no lookahead (PROTOCOL R1)
# ---------------------------------------------------------------------------


def test_no_lookahead_truncation_invariance():
    panel = make_synthetic_panel()
    full = features.compute_features(panel)

    cuts = [30, 45, 60, 75, 90, 105, 115, 125, 140, 149]  # 45 = inside NaN gap
    assert len(cuts) >= 10
    for k in cuts:
        trunc = features.compute_features(panel.iloc[: k + 1])
        # The row at the cut is bit-for-bit identical (NaNs align too)...
        pd.testing.assert_series_equal(
            trunc.iloc[k], full.iloc[k], check_exact=True
        )
        # ...and so is every earlier row.
        pd.testing.assert_frame_equal(
            trunc, full.iloc[: k + 1], check_exact=True, check_freq=False
        )


def test_compute_features_as_of_equals_truncation():
    panel = make_synthetic_panel(n=60)
    k = 40
    as_of = (panel.index[k] + pd.Timedelta(days=6)).date()  # end of week k
    via_as_of = features.compute_features(panel, as_of=as_of)
    via_slice = features.compute_features(panel.iloc[: k + 1])
    assert len(via_as_of) == k + 1
    pd.testing.assert_frame_equal(
        via_as_of, via_slice, check_exact=True, check_freq=False
    )


def test_compute_features_as_of_mid_week_drops_incomplete_week():
    panel = make_synthetic_panel(n=20)
    # One day before week 10 ends -> week 10 must not appear.
    as_of = (panel.index[10] + pd.Timedelta(days=5)).date()
    out = features.compute_features(panel, as_of=as_of)
    assert out.index[-1] == panel.index[9]


# ---------------------------------------------------------------------------
# expanding_z
# ---------------------------------------------------------------------------


def test_expanding_z_hand_computed():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = features.expanding_z(s, min_history=3)
    assert z.iloc[:2].isna().all()
    # t=2: mean(1,2,3)=2, std=1        -> (3-2)/1
    assert z.iloc[2] == pytest.approx(1.0)
    # t=3: mean=2.5, std=sqrt(5/3)     -> 1.5/sqrt(5/3)
    assert z.iloc[3] == pytest.approx(1.5 / np.sqrt(5.0 / 3.0))
    # t=4: mean=3, std=sqrt(2.5)       -> 2/sqrt(2.5)
    assert z.iloc[4] == pytest.approx(2.0 / np.sqrt(2.5))


def test_expanding_z_default_min_history_is_8():
    s = pd.Series(np.arange(12.0))
    z = features.expanding_z(s)
    assert z.iloc[:7].isna().all()
    assert z.iloc[7:].notna().all()


def test_expanding_z_flat_series_is_nan():
    z = features.expanding_z(pd.Series([5.0] * 20), min_history=3)
    assert z.isna().all()  # std <= 1e-9 everywhere


def test_expanding_z_nan_observations_do_not_count_toward_history():
    s = pd.Series([1.0, 2.0, np.nan, 3.0, 4.0])
    z = features.expanding_z(s, min_history=3)
    assert np.isnan(z.iloc[2])  # NaN input -> NaN output
    # t=3 is only the 3rd observation; mean(1,2,3)=2, std=1 -> z=1.
    assert z.iloc[3] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# trailing_slope / velocity / accel
# ---------------------------------------------------------------------------


def test_trailing_slope_recovers_ramp_exactly():
    s = pd.Series(0.5 * np.arange(30.0), index=sundays("2022-01-02", 30))
    slopes = features.trailing_slope(s)
    assert slopes.iloc[:7].isna().all()  # no full 8-week window yet
    np.testing.assert_allclose(slopes.iloc[7:], 0.5, rtol=1e-12)


def test_trailing_slope_min_points_rule():
    values = 0.5 * np.arange(20.0)
    values[10:12] = np.nan
    s = pd.Series(values)
    slopes = features.trailing_slope(s)
    # Window 5..12 has 6 non-NaN points -> defined, slope still exact.
    assert slopes.iloc[12] == pytest.approx(0.5, rel=1e-12)

    values3 = 0.5 * np.arange(20.0)
    values3[9:12] = np.nan
    slopes3 = features.trailing_slope(pd.Series(values3))
    # Window 5..12 has only 5 non-NaN points -> NaN.
    assert np.isnan(slopes3.iloc[12])


def test_velocity_positive_on_pure_ramp_panel():
    panel = pd.DataFrame(
        {"trends": np.arange(40.0) + 1.0}, index=sundays("2022-01-02", 40)
    )
    out = features.compute_features(panel)
    # composite (z of a ramp) is strictly increasing -> positive velocity
    # wherever it is defined.
    vel = out["velocity_8w"]
    assert vel.iloc[20:].notna().all()
    assert (vel.dropna() > 0).all()


def test_accel_is_velocity_difference_at_lag_8():
    panel = make_synthetic_panel(n=80)
    out = features.compute_features(panel)
    expected = out["velocity_8w"] - out["velocity_8w"].shift(8)
    pd.testing.assert_series_equal(
        out["accel"], expected, check_exact=True, check_names=False
    )
    # Velocity is first defined at index 12 (composite starts at 7, and the
    # window 5..12 already holds 6 points), so accel starts at 12 + 8 = 20.
    assert out["accel"].iloc[:20].isna().all()
    assert out["accel"].iloc[20:].notna().all()


# ---------------------------------------------------------------------------
# peak_proximity / drawdown
# ---------------------------------------------------------------------------


def _expected_peak_metrics(comp: np.ndarray, t: int) -> tuple[float, float]:
    """Independent loop reimplementation of the ratio metrics at row t."""

    def running_min(upto: int) -> float:
        vals = comp[: upto + 1]
        vals = vals[~np.isnan(vals)]
        return vals.min() if len(vals) else np.nan

    shifted = np.array([comp[s] - running_min(s) for s in range(t + 1)])
    finite = shifted[~np.isnan(shifted)]
    m = finite.max() if len(finite) else np.nan
    if not (m > 1e-9):
        return np.nan, np.nan
    pp = shifted[t] / m
    dd = min(max((m - shifted[t]) / m, 0.0), 1.0)
    return pp, dd


def test_peak_metrics_on_rise_then_fall():
    n = 60
    rise = np.linspace(1.0, 80.0, 40)
    fall = np.linspace(78.0, 30.0, 20)
    panel = pd.DataFrame(
        {"trends": np.concatenate([rise, fall])}, index=sundays("2022-01-02", n)
    )
    out = features.compute_features(panel)
    comp = out["composite"].to_numpy()

    # Hand-check a few rows against the loop reimplementation.
    for t in [20, 39, 45, 59]:
        pp, dd = _expected_peak_metrics(comp, t)
        assert out["peak_proximity"].iloc[t] == pytest.approx(pp, rel=1e-12)
        assert out["drawdown"].iloc[t] == pytest.approx(dd, rel=1e-12)

    # While composite keeps making new highs: at the peak, proximity is 1
    # and drawdown is 0.
    t_peak = int(np.nanargmax(comp))
    assert out["peak_proximity"].iloc[t_peak] == pytest.approx(1.0)
    assert out["drawdown"].iloc[t_peak] == pytest.approx(0.0)

    # After the fall: strictly below the running peak, complements add to 1.
    end = out.iloc[-1]
    assert end["peak_proximity"] < 1.0
    assert end["drawdown"] > 0.0
    assert end["peak_proximity"] + end["drawdown"] == pytest.approx(1.0)

    # Drawdown is a clipped ratio: always inside [0, 1] where defined.
    assert out["drawdown"].dropna().between(0.0, 1.0).all()


def test_peak_metrics_nan_while_composite_undefined():
    panel = make_synthetic_panel(n=30)
    out = features.compute_features(panel)
    # First 7 weeks: no source has 8 observations yet -> composite NaN ->
    # ratio metrics NaN (running peak still empty/zero).
    assert out["composite"].iloc[:7].isna().all()
    assert out["peak_proximity"].iloc[:7].isna().all()
    assert out["drawdown"].iloc[:7].isna().all()


# ---------------------------------------------------------------------------
# breadth / n_sources / composite
# ---------------------------------------------------------------------------


def test_breadth_counts_sources_with_positive_slope():
    n = 40
    idx = sundays("2022-01-02", n)
    t = np.arange(n, dtype=float)
    panel = pd.DataFrame(
        {
            "trends": 1.0 + 2.0 * t,     # rising -> rising z -> slope > 0
            "reddit": 5.0 + 0.5 * t,     # rising -> slope > 0
            "youtube": 200.0 - 3.0 * t,  # falling -> slope < 0
        },
        index=idx,
    )
    out = features.compute_features(panel)
    assert (out["breadth"].iloc[20:] == 2).all()


def test_breadth_ignores_undefined_z():
    n = 40
    idx = sundays("2022-01-02", n)
    t = np.arange(n, dtype=float)
    panel = pd.DataFrame(
        {
            "trends": 1.0 + 2.0 * t,  # rising
            "reddit": [7.0] * n,      # flat -> z undefined -> never counted
        },
        index=idx,
    )
    out = features.compute_features(panel)
    assert (out["breadth"].iloc[20:] == 1).all()


def test_composite_nan_and_n_sources_zero_when_no_sources():
    n = 30
    idx = sundays("2022-01-02", n)
    values = np.arange(n, dtype=float)
    values[:12] = np.nan  # no observations at all early on
    panel = pd.DataFrame(
        {"trends": values, "reddit": np.full(n, np.nan)}, index=idx
    )
    out = features.compute_features(panel)
    # reddit never contributes; trends needs 8 observations (from week 12).
    assert (out["n_sources"].iloc[:19] == 0).all()
    assert out["composite"].iloc[:19].isna().all()
    assert (out["n_sources"].iloc[19:] == 1).all()
    assert out["composite"].iloc[19:].notna().all()


def test_n_sources_tracks_nan_stretches():
    panel = make_synthetic_panel()
    out = features.compute_features(panel)
    # Weeks 45..50 sit inside reddit's outage: trends + youtube only.
    assert (out["n_sources"].iloc[45:51] == 2).all()
    # Week 100: all three sources live.
    assert out["n_sources"].iloc[100] == 3


def test_feature_columns_exact():
    out = features.compute_features(make_synthetic_panel(n=20))
    assert list(out.columns) == features.FEATURE_COLUMNS


# ---------------------------------------------------------------------------
# build_weekly_panel — in-memory MOCK pulls, no files
# ---------------------------------------------------------------------------


def mock_pull(source: str, data: dict, retrieved_at: str) -> Pull:
    """Synthetic in-memory Pull, explicitly provenance-stamped 'fixture'
    (no-fake-data rule: test data is never presented as real)."""
    return Pull(
        source=source,
        trend=TREND,
        retrieved_at=retrieved_at,
        provenance="fixture",
        query_spec={"note": "MOCK synthetic test data"},
        data=data,
    ).validate()


def make_trends_pull() -> Pull:
    weeks = [
        ("2025-01-05", 10, 20, False),
        ("2025-01-12", 20, 30, False),
        ("2025-01-19", 30, 40, False),
        ("2025-01-26", 40, 40, False),
        ("2025-02-02", 50, 60, False),
        ("2025-02-09", 60, 70, False),
        ("2025-02-16", 99, 99, True),  # partial current week -> excluded
    ]
    series = [
        {
            "week_start": ws,
            "values": {"matcha": a, "matcha latte": b},
            "is_partial": partial,
        }
        for ws, a, b, partial in weeks
    ]
    return mock_pull("trends", {"series": series}, "2025-02-18T09:00:00+00:00")


def make_reddit_pull() -> Pull:
    items = [
        {"id": "a1", "created_utc": ts("2025-01-13T10:00:00+00:00"),
         "title": "t", "text": "", "score": 5, "subreddit": "india",
         "num_comments": 3},
        {"id": "a2", "created_utc": ts("2025-01-18T22:00:00+00:00"),
         "title": "t", "text": "", "score": 2, "subreddit": "IndianFood",
         "num_comments": 2},
        {"id": "a3", "created_utc": ts("2025-01-27T05:00:00+00:00"),
         "title": "t", "text": "", "score": 1, "subreddit": "bangalore",
         "num_comments": 0},
    ]
    # Retrieved Feb 20 -> last fully covered week starts 2025-02-09.
    return mock_pull("reddit", {"items": items}, "2025-02-20T08:00:00+00:00")


def test_build_weekly_panel_bucketing_and_zeros():
    pulls = {"trends": make_trends_pull(), "reddit": make_reddit_pull()}
    panel, prov = features.build_weekly_panel(pulls)

    assert prov == {"trends": "fixture", "reddit": "fixture"}
    assert list(panel.columns) == ["trends", "reddit"]  # youtube: no pull
    assert list(panel.index) == list(sundays("2025-01-05", 6))  # partial week out

    # trends = mean of basket terms per week.
    np.testing.assert_allclose(
        panel["trends"], [15.0, 25.0, 35.0, 40.0, 55.0, 65.0]
    )

    # reddit = count + sum(num_comments); before first item -> NaN (we did
    # not look); silent weeks inside coverage -> real 0.
    assert np.isnan(panel["reddit"].iloc[0])              # 01-05: pre-coverage
    assert panel["reddit"].loc["2025-01-12"] == 7.0       # 2 items + 5 comments
    assert panel["reddit"].loc["2025-01-19"] == 0.0       # covered, silent
    assert panel["reddit"].loc["2025-01-26"] == 1.0       # 1 item + 0 comments
    assert panel["reddit"].loc["2025-02-02"] == 0.0
    assert panel["reddit"].loc["2025-02-09"] == 0.0


def test_build_weekly_panel_as_of_week_completeness():
    pulls = {"trends": make_trends_pull(), "reddit": make_reddit_pull()}
    # Saturday 2025-01-25 is the last day of the 01-19 week: that week is
    # complete as of this date, the 01-26 week is not.
    panel, _ = features.build_weekly_panel(pulls, as_of=datetime.date(2025, 1, 25))
    assert list(panel.index) == list(sundays("2025-01-05", 3))
    np.testing.assert_allclose(panel["trends"], [15.0, 25.0, 35.0])
    assert np.isnan(panel["reddit"].iloc[0])
    assert panel["reddit"].loc["2025-01-12"] == 7.0
    assert panel["reddit"].loc["2025-01-19"] == 0.0


def test_build_weekly_panel_as_of_prefix_consistency():
    """Panel-level R1: an earlier as_of yields exactly the matching prefix
    of a later as_of's panel — history never rewrites itself."""
    youtube_items = [
        {"video_id": f"v{i}", "published_at": iso, "title": "t",
         "description": "", "view_count": 10, "channel_id": "c",
         "channel_title": "ch"}
        for i, iso in enumerate(
            ["2025-01-06T10:00:00+00:00", "2025-01-21T10:00:00+00:00",
             "2025-02-11T10:00:00+00:00"]
        )
    ]
    pulls = {
        "trends": make_trends_pull(),
        "reddit": make_reddit_pull(),
        "youtube": mock_pull(
            "youtube", {"items": youtube_items}, "2025-03-05T00:00:00+00:00"
        ),
    }
    full, _ = features.build_weekly_panel(pulls, as_of=datetime.date(2025, 3, 1))
    part, _ = features.build_weekly_panel(pulls, as_of=datetime.date(2025, 2, 1))
    pd.testing.assert_frame_equal(
        part, full.loc[part.index], check_exact=True, check_freq=False
    )


def test_reddit_item_filtering_at_as_of_end_of_day():
    """Items after as_of end-of-day UTC are dropped (R1). Tested on the
    aggregation helper: at panel level any week containing such items is
    incomplete and never appears, so the filter is belt and braces."""
    items = [
        {"id": "in", "created_utc": ts("2025-01-25T23:59:59+00:00"),
         "num_comments": 0},
        {"id": "out", "created_utc": ts("2025-01-26T00:00:01+00:00"),
         "num_comments": 9},
    ]
    pull = mock_pull("reddit", {"items": items}, "2025-02-20T08:00:00+00:00")
    weeks = features._reddit_weeks(pull, as_of=datetime.date(2025, 1, 25))
    assert weeks == {datetime.date(2025, 1, 19): 1.0}


def test_youtube_item_filtering_and_timezone_handling():
    items = [
        {"video_id": "v1", "published_at": "2025-01-13T09:00:00Z"},
        # IST early morning Jan 19 = Jan 18 UTC -> still the 01-12 week.
        {"video_id": "v2", "published_at": "2025-01-19T02:00:00+05:30"},
        {"video_id": "v3", "published_at": "2025-01-20T10:00:00+00:00"},
        {"video_id": "v4", "published_at": "2025-02-02T00:00:01+00:00"},
    ]
    pull = mock_pull("youtube", {"items": items}, "2025-02-20T08:00:00+00:00")
    weeks = features._youtube_weeks(pull, as_of=datetime.date(2025, 2, 1))
    assert weeks == {
        datetime.date(2025, 1, 12): 2.0,
        datetime.date(2025, 1, 19): 1.0,
        # v4 is after as_of end-of-day -> dropped entirely.
    }


def test_keyed_week_incomplete_before_retrieval():
    """A week the pull was retrieved in the middle of is not a real
    observation (the keyed-source analogue of trends' is_partial)."""
    items = [
        {"id": "a", "created_utc": ts("2025-01-13T10:00:00+00:00"),
         "num_comments": 1},
        {"id": "b", "created_utc": ts("2025-01-20T10:00:00+00:00"),
         "num_comments": 4},  # in the retrieval week -> incomplete
    ]
    pull = mock_pull("reddit", {"items": items}, "2025-01-22T12:00:00+00:00")
    panel, _ = features.build_weekly_panel({"reddit": pull})
    assert list(panel.index) == [pd.Timestamp("2025-01-12")]
    assert panel["reddit"].iloc[0] == 2.0  # 1 item + 1 comment


def test_build_weekly_panel_empty_pulls():
    panel, prov = features.build_weekly_panel({})
    assert panel.empty
    assert prov == {}


# ---------------------------------------------------------------------------
# load_pulls
# ---------------------------------------------------------------------------


def test_load_pulls_omits_sources_without_files(monkeypatch):
    available = {"trends": make_trends_pull()}

    def fake_latest(source, trend):
        assert trend == TREND
        return available.get(source)

    monkeypatch.setattr(features.base, "latest", fake_latest)
    pulls = features.load_pulls(TREND)
    assert set(pulls) == {"trends"}
    assert pulls["trends"].provenance == "fixture"
