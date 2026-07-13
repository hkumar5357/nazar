"""Weekly per-trend features computed at date T over data <= T (PROTOCOL R1).

The single invariant everything in this module obeys: every statistic is
either expanding-window (uses rows 0..t only) or trailing-window (uses a
fixed number of rows ending at t). There are NO full-series operations —
no global max, no global mean, no whole-series normalization. Consequence,
and the property tests/test_features.py enforces: computing features on a
series truncated at week T yields EXACTLY the same row at T as computing
on the full series and reading row T. That is what makes the walk-forward
backtest honest — no lookahead, anywhere.

Pipeline position: ingestion envelopes (pipeline.ingest.base.Pull) come in;
build_weekly_panel turns them into a weekly panel of raw per-source
activity; compute_features turns the panel into the feature rows the
lifecycle rules (pipeline.lifecycle) consume.

Provenance travels alongside (BRIEF §0.3 no-fake-data rule):
build_weekly_panel returns a {source: provenance_kind} map so downstream
exports can refuse fixture-derived data via provenance.assert_all_real.

No LLM anywhere in this module (PROTOCOL R5): features are plain
time-series math over public activity counts.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from pipeline.ingest import base
from pipeline.ingest.base import Pull

# Feature definitions (BRIEF §5.2). These constants are structural choices
# fixed before calibration; the lifecycle STATE cutoffs (L1, L2, V0, V1)
# live in thresholds_frozen.json and are frozen at M1 (PROTOCOL R3).
Z_MIN_HISTORY = 8        # weeks of history before an expanding z is trusted
SLOPE_WINDOW_WEEKS = 8   # trailing window for velocity_8w and breadth
SLOPE_MIN_POINTS = 6     # non-NaN points required inside a slope window
ACCEL_LAG_WEEKS = 8      # accel = velocity now minus velocity this long ago

FEATURE_COLUMNS = [
    "composite",
    "n_sources",
    "velocity_8w",
    "accel",
    "peak_proximity",
    "drawdown",
    "breadth",
]

_EPS = 1e-9
_UTC = datetime.timezone.utc
_WEEK = datetime.timedelta(days=7)


def load_pulls(trend: str) -> dict[str, Pull]:
    """Newest pull per source for `trend`, via base.latest.

    Sources with no file at all (neither a real raw pull nor a MOCK_
    fixture) are omitted from the dict entirely — downstream, an absent
    source means an absent panel column, never a fabricated one.
    """
    pulls: dict[str, Pull] = {}
    for source in base.SOURCES:
        pull = base.latest(source, trend)
        if pull is not None:
            pulls[source] = pull
    return pulls


def _sunday_of(day: datetime.date) -> datetime.date:
    """Snap a date to the Sunday that starts its Google Trends week."""
    return day - datetime.timedelta(days=(day.weekday() + 1) % 7)


def _week_end(week_start: datetime.date) -> datetime.date:
    """Last day (Saturday) of the week starting at `week_start`."""
    return week_start + datetime.timedelta(days=6)


def _retrieved_date(pull: Pull) -> datetime.date:
    """UTC date the pull was retrieved (from the envelope's retrieved_at)."""
    dt = datetime.datetime.fromisoformat(pull.retrieved_at)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_UTC)
    return dt.date()


def _as_of_cutoff(as_of: datetime.date) -> datetime.datetime:
    """Exclusive UTC datetime bound for 'timestamped <= as_of' (R1).

    Items are kept iff their timestamp falls strictly before the first
    instant of the day AFTER as_of, i.e. within as_of end-of-day UTC.
    """
    return datetime.datetime.combine(
        as_of + datetime.timedelta(days=1), datetime.time.min, tzinfo=_UTC
    )


def _trends_weeks(
    pull: Pull, as_of: datetime.date | None
) -> dict[datetime.date, float]:
    """{week_start: mean of basket-term values} for complete trends weeks.

    A trends week is complete iff is_partial is False and, when as_of is
    given, the week ended on or before as_of (R1 point-in-time rule).
    """
    weeks: dict[datetime.date, float] = {}
    for entry in pull.data.get("series", []):
        if entry.get("is_partial", False):
            continue
        week = _sunday_of(datetime.date.fromisoformat(entry["week_start"]))
        if as_of is not None and _week_end(week) > as_of:
            continue
        values = list(entry["values"].values())
        if values:
            weeks[week] = float(np.mean(values))
    return weeks


