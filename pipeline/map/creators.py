"""Creator metadata + per-creator data loading for the Map slice (BRIEF §5.5).

Starter list (~12 per the brief, extended to 14 to cover all ten taxonomy
topics plus two deliberate mismatch controls — PROTOCOL A3): wellness/food
creators, fashion/café-aesthetic lifestyle creators, fitness creators, and
two tech/gadget creators kept in on purpose as controls whose content should
NOT resemble any of the demo trends. `is_control=True` marks those two;
`niche` is an informal tag (not necessarily a taxonomy.TOPICS name) used
only for the human-readable board and for picking out "the fitness-niche
creators" in affinity.py's PROTOCOL A3 validation checks.

Creator file schema (produced by scripts/make_creator_fixtures.py; a real
per-creator pull would emit the same shape with provenance="real"):

    {
      "channel_id": str,
      "channel_title": str,
      "subscribers": int,
      "retrieved_at": "<ISO-8601 with offset>",
      "provenance": "fixture" | "real",
      "videos": [
        {"video_id": str, "published_at": "<ISO-8601>", "title": str,
         "description": str, "view_count": int},
        ...  (~50)
      ]
    }

This is intentionally NOT pipeline/ingest/base.py's Pull envelope: base.py's
`Pull.validate()` requires `trend` to be a key of trends_config.TRENDS, and
creators are keyed by YouTube channel/slug, not by trend basket — forcing
creator pulls through that envelope would mean either lying about a `trend`
or weakening base.py's validation, and this task owns neither base.py nor
trends_config.py. Directory placement still mirrors base.py's convention on
purpose (real in data/raw/, MOCK_-prefixed fixtures in data/fixtures/), and
load_creator() enforces it the same way base.load() does for trend pulls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipeline import provenance

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"


class CreatorDataError(ValueError):
    """Unknown creator slug, or a creator file with the wrong provenance
    for the directory it was found in."""


@dataclass(frozen=True)
class Creator:
    slug: str
    name: str
    niche: str
    is_control: bool = False


# BRIEF §5.5 starter list. Real YouTube identities (subscriber counts are
# plausible fixed magnitudes, documented per creator below); the VIDEO
# CONTENT behind each of these, until a real per-creator pull exists, comes
# from scripts/make_creator_fixtures.py and carries fixture provenance —
# never presented as this channel's real recent uploads.
STARTER_CREATORS: tuple[Creator, ...] = (
    # Wellness/food creators (BRIEF §5.5 examples), fitness niche.
    Creator("fit_tuber", "Fit Tuber", "protein_fitness"),               # ~11M subs
    Creator("bake_with_shivesh", "Bake with Shivesh", "cooking_baking"),  # ~2.8M subs
    Creator("your_food_lab", "Your Food Lab", "cooking_baking"),         # ~6.5M subs
    # Lifestyle / café-aesthetic creators (BRIEF §5.5 examples).
    Creator("kritika_khurana", "Kritika Khurana", "fashion_lifestyle"),  # ~2.6M subs
    Creator("komal_pandey", "Komal Pandey", "fashion_lifestyle"),        # ~1.8M subs
    # Deliberate mismatch controls (PROTOCOL A3(b)): tech/gadgets content,
    # expected to score LOW on every demo trend's topic mix.
    Creator("technical_guruji", "Technical Guruji", "tech_gadgets", is_control=True),  # ~23M subs
    Creator("geeky_ranjit", "Geeky Ranjit", "tech_gadgets", is_control=True),          # ~5.2M subs
    # Second fitness/nutrition creator (BRIEF §5.5's "fitness" slot,
    # PROTOCOL A3(a) needs at least one clear fitness-niche comparison set).
    Creator("fitness_by_rahul", "Fitness by Rahul", "protein_fitness"),  # ~0.85M subs
    # Remaining niches, to give every taxonomy.TOPICS entry at least one
    # creator whose content should genuinely score there.
    Creator("yoga_with_anjali", "Yoga With Anjali", "wellness_yoga"),          # ~0.62M subs
    Creator("cafe_hopper_diaries", "Cafe Hopper Diaries", "tea_cafe"),         # ~0.51M subs
    Creator("glow_with_neha", "Glow With Neha", "skincare_beauty"),            # ~1.4M subs
    Creator("wanderlust_with_kabir", "Wanderlust with Kabir", "travel"),       # ~3.1M subs
    Creator("desi_binge_reacts", "Desi Binge Reacts", "entertainment"),        # ~4.7M subs
    Creator("urban_desi_vlogs", "Urban Desi Vlogs", "fashion_lifestyle"),      # ~0.95M subs
)

CREATORS_BY_SLUG: dict[str, Creator] = {c.slug: c for c in STARTER_CREATORS}


def _newest(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[-1] if matches else None


def load_creator(slug: str) -> dict:
    """Load the newest real pull for `slug` (data/raw/youtube_creator_
    {slug}_*.json) if present, else its newest MOCK_ fixture
    (data/fixtures/MOCK_youtube_creator_{slug}_*.json). Raises
    CreatorDataError if neither exists, the slug is unknown, or a file's
    provenance field disagrees with the directory it was found in (the same
    consistency base.load() enforces for trend pulls).

    Returns the parsed dict plus a non-schema `_source_path` key (repo-
    relative) for callers that want to log what they read; downstream
    consumers must key off `provenance`, never off which directory a file
    happened to come from.
    """
    if slug not in CREATORS_BY_SLUG:
        raise CreatorDataError(
            f"unknown creator slug: {slug!r}; known: {sorted(CREATORS_BY_SLUG)}"
        )

    real_path = _newest(RAW_DIR, f"youtube_creator_{slug}_*.json")
    if real_path is not None:
        payload = json.loads(real_path.read_text())
        if payload.get("provenance") != provenance.REAL:
            raise CreatorDataError(
                f"{real_path}: file lives in data/raw/ but provenance is "
                f"{payload.get('provenance')!r}, not {provenance.REAL!r}"
            )
        payload["_source_path"] = str(real_path.relative_to(REPO_ROOT))
        return payload

    fixture_path = _newest(FIXTURES_DIR, f"MOCK_youtube_creator_{slug}_*.json")
    if fixture_path is None:
        raise CreatorDataError(
            f"no real pull or MOCK_ fixture found for creator {slug!r}; run "
            "scripts/make_creator_fixtures.py or a real per-creator YouTube "
            "pull first"
        )
    payload = json.loads(fixture_path.read_text())
    if payload.get("provenance") != provenance.FIXTURE:
        raise CreatorDataError(
            f"{fixture_path}: file lives in data/fixtures/ but provenance is "
            f"{payload.get('provenance')!r}, not {provenance.FIXTURE!r}"
        )
    payload["_source_path"] = str(fixture_path.relative_to(REPO_ROOT))
    return payload


def fetch_creator(slug: str) -> dict:
    """Real per-creator YouTube pull — documented stub (BRIEF §2: keys
    arrive late, never block on them).

    Reuses pipeline/ingest/youtube.py's credential contract via its
    `_api_key()` / `build("youtube", "v3", ...)` client helper, so a missing
    YOUTUBE_API_KEY fails exactly the same way the trend-ingest path does:
    `base.MissingCredentials`. When a key IS present, a real implementation
    would still need to: resolve `slug` to a channel id (search.list,
    type=channel), list its most recent ~50 uploads (search.list,
    type=video, order=date), and hydrate them (videos.list) — the same
    two-step shape pipeline/ingest/youtube.py already implements for trend
    baskets. That part is deliberately left unbuilt here: no key exists yet
    to build or test it against (this slice is built and run against
    scripts/make_creator_fixtures.py fixtures instead, per BRIEF §2), and
    load_creator() already falls back to those fixtures. Filling this in is
    a follow-up once real credentials land, not a Map-slice blocker.
    """
    if slug not in CREATORS_BY_SLUG:
        raise CreatorDataError(
            f"unknown creator slug: {slug!r}; known: {sorted(CREATORS_BY_SLUG)}"
        )
    from googleapiclient.discovery import build

    from pipeline.ingest.youtube import _api_key

    key = _api_key()  # raises base.MissingCredentials if YOUTUBE_API_KEY absent
    build("youtube", "v3", developerKey=key)  # proves the client helper wires up
    raise NotImplementedError(
        f"fetch_creator({slug!r}): YOUTUBE_API_KEY is present but the real "
        "per-creator pull is not implemented yet (documented stub — see "
        "docstring). Use load_creator(), which falls back to the MOCK_ "
        "fixture, until this is filled in."
    )
