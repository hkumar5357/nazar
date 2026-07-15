"""Map slice tests (BRIEF §5.5, PROTOCOL A3): taxonomy vectorization,
engagement clamp, rank determinism, validation-pair logic, creator data
loading, and the affinity board's fixture-provenance flag.

Everything here is hermetic: taxonomy tests are pure-function tests on
in-memory strings; affinity tests build synthetic in-memory creator
payloads (never real fixtures) and call score_all()/run_validation()
directly or via affinity.main() with every directory monkeypatched into
tmp_path, mirroring the pattern tests/test_trends_ingest.py and
tests/test_keyed_ingest.py already use for this repo's ingestion tests. No
network, no real API keys, no writes outside tmp_path.
"""

from __future__ import annotations

import json
import math

import pytest

from pipeline import provenance, runlog
from pipeline.ingest import base as ingest_base
from pipeline.ingest import youtube as yt_ingest
from pipeline.map import affinity, taxonomy
from pipeline.map import creators as creators_mod
from pipeline.map.creators import Creator

# ---------------------------------------------------------------------------
# taxonomy.vectorize / mix_vector / cosine
# ---------------------------------------------------------------------------


def test_vectorize_zero_vector_for_no_hits():
    vec = taxonomy.vectorize(["completely unrelated filler text, no matches here"])
    assert set(vec) == set(taxonomy.TOPICS)
    assert all(v == 0.0 for v in vec.values())


def test_vectorize_empty_texts_list_is_zero_vector():
    vec = taxonomy.vectorize([])
    assert all(v == 0.0 for v in vec.values())


def test_vectorize_single_topic_normalizes_to_one():
    # Only tea_cafe keywords fire ("matcha" x2); after L2-normalize across
    # 10 topics a single-topic hit vector always collapses to exactly 1.0
    # in that topic and 0.0 everywhere else.
    vec = taxonomy.vectorize(["Matcha latte review", "Best matcha in town"])
    assert vec["tea_cafe"] == pytest.approx(1.0)
    assert all(v == 0.0 for topic, v in vec.items() if topic != "tea_cafe")


def test_vectorize_counts_multiple_topics_before_normalizing():
    vec = taxonomy.vectorize(["protein shake and a matcha latte after the gym workout"])
    norm = math.sqrt(sum(v * v for v in vec.values()))
    assert norm == pytest.approx(1.0)  # L2-normalized across the 10 topics
    assert vec["protein_fitness"] > 0  # protein, gym, workout
    assert vec["tea_cafe"] > 0  # matcha, latte
    # protein_fitness has 3 keyword hits (protein, gym, workout) vs
    # tea_cafe's 2 (matcha, latte) -> protein_fitness carries more weight.
    assert vec["protein_fitness"] > vec["tea_cafe"]


def test_vectorize_lowercases_before_matching():
    vec = taxonomy.vectorize(["MATCHA Latte RECIPE"])
    assert vec["tea_cafe"] > 0


def test_vectorize_counts_repeated_occurrences_within_one_text():
    single = taxonomy.vectorize(["matcha"])
    doubled = taxonomy.vectorize(["matcha matcha"])
    # Both are single-topic -> both normalize to 1.0; the raw hit count
    # (pre-normalize) is what differs, so compare via a topic that has a
    # genuine second signal to prove the count, not just the unit vector.
    mixed_single = taxonomy.vectorize(["matcha and a gym workout"])
    mixed_doubled = taxonomy.vectorize(["matcha matcha and a gym workout"])
    assert single["tea_cafe"] == pytest.approx(1.0)
    assert doubled["tea_cafe"] == pytest.approx(1.0)
    # With a fixed protein_fitness count (2 hits: gym, workout) and a
    # growing tea_cafe count (1 -> 2), tea_cafe's normalized share rises.
    assert mixed_doubled["tea_cafe"] > mixed_single["tea_cafe"]


def test_mix_vector_zero_fills_unmentioned_topics():
    mv = taxonomy.mix_vector({"tea_cafe": 0.6, "cooking_baking": 0.4})
    assert mv["tea_cafe"] == 0.6
    assert mv["cooking_baking"] == 0.4
    assert mv["fragrance_grooming"] == 0.0
    assert set(mv) == set(taxonomy.TOPICS)


