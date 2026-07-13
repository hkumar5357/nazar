"""Google Trends ingestion (geo=IN, weekly buckets). Keyless — no API key.

Backend is selected via env TRENDS_BACKEND: "pytrends" (default) or
"trendspy". Both return the same weekly interest-over-time table for a
payload of up to 5 terms — a Sunday-dated index, one 0-100 integer column
per term, and an isPartial flag on the trailing in-progress week — so
everything downstream of df_to_series() is backend-agnostic. All terms of a
trend basket go into ONE payload so Google normalizes them on a shared
0-100 scale (required for the composite index to be meaningful).

Protocol constraints enforced here:

- R1 (point-in-time): the timeframe ends at the retrieval date, and the
  trailing partial week is KEPT in the raw file, flagged is_partial=True.
  The raw file preserves exactly what the API returned at retrieval time;
  scoring excludes flagged weeks downstream, so no feature is ever computed
  on an incomplete bucket.
- R4 (run logging): pull_all() wraps the whole ingestion in
  runlog.run("ingest_trends"), records the backend and trend list, and
  registers every written file. Retry attempts are printed to stdout; a run
  that exhausts its retries is recorded as failed, not deleted.
- No fake data: every envelope built here is provenance="real" and is saved
  via base.save_raw(), which refuses non-real provenance into data/raw/.

Rate-limit politeness: up to MAX_ATTEMPTS per trend with linear backoff
(60s x attempt + 0-15s jitter) and a random 30-45s pause between trends.

CLI: python -m pipeline.ingest.trends [all|<trend-slug>]   (default: all)

Import-safe: the backend libraries are imported inside the fetch helpers,
so importing this module performs no network activity.
"""

from __future__ import annotations

import os
import random
import sys
import time
from datetime import date
from pathlib import Path

from pipeline import provenance, runlog, trends_config
from pipeline.ingest import base

DEFAULT_BACKEND = "pytrends"
BACKENDS = ("pytrends", "trendspy")

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 60
BACKOFF_JITTER_SECONDS = 15
PAUSE_BETWEEN_TRENDS_SECONDS = (30, 45)

# Google Trends compares at most 5 terms in one payload; one payload per
# trend is a hard requirement here because shared normalization only holds
# within a payload.
MAX_TERMS_PER_PAYLOAD = 5


def backend_name() -> str:
    """Backend from env TRENDS_BACKEND; defaults to pytrends."""
    name = os.environ.get("TRENDS_BACKEND", DEFAULT_BACKEND)
    if name not in BACKENDS:
        raise ValueError(f"TRENDS_BACKEND must be one of {BACKENDS}, got {name!r}")
    return name


def _fetch_pytrends(terms: list[str], timeframe: str):
    """Live weekly interest-over-time via pytrends (lazy import, no key)."""
    from pytrends.request import TrendReq

    # tz is irrelevant for weekly buckets; 360 is the pytrends-documented
    # default and matches how tonight's pulls were verified.
    client = TrendReq(hl="en-US", tz=360)
    client.build_payload(list(terms), timeframe=timeframe, geo=trends_config.GEO)
    return client.interest_over_time()


def _fetch_trendspy(terms: list[str], timeframe: str):
    """Live weekly interest-over-time via trendspy (lazy import, no key)."""
    from trendspy import Trends

    client = Trends()
    return client.interest_over_time(
        list(terms), timeframe=timeframe, geo=trends_config.GEO
    )


def df_to_series(df, terms: list[str]) -> list[dict]:
    """Convert a backend dataframe to the envelope series schema (base.py).

    Expects the shape both backends return: a date index of weekly buckets
    (Sundays — Google Trends weekly convention), one integer column per term,
    and optionally an ``isPartial`` bool column; rows without that column are
    treated as complete weeks. Partial weeks are kept and flagged, never
    dropped: the raw file records exactly what the API returned, and scoring
    excludes flagged weeks downstream (PROTOCOL R1 — a feature computed at T
    must not use the incomplete bucket containing T).

    Pure function — no I/O, no network — so tests can exercise the full
    conversion with a synthetic in-memory dataframe.
    """
    has_partial_column = "isPartial" in df.columns
    series = []
    for week, row in df.iterrows():
        series.append(
            {
                "week_start": week.strftime("%Y-%m-%d"),
                "values": {term: int(row[term]) for term in terms},
                "is_partial": bool(row["isPartial"]) if has_partial_column else False,
            }
        )
    return series


