"""YouTube Data API v3 ingestion. Public search/upload metadata only.

For each trend, runs every query in basket["youtube_queries"] through
search.list (type=video, regionCode=IN, order=date, publishedAfter=
HISTORY_START), paginating at most MAX_PAGES_PER_QUERY pages of 50 results.
The collected video ids are deduplicated and hydrated in batches of 50 via
videos.list (part=snippet,statistics) for title/description/publishedAt/
viewCount/channel. One "youtube" envelope per trend, provenance="real".

Quota budget (default daily quota is 10,000 units):
  - search.list costs 100 units per call. 3 pages x 3 queries = 9 calls
    = 900 units per trend; 4 trends (3 demo + calibration) = 3,600 units.
  - videos.list costs 1 unit per call. At most 150 ids per query
    (3 pages x 50) x 3 queries = 450 ids per trend = 9 videos.list calls
    (50 ids each) = 9 units per trend; 36 units for all four trends.
  Total worst case ~3,636 units per full pull_all — comfortably inside one
  day's quota with room for a complete re-run (BRIEF §5.1: stay far under
  quotas).

Honest limitation (declared, not hidden): search.list relevance/date ordering
is not an exhaustive archive; with order=date and 3 pages we capture at most
150 of the most recent uploads per query at pull time, so older 2022-2024
coverage depends on when the pull happens. This is a property of the public
API and is documented here and in LABNOTES.

Credentials: YOUTUBE_API_KEY is loaded from the environment (python-dotenv,
called at fetch time — never at import time). Missing/empty raises
base.MissingCredentials; there is no silent fixture fallback (no-fake-data
rule, BRIEF §0.3).

CLI:  python -m pipeline.ingest.youtube [all|<trend-slug>]
Every invocation is logged to runs/ via runlog (PROTOCOL R4), including
failures such as missing credentials.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

from pipeline import provenance, runlog
from pipeline.ingest import base
from pipeline.trends_config import ALL_TRENDS, GEO, HISTORY_START, basket

# search.list costs 100 units/page; 3 pages x 50 = up to 150 ids per query.
MAX_PAGES_PER_QUERY = 3
PAGE_SIZE = 50  # API maximum for both search.list and videos.list

_ENV_VAR = "YOUTUBE_API_KEY"


def _rfc3339(date_str: str) -> str:
    """HISTORY_START (YYYY-MM-DD) as the RFC3339 timestamp the API expects."""
    return f"{date_str}T00:00:00Z"


def _api_key() -> str:
    """Read the API key from the environment (dotenv loaded here, at call
    time, so importing this module never touches .env)."""
    load_dotenv()
    key = os.environ.get(_ENV_VAR, "").strip()
    if not key:
        raise base.MissingCredentials(
            f"{_ENV_VAR} is missing or empty. Create a YouTube Data API v3 "
            "key in Google Cloud Console and set it in .env "
            "(see .env.example); real YouTube pulls are impossible without it."
        )
    return key


def video_to_item(video: dict) -> dict:
    """Map one videos.list resource to the envelope youtube item schema
    (base.py). view_count is an int, 0 when the API omits it (hidden
    view counts). Public metadata only."""
    snippet = video.get("snippet", {})
    statistics = video.get("statistics", {})
    return {
        "video_id": str(video["id"]),
        "published_at": str(snippet.get("publishedAt", "")),
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "view_count": int(statistics.get("viewCount", 0) or 0),
        "channel_id": str(snippet.get("channelId", "")),
        "channel_title": str(snippet.get("channelTitle", "")),
    }


def _collect_video_ids(youtube, queries: list[str], published_after: str) -> list[str]:
    """search.list every query, paginating at most MAX_PAGES_PER_QUERY pages;
    dedup ids across pages and queries, preserving first-seen order.
    Separated from fetch() so tests can exercise pagination/dedup with fake
    clients — no network."""
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for query in queries:
        page_token = None
        for _ in range(MAX_PAGES_PER_QUERY):
            params = {
                "q": query,
                "part": "id",
                "type": "video",
                "regionCode": GEO,
                "publishedAfter": published_after,
                "order": "date",
                "maxResults": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            response = youtube.search().list(**params).execute()
            for entry in response.get("items", []):
                video_id = entry.get("id", {}).get("videoId")
                if video_id and video_id not in seen:
                    seen.add(video_id)
                    ordered_ids.append(video_id)
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    return ordered_ids


def _hydrate_videos(youtube, video_ids: list[str]) -> list[dict]:
    """videos.list the collected ids in batches of 50 (1 quota unit each)."""
    items: list[dict] = []
    for start in range(0, len(video_ids), PAGE_SIZE):
        batch = video_ids[start : start + PAGE_SIZE]
        response = (
            youtube.videos()
            .list(part="snippet,statistics", id=",".join(batch), maxResults=PAGE_SIZE)
            .execute()
        )
        items.extend(video_to_item(video) for video in response.get("items", []))
    return items


def fetch(trend: str) -> base.Pull:
    """Pull YouTube video metadata for one trend. Raises MissingCredentials
    if YOUTUBE_API_KEY is absent; returns a validated real-provenance Pull."""
    key = _api_key()
    queries = basket(trend)["youtube_queries"]
    published_after = _rfc3339(HISTORY_START)
    youtube = build("youtube", "v3", developerKey=key)
    video_ids = _collect_video_ids(youtube, queries, published_after)
    items = _hydrate_videos(youtube, video_ids)
    # Belt-and-braces for PROTOCOL R1: publishedAfter is enforced server-side,
    # but nothing outside the declared history window may enter the envelope.
    items = [i for i in items if i["published_at"] >= published_after[:10]]
    return base.Pull(
        source="youtube",
        trend=trend,
        retrieved_at=base.now_iso(),
        provenance=provenance.REAL,
        query_spec={
            "queries": queries,
            "region_code": GEO,
            "published_after": published_after,
            "order": "date",
            "max_pages_per_query": MAX_PAGES_PER_QUERY,
            "page_size": PAGE_SIZE,
        },
        data={"items": items},
    ).validate()


def pull_all(trends: list[str] | None = None) -> list[Path]:
    """Fetch and save raw pulls for the given trends (default: all four,
    calibration included). Logged to runs/ (PROTOCOL R4) — a failed pull is
    a logged pull."""
    targets = list(trends) if trends is not None else list(ALL_TRENDS)
    paths: list[Path] = []
    with runlog.run("ingest_youtube", notes=f"trends={targets}") as ctx:
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
        sys.exit(f"ingest_youtube: {exc}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