def test_mix_vector_rejects_unknown_topic():
    with pytest.raises(ValueError, match="unknown topic"):
        taxonomy.mix_vector({"not_a_real_topic": 1.0})


def test_cosine_zero_vector_is_zero_not_a_crash():
    zero = {t: 0.0 for t in taxonomy.TOPICS}
    other = {t: (1.0 if t == "tea_cafe" else 0.0) for t in taxonomy.TOPICS}
    assert taxonomy.cosine(zero, other) == 0.0
    assert taxonomy.cosine(zero, zero) == 0.0


def test_cosine_identical_vectors_is_one():
    vec = taxonomy.vectorize(["matcha latte matcha latte cafe brew"])
    assert taxonomy.cosine(vec, vec) == pytest.approx(1.0)


def test_cosine_orthogonal_topics_is_zero():
    tea = taxonomy.vectorize(["matcha latte cafe brew"])
    tech = taxonomy.vectorize(["smartphone unboxing benchmark laptop"])
    assert taxonomy.cosine(tea, tech) == 0.0


def test_trend_topic_mix_entries_sum_to_one():
    for trend, mix in taxonomy.TREND_TOPIC_MIX.items():
        assert sum(mix.values()) == pytest.approx(1.0), trend
        assert set(mix) <= set(taxonomy.TOPICS)


# ---------------------------------------------------------------------------
# engagement: raw ratio + cross-creator normalize/clamp
# ---------------------------------------------------------------------------


def _mock_creator_payload(subscribers, view_counts, prov=provenance.FIXTURE, texts=None):
    texts = texts if texts is not None else ["filler text"] * len(view_counts)
    videos = [
        {
            "video_id": f"v{i}",
            "published_at": "2026-01-01T00:00:00+05:30",
            "title": t,
            "description": "",
            "view_count": vc,
        }
        for i, (t, vc) in enumerate(zip(texts, view_counts))
    ]
    return {
        "channel_id": "MOCK_UC_x",
        "channel_title": "MOCK Creator",
        "subscribers": subscribers,
        "retrieved_at": "2026-01-01T00:00:00+05:30",
        "provenance": prov,
        "videos": videos,
    }


def test_engagement_raw_is_median_views_over_subscribers():
    payload = _mock_creator_payload(1000, [10, 20, 30])
    assert affinity.creator_engagement_raw(payload) == pytest.approx(20 / 1000)


def test_engagement_raw_zero_when_no_videos_or_no_subscribers():
    assert affinity.creator_engagement_raw(_mock_creator_payload(1000, [])) == 0.0
    assert affinity.creator_engagement_raw(_mock_creator_payload(0, [10])) == 0.0


def test_normalize_engagement_clamps_high_and_low():
    # median of {100, 1, 0.0001} is 1.0 -> pivot = 1.0
    raw = {"a": 100.0, "b": 1.0, "c": 0.0001}
    out = affinity.normalize_engagement(raw)
    assert out["a"] == affinity.ENGAGEMENT_MAX  # far above pivot -> ceiling
    assert out["c"] == affinity.ENGAGEMENT_MIN  # far below pivot -> floor
    assert out["b"] == pytest.approx(1.0)  # at the pivot -> unclamped


def test_normalize_engagement_mid_range_value_is_unclamped():
    raw = {"a": 3.0, "b": 2.0, "c": 1.0}  # median = 2.0 -> pivot
    out = affinity.normalize_engagement(raw)
    assert out["b"] == pytest.approx(1.0)
    assert affinity.ENGAGEMENT_MIN < out["a"] < affinity.ENGAGEMENT_MAX
    assert out["a"] == pytest.approx(1.5)  # 3/2, strictly inside the clamp band


def test_normalize_engagement_degenerate_all_zero_falls_back_to_floor():
    out = affinity.normalize_engagement({"a": 0.0, "b": 0.0})
    assert out == {"a": affinity.ENGAGEMENT_MIN, "b": affinity.ENGAGEMENT_MIN}


# ---------------------------------------------------------------------------
# rank determinism
# ---------------------------------------------------------------------------


def test_rank_trend_best_score_is_rank_one():
    ranks = affinity.rank_trend({"a": 0.1, "b": 0.9, "c": 0.5})
    assert ranks == {"b": 1, "c": 2, "a": 3}


