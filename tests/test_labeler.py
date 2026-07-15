"""Hermetic tests for the LLM labeling stack -- PROTOCOL R5's ONLY LLM use.

No network: llm_client.requests.post is always monkeypatched to a fake
responder here; nothing in this file makes a real HTTP call. No real API
keys: every key env var is deleted/set to a MOCK_ value via monkeypatch,
and load_dotenv is stubbed to a no-op so a developer's real .env can never
leak in (same convention as tests/test_keyed_ingest.py). All label-cache
writes happen under tmp_path via a monkeypatched intent_labeler.LABELS_DIR,
never under the repo's real data/labels/.
"""

from __future__ import annotations

import csv
import datetime
import json

import pytest

from pipeline import provenance
from pipeline.ingest import base
from pipeline.label import intent_labeler, llm_client, prompts
from scripts import score_qa


def _no_dotenv(monkeypatch, module):
    monkeypatch.setattr(module, "load_dotenv", lambda *a, **k: False)


def _clear_llm_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for var in (
        "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "GEMINI_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def _epoch(date_str: str) -> int:
    return int(
        datetime.datetime.fromisoformat(date_str)
        .replace(tzinfo=datetime.timezone.utc)
        .timestamp()
    )


def _reddit_item(item_id, date_str, title, text):
    return {
        "id": item_id, "created_utc": _epoch(date_str), "title": title,
        "text": text, "score": 1, "subreddit": "india", "num_comments": 0,
    }


def _youtube_item(video_id, iso_datetime, title, description):
    return {
        "video_id": video_id, "published_at": iso_datetime, "title": title,
        "description": description, "view_count": 0, "channel_id": "c",
        "channel_title": "c",
    }


def _pull(source, trend, items, kind=provenance.FIXTURE):
    return base.Pull(
        source=source, trend=trend, retrieved_at="2026-07-12T00:00:00+00:00",
        provenance=kind, query_spec={}, data={"items": items},
    )


class FakeLLM:
    """Records call count; returns a fixed label. Stands in for
    llm_client.label_text in tests -- no network, no real key."""

    def __init__(self, label="cafe_experience"):
        self.label = label
        self.calls = 0

    def label_text(self, text):
        self.calls += 1
        return {
            "label": self.label, "provider": "fake", "model": "fake-model",
            "tokens_in": 5, "tokens_out": 2,
        }


class FakeResponse:
    def __init__(self, json_body):
        self._json_body = json_body

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_body


# ---------------------------------------------------------------------------
# Keyword heuristic (h1)
# ---------------------------------------------------------------------------


def test_heuristic_classifies_cafe_experience():
    text = "the barista at the outlet made an amazing matcha, ordered a second one off the menu"
    assert intent_labeler._heuristic_label(text) == "cafe_experience"


def test_heuristic_classifies_home_or_cpg():
    text = "bought a pack of matcha powder on amazon, whisking it up at home with this recipe"
    assert intent_labeler._heuristic_label(text) == "home_or_CPG"


def test_heuristic_classifies_other_when_no_keywords_hit():
    text = "lol matcha is just green tea marketing, so overrated"
    assert intent_labeler._heuristic_label(text) == "other"


def test_heuristic_falls_back_to_other_on_a_tie():
    text = "ordered a pack of it online"
    cafe_hits = sum(1 for kw in prompts.CAFE_KEYWORDS if kw in text.lower())
    home_hits = sum(1 for kw in prompts.HOME_CPG_KEYWORDS if kw in text.lower())
    assert cafe_hits == home_hits == 1  # sanity: this text is a deliberate 1-1 tie
    assert intent_labeler._heuristic_label(text) == "other"


def test_keyword_lists_are_well_formed():
    assert len(prompts.CAFE_KEYWORDS) >= 12
    assert len(prompts.HOME_CPG_KEYWORDS) >= 12
    assert prompts.KEYWORD_HEURISTIC_VERSION == "h1"
    assert prompts.PROMPT_VERSION == "v1"


# ---------------------------------------------------------------------------
# item_id / item_text extraction
# ---------------------------------------------------------------------------


def test_item_id_and_text_reddit():
    item = _reddit_item("r1", "2026-01-05", "Title here", "Body here")
    assert intent_labeler.item_id("reddit", item) == "r1"
    assert intent_labeler.item_text("reddit", item) == "Title here\nBody here"


def test_item_id_and_text_youtube():
    item = _youtube_item("v1", "2026-01-05T00:00:00Z", "Vid title", "Vid desc")
    assert intent_labeler.item_id("youtube", item) == "v1"
    assert intent_labeler.item_text("youtube", item) == "Vid title\nVid desc"


# ---------------------------------------------------------------------------
# label_items: cache-first behavior
# ---------------------------------------------------------------------------


def test_label_items_cache_first_warm_rerun_makes_zero_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [
        _reddit_item("r1", "2026-01-05", "loved the outlet barista", "ordered at the cafe"),
        _reddit_item("r2", "2026-01-06", "made it at home", "with matcha powder from amazon"),
    ]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)

    fake = FakeLLM()
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: True)
    monkeypatch.setattr(intent_labeler.llm_client, "label_text", fake.label_text)

    first = intent_labeler.label_items("matcha", "reddit")
    assert first["calls_made"] == 2
    assert fake.calls == 2

    second = intent_labeler.label_items("matcha", "reddit")
    assert second["calls_made"] == 0
    assert fake.calls == 2  # warm re-run: zero new API calls

    cache = intent_labeler.load_cache(intent_labeler.cache_path("matcha", "reddit"))
    assert set(cache) == {"r1", "r2"}
    assert all(len(records) == 1 for records in cache.values())
    assert all(records[0]["method"] == "llm" for records in cache.values())


