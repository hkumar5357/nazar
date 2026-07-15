"""Generate MOCK_ development fixtures for the Map slice's per-creator YouTube data.

Why a SEPARATE generator (not scripts/make_fixtures.py): that script owns
the trend-basket pulls (reddit/youtube keyed by trend, via
pipeline/ingest/base.py's envelope) for a different builder's slice.
Creator fixtures are keyed by YouTube channel, not by trend, and use a
deliberately different file schema (documented in
pipeline/map/creators.py) — so this is its own script, its own seed, its
own retrieved_at, and it never touches scripts/make_fixtures.py or the 8
MOCK_ files that script already produced.

Protocol constraints honoured here:

- No-fake-data rule (BRIEF §0.3): every file is MOCK_-prefixed, lives only
  in data/fixtures/, and carries provenance "fixture". The creator IDENTITY
  (slug/name/niche — pipeline/map/creators.py's STARTER_CREATORS) is real:
  these are the actual public creators BRIEF §5.5 names for the affinity
  board. The per-video CONTENT is not real: titles/descriptions are drawn
  from per-creator phrase banks below, never scraped or copied from an
  actual upload, video_id and channel_id are synthetic MOCK_-prefixed
  placeholders (never a real 11-char YouTube id), and the file-level
  `provenance` field is "fixture" — so nothing here can be mistaken for a
  genuine API response for that channel. Every file round-trips through
  pipeline.map.creators.load_creator() before this script declares success,
  the same discipline scripts/make_fixtures.py applies via
  pipeline/ingest/base.py's loader.
- R1 (point-in-time): every video's published_at falls strictly before the
  file's retrieved_at. Asserted below.
- R4 (run logging): generation is wrapped in pipeline.runlog.run(), so each
  execution is recorded in runs/ with output hashes.
- R5 is untouched: no LLM anywhere; titles/descriptions come from fixed
  phrase banks, later scored only by taxonomy.py's plain keyword counting.

Determinism: a single random.Random(SEED) instance (never the global RNG),
consumed in a fixed creator/video loop order, with retrieved_at hardcoded —
re-running this script reproduces every file byte-for-byte. SEED and
RETRIEVED_AT are deliberately different from scripts/make_fixtures.py's
(different day, different time) so the two generators can never collide.

Usage (from the repo root):

    venv/bin/python scripts/make_creator_fixtures.py
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # allow `python scripts/make_creator_fixtures.py`

from pipeline import provenance  # noqa: E402
from pipeline.map import creators as creators_mod  # noqa: E402
from pipeline.runlog import run  # noqa: E402

SEED = 20260713
RETRIEVED_AT = "2026-07-13T21:30:00+05:30"
N_VIDEOS = 50
MAX_FILE_BYTES = 400_000

# Fixed, documented subscriber magnitudes (BRIEF §5.5: "plausible
# magnitudes, e.g. Technical Guruji 23M, Fit Tuber 11M, others 0.5-8M").
# Lives here, not on creators.Creator (which only carries identity/niche
# fields) — subscriber count is per-PULL data, and this is the only pull
# that currently exists.
SUBSCRIBERS: dict[str, int] = {
    "fit_tuber": 11_000_000,
    "bake_with_shivesh": 2_800_000,
    "your_food_lab": 6_500_000,
    "kritika_khurana": 2_600_000,
    "komal_pandey": 1_800_000,
    "technical_guruji": 23_000_000,
    "geeky_ranjit": 5_200_000,
    "fitness_by_rahul": 850_000,
    "yoga_with_anjali": 620_000,
    "cafe_hopper_diaries": 510_000,
    "glow_with_neha": 1_400_000,
    "wanderlust_with_kabir": 3_100_000,
    "desi_binge_reacts": 4_700_000,
    "urban_desi_vlogs": 950_000,
}

assert set(SUBSCRIBERS) == set(creators_mod.CREATORS_BY_SLUG), (
    "SUBSCRIBERS must document exactly the STARTER_CREATORS slugs"
)

# "Typical single-video views, for a channel this size" anchor (BRIEF §5.5:
# "view counts lognormal-ish seeded"), expressed as a fraction of
# subscribers so it scales sensibly across a ~45x subscriber range, times a
# per-creator engagement tilt (>1 = punches above its subscriber count,
# <1 = below). This is what gives pipeline/map/affinity.py's engagement
# factor real cross-creator variation to normalize/clamp against, instead
# of a flat ratio for every creator.
BASE_VIEW_RATIO = 0.05  # "typical" video ~5% of subscriber count, before tilt/noise
LOGNORMAL_SIGMA = 0.5  # per-video noise around each creator's median

ENGAGEMENT_TILT: dict[str, float] = {
    "fit_tuber": 1.15,
    "bake_with_shivesh": 0.90,
    "your_food_lab": 1.05,
    "kritika_khurana": 0.85,
    "komal_pandey": 0.80,
    "technical_guruji": 1.30,
    "geeky_ranjit": 1.00,
    "fitness_by_rahul": 1.10,
    "yoga_with_anjali": 0.75,
    "cafe_hopper_diaries": 0.95,
    "glow_with_neha": 0.90,
    "wanderlust_with_kabir": 1.00,
    "desi_binge_reacts": 1.20,
    "urban_desi_vlogs": 0.70,
}

assert set(ENGAGEMENT_TILT) == set(SUBSCRIBERS)

CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Pune", "Hyderabad", "Chennai",
    "Kolkata", "Gurgaon",
]


def fill(rng: random.Random, template: str) -> str:
    """Fill a title/description template. Always draws city/n so RNG
    consumption is uniform whether or not a given template uses them."""
    return template.format(
        city=rng.choice(CITIES),
        n=rng.choice([3, 5, 7, 10, 14, 21, 30]),
    )


# ---------------------------------------------------------------------------
# Per-creator title banks: synthetic placeholder titles in each creator's
# real public niche, never claimed as that channel's actual uploads (see
# module docstring). Purely fuel for taxonomy.vectorize()'s keyword count.
# ---------------------------------------------------------------------------

TITLES: dict[str, tuple[str, ...]] = {
    "fit_tuber": (
        "Full Day Of Eating | High Protein Edition",
        "{n} High Protein Snacks For Busy Weekdays",
        "Post Workout Protein Shake Recipe | Gym Nutrition",
        "Whey Protein Review: Best Macros For The Price",
        "{n}-Day Muscle Building Meal Plan",
        "Gym Workout Split For Beginners | Full Routine",
        "Bodybuilding Diet Myths Busted | Nutrition Q&A",
        "Cardio Vs Weights For Fat Loss: What The Macros Say",
        "Protein Bar Taste Test: {n} Brands Ranked",
        "HIIT Workout At Home | No Equipment Needed",
    ),
    "fitness_by_rahul": (
        "Gym Workout Log Week {n} | Progressive Overload",
        "High Protein Meal Prep For The Week",
        "Calisthenics Progress Update: {n} Months In",
        "Muscle Recovery Tips After Leg Day Workout",
        "Best Protein Snacks To Keep In Your Gym Bag",
        "Fitness Q&A: Cardio, Macros And Bodybuilding Basics",
        "{n}-Minute HIIT Workout For Busy Days",
        "Whey Protein Vs Plant Protein: Which Fits Your Macros?",
        "Gym Nutrition Explained: Protein Timing Myths",
        "Full Body Workout Routine For Muscle Gain",
    ),
    "bake_with_shivesh": (
        "Easy Chocolate Cake Recipe | Baking For Beginners",
        "{n}-Ingredient Bread Recipe From My Kitchen",
        "Baking Dessert Basics: Cookies Without An Oven",
        "How To Bake The Perfect Cake At Home",
        "Kitchen Hacks Every Home Baker Should Know",
        "Baking Chef's Guide To Better Bread Texture",
        "Dessert Recipe: No-Bake Cake In {n} Minutes",
        "Baking Ingredients Explained: Flour, Sugar, Butter",
        "My Go-To Kitchen Recipe For A Quick Dessert",
        "Bakery Style Bread Recipe You Can Make At Home",
    ),
    "your_food_lab": (
        "Easy Kitchen Recipe For Busy Weeknights",
        "{n}-Ingredient Dinner Recipe | Full Cooking Tutorial",
        "Cooking Basics: Chef Tips For Better Flavour",
        "Recipe Testing: Is This Dessert Worth The Hype?",
        "Kitchen Essentials Every Home Cook Needs",
        "Quick Cooking Recipe Under {n} Minutes",
        "How A Professional Chef Preps Ingredients",
        "Weekend Cooking Marathon: {n} Recipes, One Kitchen",
        "Dessert Recipe Made Simple For Home Cooks",
        "Cooking Show: Testing A Viral Kitchen Recipe",
    ),
    "kritika_khurana": (
        "Outfit Of The Day: Building A Capsule Wardrobe",
        "{n} Fashion Style Tips For Everyday Looks",
        "Shopping Haul: My Latest Wardrobe Additions",
        "Cafe Hopping In {city} | Outfit Diaries",
        "Lifestyle Vlog: A Day In My Life",
        "Fashion Aesthetic Lookbook For The Season",
        "Ootd Styling Guide: {n} Ways To Wear One Outfit",
        "Wardrobe Essentials Every Closet Needs",
        "Style Q&A: Building Your Personal Aesthetic",
        "Weekend Cafe Outfit Diaries In {city}",
    ),
    "komal_pandey": (
        "Style Experiment: Reworking My Wardrobe",
        "{n} Outfit Ideas For A Cafe Day Out",
        "Fashion Lookbook: Streetwear Meets Ethnic",
        "Shopping Haul And Outfit Styling Session",
        "Lifestyle Vlog: Fashion Week Diaries",
        "Ootd Aesthetic Guide For {city} Weather",
        "Building A Wardrobe On A Budget | Style Tips",
        "Closet Tour: My Go-To Fashion Pieces",
        "Cafe Aesthetic Outfit Of The Day",
        "Style Q&A: Fashion Trends I Am Loving This Season",
    ),
    "urban_desi_vlogs": (
        "A Day In My {city} Life | Lifestyle Vlog",
        "Fashion Haul: {n} Outfits For The Season",
        "Cafe Hopping And Outfit Diaries In {city}",
        "Wardrobe Rebuild: Style Tips For Beginners",
        "Lifestyle Aesthetic Vlog: Weekend Edition",
        "Ootd Lookbook: My Everyday Fashion Style",
        "Shopping Haul: Building A Better Wardrobe",
        "Closet Essentials For A Minimal Aesthetic",
        "Style Diaries: Fashion On A Budget",
        "Weekend Lifestyle Vlog In {city}",
    ),
    "technical_guruji": (
        "{city} Launch Unboxing: New Smartphone First Look",
        "Full Specs Review: Is This Phone Worth It?",
        "Gadget Unboxing: Latest Laptop Benchmark Test",
        "Smartphone Camera Review: Real World Test",
        "Processor Benchmark Comparison: {n} Phones Tested",
        "Tech Gadget Roundup: Best Phones This Month",
        "Laptop Review: Specs, Benchmark And Verdict",
        "Unboxing The Newest Gadget From My Mailbox",
        "Chipset Explained: What The Specs Actually Mean",
        "Phone Camera Review Comparison: {n} Devices",
    ),
    "geeky_ranjit": (
        "Smartphone Unboxing And First Impressions",
        "Gadget Review: Specs, Benchmark, Camera Test",
        "Laptop Benchmark Comparison: {n} Models Tested",
        "Tech News: New Chipset Announced This Week",
        "Phone Camera Review Under {n},000 Rupees",
        "Unboxing The Latest Gadget: Worth The Hype?",
        "Processor Benchmark Deep Dive: Full Specs Test",
        "Gadget Roundup: Best Smartphones This Quarter",
        "Laptop Review: Real World Benchmark Numbers",
        "Tech Gadget Q&A: Specs Explained Simply",
    ),
    "yoga_with_anjali": (
        "{n}-Minute Morning Yoga Routine For Beginners",
        "Yoga For Stress Relief: Breathwork Basics",
        "Mindfulness Meditation: {n} Minutes To Calm Down",
        "Wellness Routine: Yoga And Mental Health Tips",
        "Asana Breakdown: Improve Your Yoga Practice",
        "Self Care Sunday: Yoga And Meditation Guide",
        "Stretching Routine For Better Wellness",
        "Yoga For Beginners: Building A Home Practice",
        "Meditation And Breathwork For Mental Health",
        "Wellness Q&A: Yoga, Mindfulness And Self Care",
    ),
    "cafe_hopper_diaries": (
        "Cafe Hopping In {city}: Best Coffee Spots",
        "Matcha Latte Taste Test: {n} Cafes Reviewed",
        "New Cafe Alert In {city} | Coffee Vlog",
        "Barista Made Me A Cappuccino, Honest Review",
        "Cafe Vlog: Iced Tea And Espresso Tasting Day",
        "Best Coffee And Matcha Spots In {city}",
        "Cafe Crawl: Brew Reviews From {n} Coffee Shops",
        "Chai Vs Matcha Latte: Cafe Taste Test",
        "Weekend Cafe Vlog: Coffee And Matcha Diaries",
        "Espresso Bar Review: Is The Hype Real?",
    ),
    "glow_with_neha": (
        "{n}-Step Skincare Routine For Glowing Skin",
        "Glass Skin Routine: Serum And Moisturiser Guide",
        "Beauty Haul: New Skincare And Makeup Picks",
        "Sunscreen Review: Best Picks For Everyday Skin",
        "Skincare Routine Breakdown: Morning And Night",
        "Makeup Look Using Only {n} Beauty Products",
        "Serum Vs Moisturiser: What Your Skin Actually Needs",
        "Beauty Q&A: Building A Simple Skincare Routine",
        "Glow Up Routine: Skincare Tips That Actually Work",
        "Skincare Ingredients Explained: Serum Edition",
    ),
    "wanderlust_with_kabir": (
        "{city} Travel Vlog: {n}-Day Itinerary",
        "Backpacking Trip: Budget Travel Tips",
        "Hotel Review: Best Stays For A Vacation Destination",
        "Travel Itinerary: Roadtrip Through {city}",
        "Vacation Vlog: Exploring A New Destination",
        "Flight Booking Hacks For Budget Travel",
        "Tourism Guide: {n} Places To Visit This Trip",
        "Roadtrip Diaries: Backpacking Through The Hills",
        "Travel Vlog: {city} Destination Guide",
        "Vacation Planning: Itinerary For A Weekend Trip",
    ),
    "desi_binge_reacts": (
        "Movie Trailer Reaction: Is The Hype Real?",
        "Bollywood Web Series Review: Worth The Watch?",
        "Celebrity Gossip Roundup: This Week In Entertainment",
        "Song Review: New Bollywood Track Breakdown",
        "Comedy Sketch Reaction: Funniest Moments",
        "Web Series Binge Guide: {n} Shows To Watch",
        "Movie Review: New Bollywood Release Reaction",
        "Celebrity Interview Reaction: Entertainment Recap",
        "Trailer Reaction: Upcoming Bollywood Movie",
        "Comedy Sketch Roundup: This Month In Entertainment",
    ),
}

assert set(TITLES) == set(SUBSCRIBERS), "TITLES must cover every creator slug"

# Niche-flavoured generic description filler, reused across a creator's
# videos the same way scripts/make_fixtures.py reuses YT_DESCRIPTIONS.
DESCRIPTIONS: dict[str, tuple[str, ...]] = {
    "fitness": (
        "Sharing my honest gym and nutrition notes in this one.",
        "Not sponsored. Protein and macros breakdown in the pinned comment.",
        "New workout videos every week, full routine linked below.",
    ),
    "baking": (
        "Full recipe and ingredient list in the description below.",
        "Baked this in my home kitchen, nothing fancy, just practice.",
        "New baking videos every week, tell me what to bake next.",
    ),
    "cooking": (
        "Full recipe and cooking steps linked in the pinned comment.",
        "Tested this kitchen recipe twice before filming, worth it.",
        "New cooking videos every week from my home kitchen.",
    ),
    "fashion": (
        "Outfit details and wardrobe links in the description below.",
        "Not sponsored, everything shown was bought with my own money.",
        "New style and lifestyle videos every week.",
    ),
    "tech": (
        "Full specs and benchmark numbers linked in the description.",
        "Unit purchased for review, not sponsored by the brand.",
        "New gadget review videos every week, subscribe for more.",
    ),
    "wellness": (
        "Full yoga routine and breathwork steps in the description.",
        "Recorded this wellness session at home, take it at your pace.",
        "New yoga and mindfulness videos every week.",
    ),
    "cafe": (
        "Cafe location and menu details in the description below.",
        "Paid for this visit myself, honest matcha and coffee review.",
        "New cafe vlog every week, tell me which spot to try next.",
    ),
    "beauty": (
        "Full skincare routine and product list in the description.",
        "Not sponsored, this beauty haul was bought with my own money.",
        "New skincare and beauty videos every week.",
    ),
    "travel": (
        "Full itinerary and hotel details linked in the description.",
        "Self-funded trip, no sponsorship for this travel vlog.",
        "New travel and destination guides every week.",
    ),
    "entertainment": (
        "My honest reaction, timestamps in the pinned comment.",
        "Not sponsored, sharing my take on this one.",
        "New entertainment and reaction videos every week.",
    ),
}

DESCRIPTION_BANK_BY_SLUG: dict[str, str] = {
    "fit_tuber": "fitness",
    "fitness_by_rahul": "fitness",
    "bake_with_shivesh": "baking",
    "your_food_lab": "cooking",
    "kritika_khurana": "fashion",
    "komal_pandey": "fashion",
    "urban_desi_vlogs": "fashion",
    "technical_guruji": "tech",
    "geeky_ranjit": "tech",
    "yoga_with_anjali": "wellness",
    "cafe_hopper_diaries": "cafe",
    "glow_with_neha": "beauty",
    "wanderlust_with_kabir": "travel",
    "desi_binge_reacts": "entertainment",
}

assert set(DESCRIPTION_BANK_BY_SLUG) == set(SUBSCRIBERS)
assert set(DESCRIPTION_BANK_BY_SLUG.values()) == set(DESCRIPTIONS)


# ---------------------------------------------------------------------------
# Video + envelope builders
# ---------------------------------------------------------------------------

def build_videos(rng: random.Random, slug: str) -> list[dict]:
    """~N_VIDEOS videos, most-recent-first, on a plausible 4-9 day upload
    cadence ending just before RETRIEVED_AT (R1: strictly before)."""
    titles = TITLES[slug]
    desc_bank = DESCRIPTIONS[DESCRIPTION_BANK_BY_SLUG[slug]]
    subs = SUBSCRIBERS[slug]
    tilt = ENGAGEMENT_TILT[slug]
    retrieved = datetime.datetime.fromisoformat(RETRIEVED_AT)

    published: list[datetime.datetime] = []
    cursor = retrieved - datetime.timedelta(days=rng.randint(2, 5))
    for _ in range(N_VIDEOS):
        published.append(cursor)
        cursor -= datetime.timedelta(days=rng.randint(4, 9))

    median_views = max(subs * BASE_VIEW_RATIO * tilt, 1.0)
    mu = math.log(median_views)  # lognormvariate's median is exp(mu)

    videos = []
    for idx, pub in enumerate(published):
        view_count = min(int(rng.lognormvariate(mu, LOGNORMAL_SIGMA)), subs * 3)
        videos.append(
            {
                "video_id": f"MOCKCR_{slug}_{idx:03d}",
                "published_at": pub.isoformat(),
                "title": fill(rng, rng.choice(titles)),
                "description": fill(rng, rng.choice(desc_bank)),
                "view_count": max(view_count, 0),
            }
        )
    return videos


def write_fixture(rng: random.Random, creator) -> Path:
    videos = build_videos(rng, creator.slug)
    payload = {
        "channel_id": f"MOCK_UC_{creator.slug}",
        "channel_title": creator.name,
        "subscribers": SUBSCRIBERS[creator.slug],
        "retrieved_at": RETRIEVED_AT,
        "provenance": provenance.FIXTURE,
        "videos": videos,
    }

    stamp = datetime.datetime.fromisoformat(RETRIEVED_AT).strftime("%Y%m%d")
    path = (
        creators_mod.FIXTURES_DIR
        / f"MOCK_youtube_creator_{creator.slug}_{stamp}.json"
    )
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    # R1: no video's published_at may land at/after the file's retrieved_at.
    retrieval_epoch = datetime.datetime.fromisoformat(RETRIEVED_AT).timestamp()
    assert all(
        datetime.datetime.fromisoformat(v["published_at"]).timestamp()
        < retrieval_epoch
        for v in videos
    ), f"{path.name}: a video published_at is not strictly before retrieved_at (R1)"

    # No-fake-data rule: round-trip through the shared creator loader, which
    # enforces MOCK_ naming + fixture provenance + directory placement.
    loaded = creators_mod.load_creator(creator.slug)
    assert loaded["provenance"] == provenance.FIXTURE
    assert loaded["channel_id"] == payload["channel_id"]
    assert loaded["channel_title"] == payload["channel_title"]
    assert loaded["subscribers"] == payload["subscribers"]
    assert loaded["retrieved_at"] == RETRIEVED_AT
    assert len(loaded["videos"]) == N_VIDEOS

    size = path.stat().st_size
    assert size <= MAX_FILE_BYTES, f"{path.name}: {size} bytes exceeds budget"
    return path


def main() -> None:
    rng = random.Random(SEED)  # single seeded instance; never the global RNG

    with run("make_creator_fixtures", notes=f"MOCK_ creator fixtures, seed={SEED}") as ctx:
        ctx.set("seed", SEED)
        ctx.set("retrieved_at", RETRIEVED_AT)
        ctx.set("n_videos_per_creator", N_VIDEOS)
        total_videos = 0
        for creator in creators_mod.STARTER_CREATORS:
            path = write_fixture(rng, creator)
            ctx.add_output(path)
            total_videos += N_VIDEOS
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(
                f"{path.name}: {N_VIDEOS} videos, "
                f"{path.stat().st_size:,} bytes, sha256={digest[:12]}"
            )
        ctx.set("total_videos", total_videos)
        print(
            f"total: {total_videos} videos across "
            f"{len(creators_mod.STARTER_CREATORS)} creator files (provenance=fixture)"
        )


if __name__ == "__main__":
    main()