def test_rank_trend_ties_break_by_slug_ascending():
    ranks = affinity.rank_trend({"zeta": 0.5, "alpha": 0.5, "mid": 0.9})
    assert ranks == {"mid": 1, "alpha": 2, "zeta": 3}


def test_rank_trend_is_deterministic_across_repeated_calls():
    scores = {"c": 0.3, "a": 0.3, "b": 0.7, "d": 0.1}
    first = affinity.rank_trend(scores)
    for _ in range(5):
        assert affinity.rank_trend(dict(scores)) == first


# ---------------------------------------------------------------------------
# PROTOCOL A3 validation-pair logic — synthetic creators engineered to
# both pass and fail, independent of any real fixture data.
# ---------------------------------------------------------------------------


def _creators(specs):
    return [Creator(slug=s, name=s, niche=n, is_control=c) for s, n, c in specs]


VALIDATION_CREATORS = _creators(
    [
        ("fit_alpha", affinity.FITNESS_NICHE, False),
        ("fit_beta", affinity.FITNESS_NICHE, False),
        ("technical_guruji", "tech_gadgets", True),
        ("lifestyle_a", "fashion_lifestyle", False),
        ("lifestyle_b", "fashion_lifestyle", False),
    ]
)
# 5 creators total -> bottom-3 floor = 5 - 3 + 1 = 3 (rank >= 3 passes).


def test_run_validation_both_checks_pass():
    ranks_by_trend = {
        "protein_snacks": {
            "fit_alpha": 1, "fit_beta": 4, "technical_guruji": 5,
            "lifestyle_a": 2, "lifestyle_b": 3,
        },
        "matcha": {
            "fit_alpha": 2, "fit_beta": 1, "technical_guruji": 5,
            "lifestyle_a": 3, "lifestyle_b": 4,
        },
    }
    checks = affinity.run_validation(ranks_by_trend, VALIDATION_CREATORS)
    assert len(checks) == 2
    assert all(c["pass"] for c in checks)
    fitness_check = next(c for c in checks if "protein_snacks" in c["check"])
    assert fitness_check["actual"] == "fit_alpha rank 1"
    tech_check = next(c for c in checks if "matcha" in c["check"])
    assert tech_check["actual"] == "technical_guruji rank 5"


def test_run_validation_both_checks_fail():
    # Best fitness creator ranks 4th of 5 (misses top 3); tech control
    # ranks 1st for matcha (misses bottom 3) -> both checks fail.
    ranks_by_trend = {
        "protein_snacks": {
            "fit_alpha": 4, "fit_beta": 5, "technical_guruji": 1,
            "lifestyle_a": 2, "lifestyle_b": 3,
        },
        "matcha": {
            "fit_alpha": 3, "fit_beta": 4, "technical_guruji": 1,
            "lifestyle_a": 2, "lifestyle_b": 5,
        },
    }
    checks = affinity.run_validation(ranks_by_trend, VALIDATION_CREATORS)
    assert len(checks) == 2
    assert all(not c["pass"] for c in checks)


def test_run_validation_picks_best_of_several_fitness_creators():
    # fit_beta (rank 1) is better than fit_alpha (rank 4); the check must
    # follow the BEST fitness creator, not the first one in the list.
    ranks_by_trend = {
        "protein_snacks": {
            "fit_alpha": 4, "fit_beta": 1, "technical_guruji": 5,
            "lifestyle_a": 2, "lifestyle_b": 3,
        },
    }
    checks = affinity.run_validation(ranks_by_trend, VALIDATION_CREATORS)
    assert len(checks) == 1
    assert checks[0]["actual"] == "fit_beta rank 1"
    assert checks[0]["pass"] is True


def test_run_validation_skips_checks_with_no_applicable_creators():
    # No fitness-niche creator and no technical_guruji slug -> neither
    # check is applicable; run_validation degrades gracefully (no crash,
    # no fabricated result) rather than asserting something meaningless.
    creators = _creators([("lifestyle_only", "fashion_lifestyle", False)])
    checks = affinity.run_validation(
        {"protein_snacks": {"lifestyle_only": 1}, "matcha": {"lifestyle_only": 1}},
        creators,
    )
    assert checks == []