def _retrying(pull_once, label: str):
    """Run pull_once() with up to MAX_ATTEMPTS, linear backoff + jitter.

    Every attempt and every failure is printed to stdout — retries are loud,
    never silent (PROTOCOL R4 spirit). The final failure re-raises so the
    surrounding runlog context records the run as failed.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"[trends] {label}: attempt {attempt}/{MAX_ATTEMPTS}", flush=True)
            return pull_once()
        except Exception as exc:
            if attempt == MAX_ATTEMPTS:
                print(
                    f"[trends] {label}: attempt {attempt} failed ({exc}); giving up",
                    flush=True,
                )
                raise
            delay = BACKOFF_BASE_SECONDS * attempt + random.uniform(
                0, BACKOFF_JITTER_SECONDS
            )
            print(
                f"[trends] {label}: attempt {attempt} failed ({exc}); "
                f"retrying in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)


def fetch(trend: str) -> base.Pull:
    """One real Google Trends pull: all basket terms in a single payload.

    Timeframe is HISTORY_START through today (data as of retrieval — R1),
    geo=IN. An empty dataframe counts as a failed attempt: Google sometimes
    soft-fails with an empty result, and silently saving an empty series
    would be worse than retrying loudly.
    """
    terms = trends_config.basket(trend)["trends_terms"]
    if len(terms) > MAX_TERMS_PER_PAYLOAD:
        raise ValueError(
            f"{trend!r} has {len(terms)} trends_terms; Google Trends allows "
            f"at most {MAX_TERMS_PER_PAYLOAD} per payload"
        )
    backend = backend_name()
    timeframe = f"{trends_config.HISTORY_START} {date.today().isoformat()}"

    def pull_once():
        if backend == "pytrends":
            df = _fetch_pytrends(terms, timeframe)
        else:
            df = _fetch_trendspy(terms, timeframe)
        if df is None or len(df) == 0:
            raise RuntimeError(f"{backend} returned no rows for {trend!r}")
        return df

    df = _retrying(pull_once, label=f"{backend}:{trend}")
    return base.Pull(
        source="trends",
        trend=trend,
        retrieved_at=base.now_iso(),
        provenance=provenance.REAL,
        query_spec={
            "backend": backend,
            "terms": list(terms),
            "geo": trends_config.GEO,
            "timeframe": timeframe,
        },
        data={"series": df_to_series(df, terms)},
    ).validate()


def pull_all(trends: list[str]) -> list[Path]:
    """Fetch and save every trend, logged as one run (PROTOCOL R4).

    Sleeps a polite random 30-45s BETWEEN trends (not after the last) to
    stay under Google's unofficial rate limits. Each written file is
    registered on the run record as it lands, so even a run that dies
    mid-way documents what it produced.
    """
    written: list[Path] = []
    with runlog.run("ingest_trends", notes="Google Trends weekly pulls, geo=IN") as ctx:
        ctx.set("backend", backend_name())
        ctx.set("trends", list(trends))
        for i, trend in enumerate(trends):
            if i > 0:
                pause = random.uniform(*PAUSE_BETWEEN_TRENDS_SECONDS)
                print(
                    f"[trends] pausing {pause:.0f}s before {trend!r} "
                    "(rate-limit politeness)",
                    flush=True,
                )
                time.sleep(pause)
            path = base.save_raw(fetch(trend))
            ctx.add_output(path)
            written.append(path)
            print(f"[trends] wrote {path}", flush=True)
    return written


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: python -m pipeline.ingest.trends [all|<trend-slug>]."""
    args = sys.argv[1:] if argv is None else list(argv)
    target = args[0] if args else "all"
    if target == "all":
        selected = list(trends_config.ALL_TRENDS)
    elif target in trends_config.TRENDS:
        selected = [target]
    else:
        raise SystemExit(
            f"unknown trend {target!r}; usage: python -m pipeline.ingest.trends "
            f"[all|{'|'.join(sorted(trends_config.TRENDS))}]"
        )
    pull_all(selected)


if __name__ == "__main__":
    main()