def test_label_items_missing_key_selects_heuristic_method(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [_reddit_item("r1", "2026-01-05", "outlet barista menu", "ordered")]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: False)

    def _boom(text):
        raise AssertionError("label_text must not be called when no key is configured")

    monkeypatch.setattr(intent_labeler.llm_client, "label_text", _boom)

    summary = intent_labeler.label_items("matcha", "reddit")
    assert summary["method"] == "heuristic"
    assert summary["calls_made"] == 0

    record = intent_labeler.load_cache(intent_labeler.cache_path("matcha", "reddit"))["r1"][0]
    assert record["method"] == "heuristic"
    assert record["provider"] is None
    assert record["model"] is None
    assert record["prompt_version"] == prompts.KEYWORD_HEURISTIC_VERSION
    assert record["label"] == "cafe_experience"


def test_label_items_degrades_to_heuristic_if_llm_raises_missing_key_midrun(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [_reddit_item("r1", "2026-01-05", "outlet barista menu", "ordered")]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: True)

    def _raise(text):
        raise llm_client.MissingLLMKey("key vanished mid-run")

    monkeypatch.setattr(intent_labeler.llm_client, "label_text", _raise)

    summary = intent_labeler.label_items("matcha", "reddit")
    assert summary["method"] == "heuristic"
    assert summary["calls_made"] == 0
    record = intent_labeler.load_cache(intent_labeler.cache_path("matcha", "reddit"))["r1"][0]
    assert record["method"] == "heuristic"


def test_label_items_never_mixes_llm_wins_and_heuristic_line_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [_reddit_item("r1", "2026-01-05", "outlet barista menu", "ordered")]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)

    # Pass 1: no key -> heuristic label written.
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: False)
    intent_labeler.label_items("matcha", "reddit")

    # Pass 2: a real key has now arrived -> llm label appended, not overwritten.
    fake = FakeLLM(label="home_or_CPG")
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: True)
    monkeypatch.setattr(intent_labeler.llm_client, "label_text", fake.label_text)
    summary = intent_labeler.label_items("matcha", "reddit")
    assert summary["calls_made"] == 1
    assert fake.calls == 1

    records = intent_labeler.load_cache(intent_labeler.cache_path("matcha", "reddit"))["r1"]
    assert len(records) == 2
    assert {r["method"] for r in records} == {"heuristic", "llm"}

    winner = intent_labeler._pick_record(records, records[0]["text_sha256"])
    assert winner["method"] == "llm"
    assert winner["label"] == "home_or_CPG"


# ---------------------------------------------------------------------------
# build_intent_split: weekly bucketing + provenance
# ---------------------------------------------------------------------------


