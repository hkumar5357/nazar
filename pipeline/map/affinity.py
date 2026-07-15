"""Creator-trend affinity scoring (Map slice, BRIEF §5.5, PROTOCOL A3).

affinity_raw(creator, trend) = cosine(creator_topic_vector, trend_topic_mix)
                                * engagement_factor(creator)

- creator_topic_vector: taxonomy.vectorize() over the creator's ~50 recent
  video titles+descriptions (pipeline/map/taxonomy.py, keyword taxonomy —
  method documented there).
- trend_topic_mix: taxonomy.TREND_TOPIC_MIX, a fixed pre-scoring prior
  (BRIEF §5.5), expanded to the full topic vector by taxonomy.mix_vector().
- engagement_factor: median(view_count)/subscribers, normalized against the
  cross-creator median of that same ratio and clamped to
  [ENGAGEMENT_MIN, ENGAGEMENT_MAX]. Why clamp: engagement quality is meant
  to TILT affinity, never dominate it. A creator sitting at 10x the median
  views/subscriber ratio should nudge their rank up, not multiply their
  topic-match score by 10x and swamp it; symmetrically, a dormant channel or
  an inflated subscriber count is floored so it can only ever roughly halve
  the score, never zero it out. 0.25/2.0 are a documented editorial choice,
  not a fitted statistic — there is no ground truth to fit against here.

Ranks are the primary signal (BRIEF §5.5: "presented as relative ranks, not
fake precision"); the numeric score is exposed too, rounded to 4 decimals,
but is explicitly a RELATIVE quantity — meaningful only for ordering
creators within one trend's column, not comparable across trends (the two
trend mixes are different vectors) and not a probability or percentage.

R5 (LLM boundary) is not implicated: nothing here is an LLM, and nothing
here feeds pipeline/lifecycle.py or pipeline/backtest.py. This module only
ever produces creator ranks for the Map screen.

CLI: `python -m pipeline.map.affinity`, wrapped in pipeline.runlog.run
(PROTOCOL R4).
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from pipeline import provenance, runlog
from pipeline.map import creators as creators_mod
from pipeline.map.taxonomy import TREND_TOPIC_MIX, cosine, mix_vector, vectorize

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = REPO_ROOT / "data" / "map" / "affinity_board.json"

# Engagement-factor clamp band (documented above); see normalize_engagement.
ENGAGEMENT_MIN = 0.25
ENGAGEMENT_MAX = 2.0

# PROTOCOL A3 validation-pair parameters.
FITNESS_NICHE = "protein_fitness"
TECH_CONTROL_SLUG = "technical_guruji"
VALIDATION_TOP_N = 3
VALIDATION_BOTTOM_N = 3


def creator_topic_vector(payload: dict) -> dict[str, float]:
    """taxonomy.vectorize() over one creator's title+description text."""
    texts = [
        f"{v.get('title', '')} {v.get('description', '')}"
        for v in payload.get("videos", [])
    ]
    return vectorize(texts)


def creator_engagement_raw(payload: dict) -> float:
    """median(view_count) / subscribers — the raw ratio, before
    cross-creator normalization (normalize_engagement owns that step).
    0.0 for a creator with no videos or non-positive subscribers (never a
    ZeroDivisionError; a rank-worst-case value, not a crash)."""
    views = [int(v["view_count"]) for v in payload.get("videos", [])]
    subs = int(payload.get("subscribers", 0))
    if not views or subs <= 0:
        return 0.0
    return statistics.median(views) / subs


def normalize_engagement(raw_by_slug: dict[str, float]) -> dict[str, float]:
    """Cross-creator median-normalize each raw engagement ratio, then clamp
    to [ENGAGEMENT_MIN, ENGAGEMENT_MAX] (rationale in the module docstring).
    The pivot is the median of the strictly-positive raw ratios; if every
    creator's raw ratio is 0 (degenerate input), the pivot falls back to 1.0
    so every creator lands at the clamp floor rather than dividing by zero.
    """
    positive = [v for v in raw_by_slug.values() if v > 0]
    pivot = statistics.median(positive) if positive else 1.0
    return {
        slug: min(ENGAGEMENT_MAX, max(ENGAGEMENT_MIN, raw / pivot))
        for slug, raw in raw_by_slug.items()
    }


