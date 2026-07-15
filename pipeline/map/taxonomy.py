"""Keyword taxonomy for creator/trend topic vectors (Map slice, BRIEF §5.5).

Method choice (BRIEF §5.5 explicitly asks to pick embeddings OR a keyword
taxonomy and document it): a fixed keyword taxonomy over ~10 lifestyle /
content topics, not embeddings. Reasons:

1. No model call, no API key, no network — the whole Map slice stays
   reproducible offline from committed fixtures/pulls alone, matching the
   PROTOCOL R1/R4 discipline the rest of the pipeline already holds itself
   to (embeddings would need a provider call this repo has no budget or
   deadline slack to add and re-freeze against).
2. Every score is explainable by inspecting which keywords fired, which
   matters more than marginal ranking accuracy for a founder-grade review
   artifact — "why did this creator rank here" has a one-line answer.
3. It is a deliberately coarse instrument: keyword hit-counting cannot
   disambiguate polysemy (the same "match" vs "matcha" contamination
   scripts/make_fixtures.py documents for the intent labeler applies here
   too). That limitation is accepted and stated, not hidden.

R5 is not implicated either way: nothing here is an LLM. This is a pure,
deterministic keyword count — vectorize() takes text in and returns numbers
out, with no model in between.
"""

from __future__ import annotations

import math

# Fixed topic order — every topic vector in this module (creator or trend)
# is a dict keyed by these ten names; TOPICS also fixes iteration order for
# anything that needs a stable ordering (e.g. building a dense array).
TOPICS: tuple[str, ...] = (
    "tea_cafe",
    "protein_fitness",
    "fragrance_grooming",
    "skincare_beauty",
    "cooking_baking",
    "fashion_lifestyle",
    "tech_gadgets",
    "travel",
    "wellness_yoga",
    "entertainment",
)

# Keyword banks, one per topic. Deliberately short phrases (single words or
# short bigrams) matched as lowercased substrings — see _hit_count. Kept
# largely disjoint across topics on purpose so a creator's vector reflects
# genuine topical mix rather than incidental collisions; a little overlap
# (e.g. "camera review" touching tech and no other topic) is fine.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "tea_cafe": (
        "matcha", "tea", "chai", "latte", "cafe", "coffee", "barista",
        "cappuccino", "espresso", "brew", "green tea", "iced tea",
    ),
    "protein_fitness": (
        "protein", "gym", "workout", "fitness", "muscle", "nutrition",
        "macros", "whey", "cardio", "hiit", "bodybuilding", "calisthenics",
    ),
    "fragrance_grooming": (
        "perfume", "fragrance", "attar", "cologne", "scent", "grooming",
        "deodorant", "aftershave", "eau de parfum", "fragrance notes",
    ),
    "skincare_beauty": (
        "skincare", "skin routine", "serum", "moisturiser", "moisturizer",
        "sunscreen", "glass skin", "makeup", "beauty", "glow", "mucin",
    ),
    "cooking_baking": (
        "recipe", "cooking", "baking", "bake", "kitchen", "ingredients",
        "dessert", "cake", "bread", "chef",
    ),
    "fashion_lifestyle": (
        "fashion", "outfit", "style", "ootd", "lifestyle", "wardrobe",
        "shopping haul", "aesthetic", "streetwear", "closet",
    ),
    "tech_gadgets": (
        "phone", "smartphone", "gadget", "unboxing", "specs", "processor",
        "benchmark", "laptop", "chipset", "camera review",
    ),
    "travel": (
        "travel", "trip", "vacation", "itinerary", "backpacking", "flight",
        "hotel", "tourism", "destination", "roadtrip",
    ),
    "wellness_yoga": (
        "yoga", "wellness", "meditation", "mindfulness", "self care",
        "breathwork", "asana", "mental health", "stretching",
    ),
    "entertainment": (
        "movie", "trailer", "celebrity", "bollywood", "web series",
        "comedy sketch", "reaction video", "gossip", "song review",
    ),
}

assert set(KEYWORDS) == set(TOPICS), "KEYWORDS must define exactly TOPICS"


def _hit_count(lowered_text: str, keywords: tuple[str, ...]) -> int:
    """Total keyword occurrences (not just presence) of `keywords` inside
    one already-lowercased text, via substring counting."""
    return sum(lowered_text.count(kw) for kw in keywords)


def vectorize(texts: list[str]) -> dict[str, float]:
    """Keyword-hit counts over lowercased `texts`, summed across all texts
    per topic, then L2-normalized across the 10 topics.

    A text (or the whole `texts` list) with zero hits in every topic stays
    the all-zero vector rather than raising or dividing by zero — cosine()
    below treats an all-zero vector as "no signal", which is the honest
    reading of a creator/trend with no keyword overlap at all.
    """
    lowered = [t.lower() for t in texts]
    raw = {topic: 0.0 for topic in TOPICS}
    for text in lowered:
        for topic, keywords in KEYWORDS.items():
            raw[topic] += _hit_count(text, keywords)
    norm = math.sqrt(sum(v * v for v in raw.values()))
    if norm == 0.0:
        return raw
    return {topic: v / norm for topic, v in raw.items()}


def mix_vector(mix: dict[str, float]) -> dict[str, float]:
    """Expand a sparse {topic: weight} trend mix (see TREND_TOPIC_MIX) to
    the full TOPICS-ordered vector, zero-filling topics the mix does not
    mention. Mixes are authored to already sum to ~1.0 and are not
    re-normalized here (they are priors, not measurements)."""
    unknown = set(mix) - set(TOPICS)
    if unknown:
        raise ValueError(f"unknown topic(s) in trend mix: {sorted(unknown)}")
    return {topic: float(mix.get(topic, 0.0)) for topic in TOPICS}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two topic vectors keyed (at least partly)
    by TOPICS; missing keys read as 0.0. Either vector being all-zero
    yields 0.0 (no signal, not a divide-by-zero error)."""
    dot = sum(a.get(t, 0.0) * b.get(t, 0.0) for t in TOPICS)
    norm_a = math.sqrt(sum(a.get(t, 0.0) ** 2 for t in TOPICS))
    norm_b = math.sqrt(sum(b.get(t, 0.0) ** 2 for t in TOPICS))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Trend topic mixes (BRIEF §5.5): seed-weighted priors, fixed BEFORE any
# creator is scored against them — an editorial judgment call about which
# taxonomy topics compose each demo trend, not something fit to the creator
# data. Only the three demo trends need a mix; the calibration trend
# (korean_skincare) never appears in the Map slice (PROTOCOL R3/A3).
# ---------------------------------------------------------------------------

TREND_TOPIC_MIX: dict[str, dict[str, float]] = {
    "matcha": {
        "tea_cafe": 0.6,
        "cooking_baking": 0.2,
        "wellness_yoga": 0.2,
    },
    "protein_snacks": {
        "protein_fitness": 0.7,
        "wellness_yoga": 0.2,
        "cooking_baking": 0.1,
    },
    "genz_fragrance": {
        "fragrance_grooming": 0.8,
        "fashion_lifestyle": 0.2,
    },
}

for _mix in TREND_TOPIC_MIX.values():
    assert set(_mix) <= set(TOPICS), "trend mix references an unknown topic"
    assert abs(sum(_mix.values()) - 1.0) < 1e-9, "trend mix must sum to 1.0"
del _mix
