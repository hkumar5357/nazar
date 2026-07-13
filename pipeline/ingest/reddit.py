"""Reddit ingestion (script app, PRAW, read-only). Public metadata only.

For each trend, searches every query in basket["reddit_queries"] across every
subreddit in trends_config.SUBREDDITS (one shared subreddit set for all
trends — PROTOCOL C2's "one shared pipeline" requirement). Results are
filtered client-side to created_utc >= HISTORY_START, deduplicated by
submission id across queries, and written as a single "reddit" envelope per
trend via base.save_raw with provenance="real".

Known honest limitation (declared, not hidden): Reddit's search listings cap
out at roughly 250 results per (subreddit, query) and are returned newest
first, so coverage skews recent. Historical coverage for 2022-2024 will be
sparse, especially on high-volume subreddits. This is a property of the public
API, it is documented here and in LABNOTES, and the composite index treats
Reddit as one signal among several rather than a complete archive.

Rate limits: we sleep ~1.1s between (subreddit x query) listings, which keeps
us far under Reddit's authenticated limit (~100 requests/min); PRAW adds its
own internal throttling on top.

Credentials: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT are
loaded from the environment (python-dotenv, called at fetch time — never at
import time) and are absent until Harsh supplies keys (BRIEF §2). Missing or
empty values raise base.MissingCredentials; there is no silent fixture
fallback here — fixtures are generated separately and provenance-stamped
(no-fake-data rule, BRIEF §0.3).

CLI:  python -m pipeline.ingest.reddit [all|<trend-slug>]
Every invocation is logged to runs/ via runlog (PROTOCOL R4), including
failures such as missing credentials.
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

import praw
from dotenv import load_dotenv

from pipeline import provenance, runlog
from pipeline.ingest import base
from pipeline.trends_config import ALL_TRENDS, HISTORY_START, SUBREDDITS, basket

# Reddit search listings return at most ~250 items; asking for more is a no-op.
SEARCH_LIMIT = 250
# ~1.1s between listings keeps total request rate far under quota.
SLEEP_BETWEEN_LISTINGS_S = 1.1

_ENV_VARS = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")


def _epoch(date_str: str) -> int:
    """Epoch seconds at UTC midnight for an ISO YYYY-MM-DD date."""
    day = datetime.datetime.fromisoformat(date_str)
    return int(day.replace(tzinfo=datetime.timezone.utc).timestamp())


def _credentials() -> dict:
    """Read Reddit credentials from the environment (dotenv loaded here,
    at call time, so importing this module never touches .env)."""
    load_dotenv()
    values = {var: os.environ.get(var, "").strip() for var in _ENV_VARS}
    missing = [var for var, value in values.items() if not value]
    if missing:
        raise base.MissingCredentials(
            "Reddit credentials missing or empty: "
            + ", ".join(missing)
            + ". Create a Reddit script app and set these in .env "
            "(see .env.example); real Reddit pulls are impossible without them."
        )
    return {
        "client_id": values["REDDIT_CLIENT_ID"],
        "client_secret": values["REDDIT_CLIENT_SECRET"],
        "user_agent": values["REDDIT_USER_AGENT"],
    }


def submission_to_item(submission) -> dict:
    """Map a PRAW Submission to the envelope reddit item schema (base.py).

    Aggregate counts and public metadata only — no author identities, no
    personal-data harvesting (BRIEF §5.1). `text` is the selftext body, or
    "" for link posts.
    """
    return {
        "id": str(submission.id),
        "created_utc": int(submission.created_utc),
        "title": str(submission.title),
        "text": str(getattr(submission, "selftext", "") or ""),
        "score": int(submission.score),
        "subreddit": str(submission.subreddit),
        "num_comments": int(submission.num_comments),
    }


def _collect_items(reddit, queries: list[str], min_created_utc: int) -> list[dict]:
    """Search every (subreddit x query) listing; filter to the history window;
    dedup by submission id (first occurrence wins). Separated from fetch() so
    tests can exercise the filter/dedup logic with fake clients — no network.
    """
    items_by_id: dict[str, dict] = {}
    for subreddit_name in SUBREDDITS:
        subreddit = reddit.subreddit(subreddit_name)
        for query in queries:
            for submission in subreddit.search(
                query, sort="new", time_filter="all", limit=SEARCH_LIMIT
            ):
                if int(submission.created_utc) < min_created_utc:
                    continue  # PROTOCOL R1: nothing outside the declared window
                item = submission_to_item(submission)
                items_by_id.setdefault(item["id"], item)
            time.sleep(SLEEP_BETWEEN_LISTINGS_S)
    return sorted(items_by_id.values(), key=lambda item: item["created_utc"])


def fetch(trend: str) -> base.Pull:
    """Pull all Reddit submissions for one trend. Raises MissingCredentials
    if the env keys are absent; returns a validated real-provenance Pull."""
    creds = _credentials()
    queries = basket(trend)["reddit_queries"]
    reddit = praw.Reddit(**creds)
    reddit.read_only = True
    min_created_utc = _epoch(HISTORY_START)
    items = _collect_items(reddit, queries, min_created_utc)
    return base.Pull(
        source="reddit",
        trend=trend,
        retrieved_at=base.now_iso(),
        provenance=provenance.REAL,
        query_spec={
            "queries": queries,
            "subreddits": list(SUBREDDITS),
            "sort": "new",
            "time_filter": "all",
            "limit": SEARCH_LIMIT,
            "min_created_utc": min_created_utc,
            "history_start": HISTORY_START,
        },
        data={"items": items},
    ).validate()


def pull_all(trends: list[str] | None = None) -> list[Path]:
    """Fetch and save raw pulls for the given trends (default: all four,
    calibration included). Logged to runs/ (PROTOCOL R4) — a failed pull is
    a logged pull."""
    targets = list(trends) if trends is not None else list(ALL_TRENDS)
    paths: list[Path] = []
    with runlog.run("ingest_reddit", notes=f"trends={targets}") as ctx:
        for trend in targets:
            pull = fetch(trend)
            path = base.save_raw(pull)
            ctx.add_output(path)
            ctx.set(f"items_{trend}", len(pull.data["items"]))
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    target = args[0] if args else "all"
    try:
        paths = pull_all(None if target == "all" else [target])
    except base.MissingCredentials as exc:
        sys.exit(f"ingest_reddit: {exc}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