# ---------------------------------------------------------------------------
# score_all() end-to-end on synthetic in-memory payloads (no disk I/O)
# ---------------------------------------------------------------------------


def test_score_all_ranks_ordering_and_deterministic_creator_order():
    creators = _creators(
        [("cafe_x", "tea_cafe", False), ("technical_guruji", "tech_gadgets", True)]
    )
    payloads = {
        "cafe_x": _mock_creator_payload(
            1000, [100] * 5, texts=["Matcha latte cafe review"] * 5
        ),
        "technical_guruji": _mock_creator_payload(
            1000, [100] * 5, texts=["Smartphone unboxing benchmark"] * 5
        ),
    }
    board = affinity.score_all(creator_list=creators, payloads=payloads)

    # deterministic ordering: creators sorted by slug
    assert [c["slug"] for c in board["creators"]] == ["cafe_x", "technical_guruji"]

    matcha = {c["slug"]: c["per_trend"]["matcha"] for c in board["creators"]}
    assert matcha["cafe_x"]["rank"] == 1
    assert matcha["technical_guruji"]["score"] == 0.0  # zero topic overlap
    assert matcha["technical_guruji"]["rank"] == 2

    for c in board["creators"]:
        for trend_result in c["per_trend"].values():
            assert trend_result["score"] == round(trend_result["score"], 4)


def test_score_all_covers_every_demo_trend_and_only_demo_trends():
    creators = _creators([("cafe_x", "tea_cafe", False)])
    payloads = {"cafe_x": _mock_creator_payload(1000, [10], texts=["matcha"])}
    board = affinity.score_all(creator_list=creators, payloads=payloads)
    per_trend = board["creators"][0]["per_trend"]
    assert set(per_trend) == set(taxonomy.TREND_TOPIC_MIX)
    assert "korean_skincare" not in per_trend  # calibration trend never scored here


# ---------------------------------------------------------------------------
# affinity_board.json provenance: contains_fixture_data must be true while
# creator data is fixture-derived (BRIEF §0.3), whether checked via
# score_all() directly or via the full main() CLI path.
# ---------------------------------------------------------------------------


def test_score_all_provenance_true_when_any_creator_is_fixture():
    creators = _creators([("cafe_x", "tea_cafe", False), ("cafe_y", "tea_cafe", False)])
    payloads = {
        "cafe_x": _mock_creator_payload(1000, [10], prov=provenance.REAL),
        "cafe_y": _mock_creator_payload(1000, [10], prov=provenance.FIXTURE),
    }
    board = affinity.score_all(creator_list=creators, payloads=payloads)
    assert board["provenance"]["contains_fixture_data"] is True
    assert board["provenance"]["sources"] == {"creator_data": provenance.FIXTURE}


def test_score_all_provenance_false_when_every_creator_is_real():
    creators = _creators([("cafe_x", "tea_cafe", False)])
    payloads = {"cafe_x": _mock_creator_payload(1000, [10], prov=provenance.REAL)}
    board = affinity.score_all(creator_list=creators, payloads=payloads)
    assert board["provenance"]["contains_fixture_data"] is False
    assert board["provenance"]["sources"] == {"creator_data": provenance.REAL}