def rank_trend(scores: dict[str, float]) -> dict[str, int]:
    """1 = best (highest score). Deterministic tie-break: ties broken by
    slug ascending, so re-running with identical inputs always reproduces
    the identical rank assignment."""
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return {slug: i + 1 for i, (slug, _score) in enumerate(ordered)}


def run_validation(
    ranks_by_trend: dict[str, dict[str, int]],
    creator_list,
) -> list[dict]:
    """PROTOCOL A3 (amended C4): two pass/fail checks against `ranks_by_trend`.

    (a) the best-ranked fitness-niche (FITNESS_NICHE) creator must rank in
        the top VALIDATION_TOP_N for protein_snacks.
    (b) the tech control (TECH_CONTROL_SLUG) must rank in the bottom
        VALIDATION_BOTTOM_N for matcha.

    Pure function of its arguments (no disk I/O) so tests can engineer
    synthetic creator lists + rank maps to exercise both the pass and the
    fail path deterministically.
    """
    n_creators = len(creator_list)
    checks: list[dict] = []

    fitness_slugs = [c.slug for c in creator_list if c.niche == FITNESS_NICHE]
    if fitness_slugs and "protein_snacks" in ranks_by_trend:
        protein_ranks = ranks_by_trend["protein_snacks"]
        best_slug = min(fitness_slugs, key=lambda s: protein_ranks[s])
        best_rank = protein_ranks[best_slug]
        checks.append(
            {
                "check": (
                    f"top {FITNESS_NICHE}-niche creator ranks top "
                    f"{VALIDATION_TOP_N} for protein_snacks"
                ),
                "expected": f"rank <= {VALIDATION_TOP_N}",
                "actual": f"{best_slug} rank {best_rank}",
                "pass": best_rank <= VALIDATION_TOP_N,
            }
        )

    if "matcha" in ranks_by_trend and TECH_CONTROL_SLUG in ranks_by_trend["matcha"]:
        matcha_ranks = ranks_by_trend["matcha"]
        tech_rank = matcha_ranks[TECH_CONTROL_SLUG]
        bottom_floor = n_creators - VALIDATION_BOTTOM_N + 1
        checks.append(
            {
                "check": (
                    f"tech-control creator ({TECH_CONTROL_SLUG}) ranks bottom "
                    f"{VALIDATION_BOTTOM_N} for matcha"
                ),
                "expected": f"rank >= {bottom_floor} (of {n_creators})",
                "actual": f"{TECH_CONTROL_SLUG} rank {tech_rank}",
                "pass": tech_rank >= bottom_floor,
            }
        )

    return checks


METHOD_NOTE = (
    "Affinity = cosine(creator topic vector, trend topic mix) x engagement "
    "factor. Topic vectors come from a fixed 10-topic keyword taxonomy over "
    "each creator's ~50 most recent video titles+descriptions (see "
    "pipeline/map/taxonomy.py for the method choice vs embeddings). Trend "
    "topic mixes (pipeline.map.taxonomy.TREND_TOPIC_MIX) are fixed, "
    "seed-weighted priors set BEFORE scoring, not fit to creator data. "
    "Engagement factor = median(view_count)/subscribers, normalized to the "
    "cross-creator median and clamped to "
    f"[{ENGAGEMENT_MIN}, {ENGAGEMENT_MAX}] so engagement quality tilts "
    "affinity without dominating the topic match. RANK is the primary "
    "signal (1 = best fit within that trend's column). The numeric `score` "
    "is rounded to 4 decimals but is explicitly RELATIVE: meaningful only "
    "for ordering creators within one trend, not comparable across trends "
    "and not a probability. Nothing here is an LLM (PROTOCOL R5 n/a) and "
    "nothing here feeds the lifecycle/backtest state machine."
)


