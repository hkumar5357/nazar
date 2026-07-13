"""Hermetic tests for keyed-source ingestion (reddit, youtube) + events loader.

No network, no real keys, no writes outside tmp_path. All fake objects are
MOCK_-named, synthetic, and provenance-stamped "fixture" wherever they enter
a Pull envelope (no-fake-data rule, BRIEF §0.3) — nothing here is ever
presented as real data.

dotenv hygiene: reddit._credentials() / youtube._api_key() call load_dotenv()
at call time. A developer's real .env must never leak into these tests, so
every credentials test monkeypatches the module-level load_dotenv reference
to a no-op before touching os.environ.
"""

from __future__ import annotations

import pytest

from pipeline import provenance
from pipeline.ingest import base, news_events, reddit, youtube

REDDIT_ENV = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")


def _no_dotenv(monkeypatch, module):
    """Stop load_dotenv from reading a real .env during the test."""
    monkeypatch.setattr(module, "load_dotenv", lambda *args, **kwargs: False)


# ---------------------------------------------------------------------------
# MissingCredentials
# ---------------------------------------------------------------------------


def test_reddit_missing_credentials_when_env_absent(monkeypatch):
    _no_dotenv(monkeypatch, reddit)
    for var in REDDIT_ENV:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(base.MissingCredentials) as excinfo:
        reddit.fetch("matcha")
    message = str(excinfo.value)
    for var in REDDIT_ENV:
        assert var in message  # error must name the vars to set


def test_reddit_missing_credentials_when_env_empty(monkeypatch):
    _no_dotenv(monkeypatch, reddit)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "MOCK_id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "   ")  # whitespace == empty
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)
    with pytest.raises(base.MissingCredentials) as excinfo:
        reddit.fetch("matcha")
    message = str(excinfo.value)
    assert "REDDIT_CLIENT_SECRET" in message
    assert "REDDIT_USER_AGENT" in message
    assert "REDDIT_CLIENT_ID" not in message  # that one was provided


def test_youtube_missing_credentials_when_env_absent(monkeypatch):
    _no_dotenv(monkeypatch, youtube)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(base.MissingCredentials) as excinfo:
        youtube.fetch("matcha")
    assert "YOUTUBE_API_KEY" in str(excinfo.value)


def test_youtube_missing_credentials_when_env_empty(monkeypatch):
    _no_dotenv(monkeypatch, youtube)
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    with pytest.raises(base.MissingCredentials):
        youtube.fetch("matcha")


# ---------------------------------------------------------------------------
# Reddit mapping + collection (fake PRAW objects, MOCK_ synthetic data)
# ---------------------------------------------------------------------------

EPOCH_2021_06 = 1_622_505_600  # 2021-06-01, before HISTORY_START
EPOCH_2023_06 = 1_685_577_600  # 2023-06-01, inside the window


class MockSubmission:
    """Shaped like a praw.models.Submission for mapping tests. Synthetic."""

    def __init__(self, sub_id, created_utc, title, selftext, score,
                 subreddit, num_comments):
        self.id = sub_id
        self.created_utc = created_utc
        self.title = title
        self.selftext = selftext
        self.score = score
        self.subreddit = subreddit  # praw yields an object; str() is the name
        self.num_comments = num_comments


class MockSubreddit:
    """Returns the same canned listing for every query (synthetic)."""

    def __init__(self, submissions):
        self._submissions = submissions
        self.search_calls = []

    def search(self, query, sort=None, time_filter=None, limit=None):
        self.search_calls.append(
            {"query": query, "sort": sort, "time_filter": time_filter,
             "limit": limit}
        )
        return list(self._submissions)


class MockRedditClient:
    def __init__(self, submissions):
        self._subreddit = MockSubreddit(submissions)

    def subreddit(self, name):
        return self._subreddit