def _reddit_weeks(
    pull: Pull, as_of: datetime.date | None
) -> dict[datetime.date, float]:
    """{week_start: item count + sum of num_comments} from reddit items.

    Count-plus-comments is a deliberate activity proxy: a post that starts
    a conversation is more signal than a post nobody answers. When as_of
    is given, items with created_utc after as_of end-of-day UTC are
    dropped (R1) — belt and braces, since any week containing them is
    incomplete and never reaches the panel anyway.
    """
    cutoff_ts = None
    if as_of is not None:
        cutoff_ts = _as_of_cutoff(as_of).timestamp()
    weeks: dict[datetime.date, float] = {}
    for item in pull.data.get("items", []):
        ts = item["created_utc"]
        if cutoff_ts is not None and ts >= cutoff_ts:
            continue
        day = datetime.datetime.fromtimestamp(ts, tz=_UTC).date()
        week = _sunday_of(day)
        weeks[week] = weeks.get(week, 0.0) + 1.0 + float(item.get("num_comments", 0))
    return weeks


def _youtube_weeks(
    pull: Pull, as_of: datetime.date | None
) -> dict[datetime.date, float]:
    """{week_start: upload count} from youtube items (published_at, UTC).

    Same as_of end-of-day filtering as reddit (R1).
    """
    cutoff = None
    if as_of is not None:
        cutoff = _as_of_cutoff(as_of)
    weeks: dict[datetime.date, float] = {}
    for item in pull.data.get("items", []):
        dt = datetime.datetime.fromisoformat(item["published_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        dt = dt.astimezone(_UTC)
        if cutoff is not None and dt >= cutoff:
            continue
        week = _sunday_of(dt.date())
        weeks[week] = weeks.get(week, 0.0) + 1.0
    return weeks


def _keyed_last_complete_week(
    pull: Pull, as_of: datetime.date | None
) -> datetime.date:
    """Last week fully covered by a reddit/youtube pull.

    Google Trends marks its own partial week with is_partial; keyed
    sources need the analogue, otherwise the week a pull was retrieved in
    would look like a (falsely low) real observation. A week counts as
    covered only if it ended strictly before the retrieval date, and —
    when as_of is given — ended on or before as_of (R1).
    """
    last = _sunday_of(_retrieved_date(pull) - _WEEK)
    if as_of is not None:
        last = min(last, _sunday_of(as_of - datetime.timedelta(days=6)))
    return last


def build_weekly_panel(
    pulls: dict[str, Pull], as_of: datetime.date | None = None
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Weekly per-source activity panel + provenance map from raw pulls.

    Returns (panel, provenance_map) where provenance_map is
    {source: pull.provenance} — downstream exports use it to enforce the
    no-fake-data rule.

    Panel shape:
    - Index: consecutive weekly Sundays (the Google Trends week grid),
      from the earliest complete week any source covers to the last
      complete week any source covers. A week is complete iff is_partial
      is False (trends) / it ended before retrieval (reddit, youtube)
      and, when as_of is given, it ended on or before as_of (R1).
    - "trends": mean of the basket terms' values that week.
    - "reddit": item count + sum of num_comments (activity proxy).
    - "youtube": upload count.
    - Weeks inside a source's coverage window with zero items are 0.0 —
      a real observation of silence, which is exactly what trend decay
      looks like. Weeks outside coverage are NaN (we did not look).
      Sources with no pull have no column at all.
    """
    provenance_map = {source: pull.provenance for source, pull in pulls.items()}

    per_source: dict[str, dict[datetime.date, float]] = {}
    coverage: dict[str, tuple[datetime.date, datetime.date]] = {}
    for source, pull in pulls.items():
        if source == "trends":
            weeks = _trends_weeks(pull, as_of)
            if weeks:
                per_source[source] = weeks
                coverage[source] = (min(weeks), max(weeks))
        else:
            aggregate = _reddit_weeks if source == "reddit" else _youtube_weeks
            weeks = aggregate(pull, as_of)
            last = _keyed_last_complete_week(pull, as_of)
            weeks = {w: v for w, v in weeks.items() if w <= last}
            if weeks:
                per_source[source] = weeks
                # Coverage runs from the first observed item through the
                # last week the pull fully covers: trailing silent weeks
                # are real zeros, not gaps.
                coverage[source] = (min(weeks), last)

    ordered_sources = [s for s in base.SOURCES if s in pulls]
    if not per_source:
        empty_index = pd.DatetimeIndex([], name="week_start")
        panel = pd.DataFrame(
            {s: pd.Series(dtype=float) for s in ordered_sources}, index=empty_index
        )
        return panel, provenance_map

    first = min(lo for lo, _ in coverage.values())
    last = max(hi for _, hi in coverage.values())
    index = pd.date_range(
        pd.Timestamp(first), pd.Timestamp(last), freq="7D", name="week_start"
    )

    columns: dict[str, pd.Series] = {}
    for source in ordered_sources:
        if source not in per_source:
            columns[source] = pd.Series(np.nan, index=index, dtype=float)
            continue
        weeks = per_source[source]
        lo, hi = coverage[source]
        values = []
        for ts in index:
            week = ts.date()
            if week < lo or week > hi:
                values.append(np.nan)  # outside coverage: we did not look
            elif source == "trends":
                # A gap inside the trends grid is missing data, not zero.
                values.append(weeks.get(week, np.nan))
            else:
                values.append(weeks.get(week, 0.0))  # real zero-activity week
        columns[source] = pd.Series(values, index=index, dtype=float)

    return pd.DataFrame(columns), provenance_map


def expanding_z(s: pd.Series, min_history: int = Z_MIN_HISTORY) -> pd.Series:
    """Expanding-window z-score: z_t = (x_t - mean(x[0..t])) / std(x[0..t]).

    std uses ddof=1. NaN wherever fewer than min_history non-NaN
    observations have been seen so far, or the expanding std is <= 1e-9
    (a flat series has no meaningful z). Expanding-only by construction —
    the value at t can never see anything after t (PROTOCOL R1).
    """
    mean = s.expanding().mean()
    std = s.expanding().std(ddof=1)
    count = s.expanding().count()
    z = (s - mean) / std
    return z.where((count >= min_history) & (std > _EPS))


def trailing_slope(
    s: pd.Series,
    window: int = SLOPE_WINDOW_WEEKS,
    min_points: int = SLOPE_MIN_POINTS,
) -> pd.Series:
    """OLS slope of s over the trailing `window` rows ending at each t.

    x is the week offset 0..window-1 inside the window, so the slope is
    per-week. Requires min_points non-NaN values inside the window, else
    NaN; NaN until a full window of rows exists. Trailing-only (R1).
    """
    values = s.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    x = np.arange(window, dtype=float)
    for t in range(window - 1, len(values)):
        y = values[t - window + 1 : t + 1]
        mask = ~np.isnan(y)
        if mask.sum() >= min_points:
            out[t] = np.polyfit(x[mask], y[mask], 1)[0]
    return pd.Series(out, index=s.index)


def compute_features(
    panel: pd.DataFrame, as_of: datetime.date | None = None
) -> pd.DataFrame:
    """Feature rows for the lifecycle rules, from a weekly source panel.

    Columns (exactly FEATURE_COLUMNS):
    - composite:      mean of the available per-source expanding z-scores
    - n_sources:      how many sources contributed that week (0 -> NaN
                      composite; honesty count, shown on the dashboard)
    - velocity_8w:    trailing-8-week OLS slope of composite
    - accel:          velocity_8w now minus velocity_8w 8 weeks ago
    - peak_proximity: how close composite sits to its running peak
    - drawdown:       how far composite has fallen off its running peak
    - breadth:        number of sources whose z has a positive
                      trailing-8-week slope

    peak_proximity/drawdown are ratios, and composite (a mean of z-scores)
    can be negative, so composite is first shifted by its expanding min:
    shifted_t = composite_t - expanding_min(composite)_t, and
    m_t = expanding_max(shifted)_t. Then peak_proximity = shifted_t / m_t
    and drawdown = (m_t - shifted_t) / m_t clipped to [0, 1], both NaN
    while m_t <= 1e-9. Expanding min/max ONLY — a global max would leak
    the future into every earlier row and break R1.

    If as_of is given, rows for weeks ending after as_of are dropped
    before computing anything (R1 belt and braces; build_weekly_panel
    already refuses incomplete weeks when given the same as_of).
    """
    if as_of is not None:
        panel = panel.loc[panel.index + pd.Timedelta(days=6) <= pd.Timestamp(as_of)]

    z = pd.DataFrame(
        {col: expanding_z(panel[col]) for col in panel.columns}, index=panel.index
    )
    n_sources = z.notna().sum(axis=1).astype("int64")
    composite = z.mean(axis=1)  # row mean over non-NaN z's; all-NaN -> NaN

    velocity_8w = trailing_slope(composite)
    accel = velocity_8w - velocity_8w.shift(ACCEL_LAG_WEEKS)

    shifted = composite - composite.expanding().min()
    running_peak = shifted.expanding().max()
    defined = running_peak > _EPS
    peak_proximity = (shifted / running_peak).where(defined)
    drawdown = ((running_peak - shifted) / running_peak).clip(0.0, 1.0).where(defined)

    source_slopes = pd.DataFrame(
        {col: trailing_slope(z[col]) for col in z.columns}, index=panel.index
    )
    breadth = (source_slopes > 0).sum(axis=1).astype("int64")  # NaN slope -> False

    return pd.DataFrame(
        {
            "composite": composite,
            "n_sources": n_sources,
            "velocity_8w": velocity_8w,
            "accel": accel,
            "peak_proximity": peak_proximity,
            "drawdown": drawdown,
            "breadth": breadth,
        }
    )