def test_build_intent_split_weekly_bucketing_and_fixture_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)

    # 2026-01-05 (Mon) and 2026-01-06 (Tue) both fall in the Sunday-week
    # starting 2026-01-04; 2026-01-13 (Tue) falls in the next week (2026-01-11).
    reddit_items = [
        _reddit_item("r1", "2026-01-05", "ordered at the cafe outlet", "barista menu"),
        _reddit_item("r2", "2026-01-06", "made at home", "matcha powder from amazon"),
    ]
    youtube_items = [
        _youtube_item("y1", "2026-01-13T00:00:00Z", "random meme video", "lol"),
    ]
    reddit_pull = _pull("reddit", "matcha", reddit_items)
    youtube_pull = _pull("youtube", "matcha", youtube_items)

    def fake_latest(source, trend):
        return {"reddit": reddit_pull, "youtube": youtube_pull}.get(source)

    monkeypatch.setattr(base, "latest", fake_latest)
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: False)
    intent_labeler.label_items("matcha", "reddit")
    intent_labeler.label_items("matcha", "youtube")

    split = intent_labeler.build_intent_split("matcha")

    assert split["trend"] == "matcha"
    assert split["method_used"] == "heuristic"
    assert split["label_provenance"] == "fixture_heuristic"
    assert split["provenance"]["contains_fixture_data"] is True
    assert split["provenance"]["sources"] == {
        "labels": provenance.FIXTURE_HEURISTIC, "items": provenance.FIXTURE,
    }
    assert split["input_provenance"] == provenance.FIXTURE

    weeks = {w["week"]: w for w in split["weekly"]}
    assert "2026-01-04" in weeks
    assert "2026-01-11" in weeks
    week1 = weeks["2026-01-04"]
    assert week1["cafe_experience"] + week1["home_or_CPG"] + week1["other"] == 2
    week2 = weeks["2026-01-11"]
    assert week2["cafe_experience"] + week2["home_or_CPG"] + week2["other"] == 1

    out_path = tmp_path / "intent_split_matcha.json"
    assert out_path.exists()
    assert json.loads(out_path.read_text()) == split
    # determinism: no generation timestamp anywhere in the artifact
    assert "generated_at" not in out_path.read_text()


def test_build_intent_split_real_provenance_when_every_label_is_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [_reddit_item("r1", "2026-02-02", "t", "t")]
    pull = _pull("reddit", "matcha", items, kind=provenance.REAL)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)

    fake = FakeLLM(label="other")
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: True)
    monkeypatch.setattr(intent_labeler.llm_client, "label_text", fake.label_text)
    intent_labeler.label_items("matcha", "reddit")

    split = intent_labeler.build_intent_split("matcha")
    assert split["method_used"] == "llm"
    assert split["label_provenance"] == "real"
    assert split["provenance"]["contains_fixture_data"] is False
    assert split["input_provenance"] == provenance.REAL


def test_build_intent_split_skips_items_never_labeled(tmp_path, monkeypatch):
    # A pull with an item that was never run through label_items -- the
    # split must skip it rather than fabricate a label for it.
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [_reddit_item("r1", "2026-01-05", "t", "t")]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)

    split = intent_labeler.build_intent_split("matcha")
    assert split["weekly"] == []
    assert split["method_used"] == "none"
    assert split["label_provenance"] == "fixture_heuristic"


# ---------------------------------------------------------------------------
# llm_client: has_api_key / MissingLLMKey
# ---------------------------------------------------------------------------


def test_has_api_key_true_when_configured(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "MOCK_key")
    assert llm_client.has_api_key() is True