def test_main_writes_affinity_board_with_fixture_provenance_flag(tmp_path, monkeypatch):
    """Full CLI path (affinity.main -> runlog.run -> board written to
    disk), entirely redirected into tmp_path: no real repo file is read or
    written. Proves the fixture banner condition end-to-end, not just at
    the score_all() unit level."""
    creators = _creators([("cafe_x", "tea_cafe", False)])
    monkeypatch.setattr(creators_mod, "STARTER_CREATORS", tuple(creators))

    payload = _mock_creator_payload(1000, [10] * 5, texts=["matcha latte cafe"] * 5)
    # No "_source_path" key -> main() has nothing to add_input(); this
    # keeps the test independent of creators.REPO_ROOT/FIXTURES_DIR wiring.
    monkeypatch.setattr(creators_mod, "load_creator", lambda slug: dict(payload))

    output_path = tmp_path / "affinity_board.json"
    monkeypatch.setattr(affinity, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(affinity, "REPO_ROOT", tmp_path)  # for the final relative_to() print

    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(runlog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runlog, "RUNS_DIR", runs_dir)

    exit_code = affinity.main()

    assert exit_code == 0
    board = json.loads(output_path.read_text())
    assert board["provenance"]["contains_fixture_data"] is True
    assert board["provenance"]["sources"] == {"creator_data": provenance.FIXTURE}
    assert board["creators"][0]["slug"] == "cafe_x"
    assert "method_note" in board and isinstance(board["method_note"], str)

    run_dirs = list(runs_dir.iterdir())
    assert len(run_dirs) == 1
    record = json.loads((run_dirs[0] / "run.json").read_text())
    assert record["command"] == "affinity"
    assert record["status"] == "ok"


# ---------------------------------------------------------------------------
# creators.load_creator: directory/provenance discipline (mirrors
# pipeline/ingest/base.py's load() consistency checks for trend pulls)
# ---------------------------------------------------------------------------


def test_load_creator_unknown_slug_raises():
    with pytest.raises(creators_mod.CreatorDataError, match="unknown creator slug"):
        creators_mod.load_creator("not_a_real_slug")


def test_load_creator_missing_data_raises(tmp_path, monkeypatch):
    raw_dir, fixtures_dir = tmp_path / "raw", tmp_path / "fixtures"
    raw_dir.mkdir()
    fixtures_dir.mkdir()
    monkeypatch.setattr(creators_mod, "RAW_DIR", raw_dir)
    monkeypatch.setattr(creators_mod, "FIXTURES_DIR", fixtures_dir)
    with pytest.raises(creators_mod.CreatorDataError, match="no real pull or MOCK_ fixture"):
        creators_mod.load_creator("fit_tuber")


def test_load_creator_prefers_real_pull_over_fixture(tmp_path, monkeypatch):
    raw_dir, fixtures_dir = tmp_path / "raw", tmp_path / "fixtures"
    raw_dir.mkdir()
    fixtures_dir.mkdir()
    monkeypatch.setattr(creators_mod, "RAW_DIR", raw_dir)
    monkeypatch.setattr(creators_mod, "FIXTURES_DIR", fixtures_dir)
    monkeypatch.setattr(creators_mod, "REPO_ROOT", tmp_path)

    fixture_payload = _mock_creator_payload(1000, [10])
    (fixtures_dir / "MOCK_youtube_creator_fit_tuber_20260101.json").write_text(
        json.dumps(fixture_payload)
    )
    real_payload = dict(fixture_payload)
    real_payload["provenance"] = provenance.REAL
    real_payload["channel_title"] = "REAL Fit Tuber Pull"
    (raw_dir / "youtube_creator_fit_tuber_20260102.json").write_text(
        json.dumps(real_payload)
    )

    loaded = creators_mod.load_creator("fit_tuber")
    assert loaded["provenance"] == provenance.REAL
    assert loaded["channel_title"] == "REAL Fit Tuber Pull"


def test_load_creator_rejects_provenance_mismatch_in_raw_dir(tmp_path, monkeypatch):
    raw_dir, fixtures_dir = tmp_path / "raw", tmp_path / "fixtures"
    raw_dir.mkdir()
    fixtures_dir.mkdir()
    monkeypatch.setattr(creators_mod, "RAW_DIR", raw_dir)
    monkeypatch.setattr(creators_mod, "FIXTURES_DIR", fixtures_dir)
    monkeypatch.setattr(creators_mod, "REPO_ROOT", tmp_path)

    bad_payload = _mock_creator_payload(1000, [10])  # provenance="fixture"
    (raw_dir / "youtube_creator_fit_tuber_20260101.json").write_text(
        json.dumps(bad_payload)
    )

    with pytest.raises(creators_mod.CreatorDataError, match="file lives in data/raw"):
        creators_mod.load_creator("fit_tuber")


# ---------------------------------------------------------------------------
# creators.fetch_creator: documented stub, MissingCredentials contract
# ---------------------------------------------------------------------------


def test_fetch_creator_unknown_slug_raises():
    with pytest.raises(creators_mod.CreatorDataError, match="unknown creator slug"):
        creators_mod.fetch_creator("not_a_real_slug")


def test_fetch_creator_missing_credentials_when_env_absent(monkeypatch):
    monkeypatch.setattr(yt_ingest, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(ingest_base.MissingCredentials):
        creators_mod.fetch_creator("fit_tuber")