MOCK_SUBMISSIONS = [
    MockSubmission("m1", EPOCH_2023_06, "MOCK matcha latte spot?",
                   "any cafe recs in indiranagar", 42, "bangalore", 7),
    MockSubmission("m2", EPOCH_2023_06 + 86_400, "MOCK matcha powder brands",
                   "", 10, "IndianFood", 3),  # link post: selftext ""
    MockSubmission("m0", EPOCH_2021_06, "MOCK pre-window post",
                   "before HISTORY_START, must be dropped", 5, "india", 1),
]


def test_submission_to_item_maps_schema_fields():
    item = reddit.submission_to_item(MOCK_SUBMISSIONS[0])
    assert item == {
        "id": "m1",
        "created_utc": EPOCH_2023_06,
        "title": "MOCK matcha latte spot?",
        "text": "any cafe recs in indiranagar",
        "score": 42,
        "subreddit": "bangalore",
        "num_comments": 7,
    }


def test_submission_to_item_link_post_text_is_empty_string():
    item = reddit.submission_to_item(MOCK_SUBMISSIONS[1])
    assert item["text"] == ""


def test_reddit_collect_filters_window_and_dedups(monkeypatch):
    monkeypatch.setattr(reddit, "SLEEP_BETWEEN_LISTINGS_S", 0)
    client = MockRedditClient(MOCK_SUBMISSIONS)
    cutoff = reddit._epoch("2022-01-01")
    # Two queries x six subreddits return the same canned listing; dedup by
    # id must collapse them, and the pre-window post must be dropped (R1).
    items = reddit._collect_items(client, ["matcha", "matcha latte"], cutoff)
    assert [i["id"] for i in items] == ["m1", "m2"]  # sorted by created_utc
    assert all(i["created_utc"] >= cutoff for i in items)
    # every (subreddit x query) listing was searched with the right params
    calls = client._subreddit.search_calls
    assert len(calls) == len(reddit.SUBREDDITS) * 2
    assert all(
        c == {"query": c["query"], "sort": "new", "time_filter": "all",
              "limit": reddit.SEARCH_LIMIT}
        for c in calls
    )


def test_reddit_items_validate_in_fixture_envelope():
    items = [reddit.submission_to_item(s) for s in MOCK_SUBMISSIONS[:2]]
    pull = base.Pull(
        source="reddit",
        trend="matcha",
        retrieved_at=base.now_iso(),
        provenance=provenance.FIXTURE,  # synthetic data is never "real"
        query_spec={"queries": ["matcha"]},
        data={"items": items},
    )
    assert pull.validate() is pull
    schema_keys = {"id", "created_utc", "title", "text", "score",
                   "subreddit", "num_comments"}
    for item in pull.data["items"]:
        assert set(item) == schema_keys
        assert isinstance(item["created_utc"], int)
        assert isinstance(item["score"], int)
        assert isinstance(item["num_comments"], int)


# ---------------------------------------------------------------------------
# YouTube mapping + collection (fake API client, MOCK_ synthetic data)
# ---------------------------------------------------------------------------

MOCK_VIDEO_FULL = {
    "id": "vidA",
    "snippet": {
        "publishedAt": "2023-08-15T09:30:00Z",
        "title": "MOCK matcha recipe",
        "description": "MOCK how to whisk matcha at home",
        "channelId": "chan1",
        "channelTitle": "MOCK Kitchen",
    },
    "statistics": {"viewCount": "1234"},
}

MOCK_VIDEO_NO_VIEWS = {
    "id": "vidB",
    "snippet": {
        "publishedAt": "2024-01-02T00:00:00Z",
        "title": "MOCK matcha vlog",
        "description": "",
        "channelId": "chan2",
        "channelTitle": "MOCK Vlogs",
    },
    "statistics": {},  # hidden view count -> view_count must be 0
}


class MockRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class MockSearch:
    """search.list stub: pages keyed by (query, pageToken). Synthetic."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def list(self, **params):
        self.calls.append(params)
        key = (params["q"], params.get("pageToken"))
        return MockRequest(self._pages[key])


class MockVideos:
    """videos.list stub returning canned resources for requested ids."""

    def __init__(self, by_id):
        self._by_id = by_id
        self.calls = []

    def list(self, **params):
        self.calls.append(params)
        ids = params["id"].split(",")
        return MockRequest(
            {"items": [self._by_id[v] for v in ids if v in self._by_id]}
        )


class MockYouTubeClient:
    def __init__(self, search_pages, videos_by_id):
        self._search = MockSearch(search_pages)
        self._videos = MockVideos(videos_by_id)

    def search(self):
        return self._search

    def videos(self):
        return self._videos


def _search_item(video_id):
    return {"id": {"kind": "youtube#video", "videoId": video_id}}


def test_video_to_item_maps_schema_fields():
    assert youtube.video_to_item(MOCK_VIDEO_FULL) == {
        "video_id": "vidA",
        "published_at": "2023-08-15T09:30:00Z",
        "title": "MOCK matcha recipe",
        "description": "MOCK how to whisk matcha at home",
        "view_count": 1234,
        "channel_id": "chan1",
        "channel_title": "MOCK Kitchen",
    }


def test_video_to_item_view_count_zero_when_absent():
    item = youtube.video_to_item(MOCK_VIDEO_NO_VIEWS)
    assert item["view_count"] == 0
    assert isinstance(item["view_count"], int)


def test_youtube_collect_paginates_and_dedups():
    pages = {
        ("q1", None): {
            "items": [_search_item("vidA"), _search_item("vidB")],
            "nextPageToken": "p2",
        },
        ("q1", "p2"): {"items": [_search_item("vidA")]},  # dup across pages
        ("q2", None): {"items": [_search_item("vidB"),  # dup across queries
                                 _search_item("vidC")]},
    }
    client = MockYouTubeClient(pages, {})
    ids = youtube._collect_video_ids(client, ["q1", "q2"], "2022-01-01T00:00:00Z")
    assert ids == ["vidA", "vidB", "vidC"]
    # request params match the declared query_spec
    first = client._search.calls[0]
    assert first["type"] == "video"
    assert first["regionCode"] == "IN"
    assert first["publishedAfter"] == "2022-01-01T00:00:00Z"
    assert first["order"] == "date"
    assert first["maxResults"] == youtube.PAGE_SIZE
    assert "pageToken" not in first  # never pass pageToken=None


def test_youtube_collect_stops_at_max_pages():
    # every page advertises another page; collection must stop at the cap
    pages = {
        ("q1", None): {"items": [_search_item("v0")], "nextPageToken": "p1"},
        ("q1", "p1"): {"items": [_search_item("v1")], "nextPageToken": "p2"},
        ("q1", "p2"): {"items": [_search_item("v2")], "nextPageToken": "p3"},
        ("q1", "p3"): {"items": [_search_item("v3")], "nextPageToken": "p4"},
    }
    client = MockYouTubeClient(pages, {})
    ids = youtube._collect_video_ids(client, ["q1"], "2022-01-01T00:00:00Z")
    assert ids == ["v0", "v1", "v2"]
    assert len(client._search.calls) == youtube.MAX_PAGES_PER_QUERY


def test_youtube_hydrate_batches_of_fifty():
    by_id = {}
    for n in range(120):
        video = {
            "id": f"v{n:03d}",
            "snippet": {"publishedAt": "2023-01-01T00:00:00Z",
                        "title": f"MOCK video {n}", "description": "",
                        "channelId": "c", "channelTitle": "MOCK"},
            "statistics": {"viewCount": str(n)},
        }
        by_id[video["id"]] = video
    client = MockYouTubeClient({}, by_id)
    items = youtube._hydrate_videos(client, sorted(by_id))
    assert len(items) == 120
    calls = client._videos.calls
    assert [len(c["id"].split(",")) for c in calls] == [50, 50, 20]
    assert all(c["part"] == "snippet,statistics" for c in calls)


def test_youtube_items_validate_in_fixture_envelope():
    items = [youtube.video_to_item(MOCK_VIDEO_FULL),
             youtube.video_to_item(MOCK_VIDEO_NO_VIEWS)]
    pull = base.Pull(
        source="youtube",
        trend="matcha",
        retrieved_at=base.now_iso(),
        provenance=provenance.FIXTURE,  # synthetic data is never "real"
        query_spec={"queries": ["MOCK"]},
        data={"items": items},
    )
    assert pull.validate() is pull
    schema_keys = {"video_id", "published_at", "title", "description",
                   "view_count", "channel_id", "channel_title"}
    for item in pull.data["items"]:
        assert set(item) == schema_keys


# ---------------------------------------------------------------------------
# news_events loader (temp CSVs in tmp_path)
# ---------------------------------------------------------------------------

HEADER = "event_id,trend,event_name,event_date,source_url,locked_at,notes\n"
GOOD_ROW = ("ev1,matcha,MOCK Costa matcha launch,2025-11-03,"
            "https://example.com/mock,2026-07-12,MOCK note\n")


def _write(tmp_path, text):
    path = tmp_path / "events.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_events_valid_file(tmp_path):
    second = ("ev2,protein_snacks,MOCK Farmley report,2026-07-01,"
              "http://example.com/mock2,2026-07-12,\n")
    events = news_events.load_events(_write(tmp_path, HEADER + GOOD_ROW + second))
    assert [e["event_id"] for e in events] == ["ev1", "ev2"]
    assert events[0]["trend"] == "matcha"
    assert events[0]["event_date"] == "2025-11-03"
    assert events[1]["notes"] == ""
    assert set(events[0]) == set(news_events.COLUMNS)


def test_load_events_missing_file_mentions_m1(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        news_events.load_events(tmp_path / "absent.csv")
    assert "Milestone 1" in str(excinfo.value)


def test_load_events_rejects_bad_header(tmp_path):
    path = _write(tmp_path, "event_id,trend,event_name\nev1,matcha,x\n")
    with pytest.raises(ValueError, match="bad header"):
        news_events.load_events(path)


def test_load_events_rejects_non_iso_date(tmp_path):
    row = ("ev1,matcha,MOCK event,03-11-2025,"
           "https://example.com,2026-07-12,\n")
    with pytest.raises(ValueError, match="event_date"):
        news_events.load_events(_write(tmp_path, HEADER + row))


def test_load_events_rejects_impossible_calendar_date(tmp_path):
    row = ("ev1,matcha,MOCK event,2025-13-40,"
           "https://example.com,2026-07-12,\n")
    with pytest.raises(ValueError, match="event_date"):
        news_events.load_events(_write(tmp_path, HEADER + row))


def test_load_events_rejects_bad_locked_at(tmp_path):
    row = ("ev1,matcha,MOCK event,2025-11-03,"
           "https://example.com,not-a-date,\n")
    with pytest.raises(ValueError, match="locked_at"):
        news_events.load_events(_write(tmp_path, HEADER + row))


def test_load_events_rejects_unknown_trend(tmp_path):
    row = ("ev1,quinoa,MOCK event,2025-11-03,"
           "https://example.com,2026-07-12,\n")
    with pytest.raises(ValueError, match="unknown trend"):
        news_events.load_events(_write(tmp_path, HEADER + row))


def test_load_events_rejects_non_http_source_url(tmp_path):
    row = "ev1,matcha,MOCK event,2025-11-03,example.com,2026-07-12,\n"
    with pytest.raises(ValueError, match="source_url"):
        news_events.load_events(_write(tmp_path, HEADER + row))


def test_load_events_rejects_duplicate_event_id(tmp_path):
    with pytest.raises(ValueError, match="duplicate event_id"):
        news_events.load_events(_write(tmp_path, HEADER + GOOD_ROW + GOOD_ROW))


def test_load_events_reports_all_problems_at_once(tmp_path):
    bad = "ev1,quinoa,MOCK event,2025-13-40,ftp://x,2026-07-12,\n"
    with pytest.raises(ValueError) as excinfo:
        news_events.load_events(_write(tmp_path, HEADER + bad))
    message = str(excinfo.value)
    assert "unknown trend" in message
    assert "event_date" in message
    assert "source_url" in message