def test_has_api_key_false_when_absent(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    assert llm_client.has_api_key() is False


def test_has_api_key_defaults_to_gemini_provider(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "MOCK_key")
    assert llm_client.has_api_key() is True


def test_label_text_missing_key_raises_missing_llm_key(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(llm_client.MissingLLMKey):
        llm_client.label_text("some text")


def test_missing_llm_key_is_reexported_from_label_package():
    import pipeline.label as label_pkg

    assert label_pkg.MissingLLMKey is llm_client.MissingLLMKey


# ---------------------------------------------------------------------------
# llm_client: response parsing (mocked requests, one per provider)
# ---------------------------------------------------------------------------


def test_label_text_gemini_success(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "MOCK_key")

    def fake_post(url, params=None, json=None, timeout=None):
        assert "generativelanguage.googleapis.com" in url
        assert params["key"] == "MOCK_key"
        assert json["generationConfig"]["temperature"] == 0
        return FakeResponse({
            "candidates": [{"content": {"parts": [{"text": '{"label": "cafe_experience"}'}]}}],
            "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 6},
        })

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    result = llm_client.label_text("some post text")
    assert result == {
        "label": "cafe_experience", "provider": "gemini",
        "model": "gemini-2.5-flash", "tokens_in": 40, "tokens_out": 6,
    }


def test_label_text_openai_success(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "MOCK_key")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer MOCK_key"
        assert json["temperature"] == 0
        return FakeResponse({
            "choices": [{"message": {"content": '{"label": "home_or_CPG"}'}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 5},
        })

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    result = llm_client.label_text("some post text")
    assert result == {
        "label": "home_or_CPG", "provider": "openai",
        "model": "gpt-5-mini", "tokens_in": 30, "tokens_out": 5,
    }


def test_label_text_anthropic_success_uses_pinned_default_model(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "MOCK_key")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "MOCK_key"
        assert headers["anthropic-version"] == "2023-06-01"
        assert json["temperature"] == 0
        assert json["model"] == "claude-haiku-4-5-20251001"
        return FakeResponse({
            "content": [{"type": "text", "text": '{"label": "other"}'}],
            "usage": {"input_tokens": 55, "output_tokens": 8},
        })

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    result = llm_client.label_text("some post text")
    assert result == {
        "label": "other", "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001", "tokens_in": 55, "tokens_out": 8,
    }


def test_label_text_respects_model_env_override(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "MOCK_key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-MOCK-override")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert json["model"] == "claude-MOCK-override"
        return FakeResponse({
            "content": [{"type": "text", "text": '{"label": "other"}'}],
            "usage": {},
        })

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    result = llm_client.label_text("x")
    assert result["model"] == "claude-MOCK-override"
    assert result["tokens_in"] == 0  # absent usage fields default to 0
    assert result["tokens_out"] == 0


def test_label_text_retries_once_on_garbage_then_succeeds(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "MOCK_key")

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        text = "not json at all" if len(calls) == 1 else '{"label": "cafe_experience"}'
        return FakeResponse({
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        })

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    result = llm_client.label_text("x")
    assert len(calls) == 2
    assert result["label"] == "cafe_experience"


def test_label_text_raises_after_two_garbage_responses(monkeypatch):
    _no_dotenv(monkeypatch, llm_client)
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "MOCK_key")

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return FakeResponse({
            "content": [{"type": "text", "text": "still not json"}],
            "usage": {},
        })

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    with pytest.raises(ValueError):
        llm_client.label_text("x")
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# score_qa
# ---------------------------------------------------------------------------


def test_score_qa_refuses_when_cache_is_heuristic_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    items = [_reddit_item("r1", "2026-01-05", "outlet barista menu", "ordered")]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: False)
    intent_labeler.label_items("matcha", "reddit")

    result = score_qa.generate_sample("matcha")
    assert result is None
    captured = capsys.readouterr()
    assert "QA sample is for real LLM labels; none exist yet" in captured.out


def test_score_qa_refuses_when_no_labels_exist_at_all(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    monkeypatch.setattr(base, "latest", lambda source, trend: None)
    result = score_qa.generate_sample("matcha")
    assert result is None
    assert "none exist yet" in capsys.readouterr().out


def test_score_qa_generates_sample_when_llm_labels_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_labeler, "LABELS_DIR", tmp_path)
    out_path = tmp_path / "qa_sample_50.csv"
    monkeypatch.setattr(score_qa, "QA_SAMPLE_PATH", out_path)

    items = [
        _reddit_item(f"r{i}", "2026-01-05", f"item {i}", "text")
        for i in range(5)
    ]
    pull = _pull("reddit", "matcha", items)
    monkeypatch.setattr(base, "latest", lambda source, trend: pull if source == "reddit" else None)

    fake = FakeLLM(label="cafe_experience")
    monkeypatch.setattr(intent_labeler.llm_client, "has_api_key", lambda: True)
    monkeypatch.setattr(intent_labeler.llm_client, "label_text", fake.label_text)
    intent_labeler.label_items("matcha", "reddit")

    result = score_qa.generate_sample("matcha", n=3, seed=1)
    assert result == out_path
    assert out_path.exists()
    with out_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert list(rows[0]) == list(score_qa.CSV_FIELDS)
    assert all(r["human_label"] == "" for r in rows)
    assert {r["item_id"] for r in rows} <= {f"r{i}" for i in range(5)}


def test_score_computes_agreement_rate(tmp_path):
    csv_path = tmp_path / "sample.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(score_qa.CSV_FIELDS)
        writer.writerow(["r1", "text a", "cafe_experience", "cafe_experience"])
        writer.writerow(["r2", "text b", "home_or_CPG", "other"])
        writer.writerow(["r3", "text c", "other", ""])  # not yet reviewed

    rate = score_qa.score(csv_path)
    assert rate == pytest.approx(0.5)


def test_score_returns_zero_when_nothing_reviewed(tmp_path, capsys):
    csv_path = tmp_path / "sample.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(score_qa.CSV_FIELDS)
        writer.writerow(["r1", "text a", "cafe_experience", ""])

    rate = score_qa.score(csv_path)
    assert rate == 0.0
    assert "no reviewed rows" in capsys.readouterr().out
