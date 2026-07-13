"""Hermetic tests for Google Trends ingestion (pipeline/ingest/trends.py).

No network anywhere: the backend fetch helpers are monkeypatched to return a
synthetic in-memory dataframe shaped exactly like real pytrends output —
Sunday-dated weekly index, one integer column per term, and an isPartial
column whose trailing row is True. The synthetic frame is MOCK data, lives
only in memory (or under tmp_path), and is never presented as real.

base.save_raw's refusal of non-real provenance is covered by the ingestion
base tests and deliberately not duplicated here.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from pipeline import runlog, trends_config
from pipeline.ingest import base, trends

MATCHA_TERMS = trends_config.TRENDS["matcha"]["trends_terms"]

# Google Trends weekly buckets start on Sundays; the trailing bucket is the
# in-progress week, which real pytrends frames flag isPartial=True.
MOCK_SUNDAYS = ["2022-01-02", "2022-01-09", "2022-01-16"]


def make_mock_df(terms):
    """MOCK pytrends-shaped frame: term k gets values 10+k, 20+k, 30+k."""
    data = {
        term: [10 * (week + 1) + k for week in range(len(MOCK_SUNDAYS))]
        for k, term in enumerate(terms)
    }
    data["isPartial"] = [False] * (len(MOCK_SUNDAYS) - 1) + [True]
    return pd.DataFrame(data, index=pd.to_datetime(MOCK_SUNDAYS))


# --- df_to_series: pure conversion -----------------------------------------


def test_df_to_series_values_and_week_start_formatting():
    terms = ["matcha", "matcha latte"]
    series = trends.df_to_series(make_mock_df(terms), terms)

    assert [row["week_start"] for row in series] == MOCK_SUNDAYS
    assert series[0]["values"] == {"matcha": 10, "matcha latte": 11}
    assert series[2]["values"] == {"matcha": 30, "matcha latte": 31}

    # Plain Python ints/bools (not numpy scalars) so envelopes stay JSON-safe.
    for row in series:
        for value in row["values"].values():
            assert type(value) is int
        assert type(row["is_partial"]) is bool
    json.dumps(series)


def test_df_to_series_flags_partial_trailing_week():
    terms = ["matcha"]
    series = trends.df_to_series(make_mock_df(terms), terms)
    assert [row["is_partial"] for row in series] == [False, False, True]


def test_df_to_series_defaults_partial_false_without_column():
    terms = ["matcha"]
    df = make_mock_df(terms).drop(columns=["isPartial"])
    series = trends.df_to_series(df, terms)
    assert [row["is_partial"] for row in series] == [False, False, False]


# --- backend selection ------------------------------------------------------


def test_backend_defaults_to_pytrends(monkeypatch):
    monkeypatch.delenv("TRENDS_BACKEND", raising=False)
    assert trends.backend_name() == "pytrends"


def test_backend_env_selects_trendspy(monkeypatch):
    monkeypatch.setenv("TRENDS_BACKEND", "trendspy")
    assert trends.backend_name() == "trendspy"


def test_backend_rejects_unknown_name(monkeypatch):
    monkeypatch.setenv("TRENDS_BACKEND", "bogus")
    with pytest.raises(ValueError):
        trends.backend_name()


# --- fetch: envelope construction (backend stubbed, no network) -------------


def test_fetch_builds_valid_real_envelope(monkeypatch):
    monkeypatch.delenv("TRENDS_BACKEND", raising=False)
    seen = {}

    def fake_pytrends(terms, timeframe):
        seen["terms"] = terms
        seen["timeframe"] = timeframe
        return make_mock_df(terms)

    monkeypatch.setattr(trends, "_fetch_pytrends", fake_pytrends)

    pull = trends.fetch("matcha")
    pull.validate()  # envelope contract from ingest/base.py

    assert pull.source == "trends"
    assert pull.trend == "matcha"
    assert pull.provenance == "real"
    assert pull.query_spec == {
        "backend": "pytrends",
        "terms": MATCHA_TERMS,
        "geo": "IN",
        "timeframe": f"2022-01-01 {date.today().isoformat()}",
    }
    assert seen["terms"] == MATCHA_TERMS
    assert seen["timeframe"] == pull.query_spec["timeframe"]
    assert len(pull.data["series"]) == len(MOCK_SUNDAYS)
    assert pull.data["series"][-1]["is_partial"] is True


def test_fetch_dispatches_to_trendspy_backend(monkeypatch):
    monkeypatch.setenv("TRENDS_BACKEND", "trendspy")
    monkeypatch.setattr(
        trends, "_fetch_trendspy", lambda terms, timeframe: make_mock_df(terms)
    )
    pull = trends.fetch("matcha")
    assert pull.query_spec["backend"] == "trendspy"


# --- retry/backoff -----------------------------------------------------------


def test_fetch_retries_with_linear_backoff_and_jitter(monkeypatch):
    monkeypatch.delenv("TRENDS_BACKEND", raising=False)
    attempts = []

    def flaky(terms, timeframe):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("MOCK transient 429")
        return make_mock_df(terms)

    sleeps = []
    monkeypatch.setattr(trends, "_fetch_pytrends", flaky)
    monkeypatch.setattr(trends.time, "sleep", sleeps.append)

    pull = trends.fetch("matcha")

    assert len(attempts) == 3
    assert pull.provenance == "real"
    # 60*attempt + jitter in [0, 15]
    assert len(sleeps) == 2
    assert 60 <= sleeps[0] <= 75
    assert 120 <= sleeps[1] <= 135


def test_fetch_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.delenv("TRENDS_BACKEND", raising=False)
    attempts = []

    def always_fail(terms, timeframe):
        attempts.append(1)
        raise ConnectionError("MOCK hard failure")

    monkeypatch.setattr(trends, "_fetch_pytrends", always_fail)
    monkeypatch.setattr(trends.time, "sleep", lambda s: None)

    with pytest.raises(ConnectionError):
        trends.fetch("matcha")
    assert len(attempts) == trends.MAX_ATTEMPTS


def test_fetch_treats_empty_dataframe_as_failure(monkeypatch):
    monkeypatch.delenv("TRENDS_BACKEND", raising=False)
    monkeypatch.setattr(
        trends, "_fetch_pytrends", lambda terms, timeframe: pd.DataFrame()
    )
    monkeypatch.setattr(trends.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        trends.fetch("matcha")


# --- pull_all: files + run logging (all I/O redirected to tmp_path) ---------


def test_pull_all_writes_files_and_logs_run(tmp_path, monkeypatch):
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    runs_dir = tmp_path / "runs"

    monkeypatch.setattr(base, "RAW_DIR", raw_dir)
    monkeypatch.setattr(runlog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runlog, "RUNS_DIR", runs_dir)
    monkeypatch.delenv("TRENDS_BACKEND", raising=False)
    monkeypatch.setattr(
        trends, "_fetch_pytrends", lambda terms, timeframe: make_mock_df(terms)
    )
    sleeps = []
    monkeypatch.setattr(trends.time, "sleep", sleeps.append)

    paths = trends.pull_all(["matcha", "korean_skincare"])

    # One file per trend, in (redirected) data/raw, loadable + valid.
    assert len(paths) == 2
    assert all(p.parent == raw_dir for p in paths)
    for path, trend in zip(paths, ["matcha", "korean_skincare"]):
        loaded = base.load(path)
        assert loaded.trend == trend
        assert loaded.provenance == "real"
        assert loaded.data["series"][-1]["is_partial"] is True

    # Exactly one polite pause BETWEEN the two trends, none after the last.
    assert len(sleeps) == 1
    assert 30 <= sleeps[0] <= 45

    # R4: one run record with backend, trend list, and every output file.
    run_dirs = list(runs_dir.iterdir())
    assert len(run_dirs) == 1
    record = json.loads((run_dirs[0] / "run.json").read_text())
    assert record["command"] == "ingest_trends"
    assert record["status"] == "ok"
    assert record["extra"]["backend"] == "pytrends"
    assert record["extra"]["trends"] == ["matcha", "korean_skincare"]
    assert [o["path"] for o in record["outputs"]] == [
        str(p.relative_to(tmp_path)) for p in paths
    ]


# --- CLI ----------------------------------------------------------------------


def test_cli_selects_all_or_single_trend(monkeypatch):
    calls = []
    monkeypatch.setattr(trends, "pull_all", lambda ts: calls.append(ts) or [])

    trends.main([])
    trends.main(["matcha"])

    assert calls[0] == trends_config.ALL_TRENDS
    assert calls[1] == ["matcha"]


def test_cli_rejects_unknown_slug(monkeypatch):
    monkeypatch.setattr(
        trends, "pull_all", lambda ts: pytest.fail("must not pull for a bad slug")
    )
    with pytest.raises(SystemExit):
        trends.main(["not-a-trend"])