def score_all(
    creator_list=None,
    payloads: dict[str, dict] | None = None,
) -> dict:
    """Score every creator in `creator_list` (default: STARTER_CREATORS)
    against every trend in taxonomy.TREND_TOPIC_MIX. Returns the full
    affinity_board.json payload.

    `payloads`, if given, maps slug -> creator file dict and is used instead
    of creators_mod.load_creator() — this is what lets tests exercise
    scoring end-to-end on synthetic in-memory creators with no disk I/O.
    """
    creator_list = list(creator_list) if creator_list is not None else list(
        creators_mod.STARTER_CREATORS
    )
    if payloads is None:
        payloads = {c.slug: creators_mod.load_creator(c.slug) for c in creator_list}

    topic_vectors = {c.slug: creator_topic_vector(payloads[c.slug]) for c in creator_list}
    engagement_raw = {
        c.slug: creator_engagement_raw(payloads[c.slug]) for c in creator_list
    }
    engagement_factor = normalize_engagement(engagement_raw)

    trend_scores: dict[str, dict[str, float]] = {}
    for trend, mix in TREND_TOPIC_MIX.items():
        trend_vec = mix_vector(mix)
        trend_scores[trend] = {
            c.slug: round(
                cosine(topic_vectors[c.slug], trend_vec) * engagement_factor[c.slug],
                4,
            )
            for c in creator_list
        }

    ranks_by_trend = {
        trend: rank_trend(scores) for trend, scores in trend_scores.items()
    }

    trend_order = sorted(TREND_TOPIC_MIX)
    creator_records = []
    for c in sorted(creator_list, key=lambda c: c.slug):
        per_trend = {
            trend: {
                "rank": ranks_by_trend[trend][c.slug],
                "score": trend_scores[trend][c.slug],
            }
            for trend in trend_order
        }
        creator_records.append(
            {
                "slug": c.slug,
                "name": c.name,
                "niche": c.niche,
                "is_control": c.is_control,
                "subscribers": int(payloads[c.slug].get("subscribers", 0)),
                "engagement_factor": round(engagement_factor[c.slug], 6),
                "per_trend": per_trend,
            }
        )

    validation = run_validation(ranks_by_trend, creator_list)

    creator_kinds = {
        c.slug: payloads[c.slug].get("provenance", provenance.FIXTURE)
        for c in creator_list
    }
    overall_kind = (
        provenance.FIXTURE
        if any(k in provenance.FIXTURE_KINDS for k in creator_kinds.values())
        else provenance.REAL
    )

    return {
        "creators": creator_records,
        "validation": validation,
        "method_note": METHOD_NOTE,
        "provenance": provenance.summarize({"creator_data": overall_kind}),
    }


def main() -> int:
    creator_list = list(creators_mod.STARTER_CREATORS)
    with runlog.run("affinity", notes="Map slice: creator-trend affinity scoring") as ctx:
        payloads = {c.slug: creators_mod.load_creator(c.slug) for c in creator_list}
        for c in creator_list:
            source = payloads[c.slug].get("_source_path")
            if source:
                ctx.add_input(REPO_ROOT / source)

        board = score_all(creator_list=creator_list, payloads=payloads)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(board, indent=2, ensure_ascii=False) + "\n"
        )
        ctx.add_output(OUTPUT_PATH)
        ctx.set("n_creators", len(board["creators"]))
        ctx.set("validation", board["validation"])
        ctx.set(
            "contains_fixture_data",
            board["provenance"]["contains_fixture_data"],
        )

    for check in board["validation"]:
        status = "PASS" if check["pass"] else "FAIL"
        print(f"[affinity] {status}: {check['check']} -> {check['actual']}")
    print(f"[affinity] wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
