"""Generate MOCK_ development fixtures for the two keyed sources (reddit, youtube).

Why this exists: API keys arrive late (BRIEF §2), so the pipeline is built and
exercised against fixtures first. Protocol constraints honoured here:

- No-fake-data rule (BRIEF §0.3): every file is MOCK_-prefixed, lives only in
  data/fixtures/, and carries provenance "fixture". pipeline/ingest/base.load()
  enforces the directory/provenance pairing; this script round-trips every file
  through load() and asserts it before declaring success. Reddit titles are
  template-generic, ids are MOCK_-prefixed, and YouTube channel names all start
  with "Mock" — nothing here can be mistaken for real data on inspection.
- R1 (point-in-time): every item timestamp falls strictly before the envelope's
  retrieved_at, and the weekly window contains no partial weeks. Asserted below.
- R4 (run logging): generation is wrapped in pipeline.runlog.run(), so each
  execution is recorded in runs/ with output hashes.
- R5 is untouched: no LLM anywhere; text comes from fixed phrase banks. The
  banks deliberately mix cafe/venue-experience phrasing, home/CPG phrasing and
  off-topic noise so the intent labeler has something honest to chew on later.

Determinism: a single random.Random(SEED) instance (never the global RNG) is
consumed in a fixed loop order, and retrieved_at is hardcoded, so re-running
this script produces byte-identical files. SEED is today's date, 2026-07-12.

Usage (from the repo root):

    venv/bin/python scripts/make_fixtures.py
"""

from __future__ import annotations

import datetime
import hashlib
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # allow `python scripts/make_fixtures.py`

from pipeline import provenance, trends_config  # noqa: E402
from pipeline.ingest import base  # noqa: E402
from pipeline.runlog import run  # noqa: E402

SEED = 20260712

# Hardcoded so re-runs are byte-identical (a fixture's "retrieval" is the run
# of this script, and that is pinned by design, not observed from the clock).
RETRIEVED_AT = "2026-07-12T21:00:00+05:30"

# Sunday-start weeks (Google-Trends-style buckets), full weeks only: the last
# week (2026-07-05 .. 2026-07-11) closes before RETRIEVED_AT, so no item can
# be timestamped after retrieval (R1).
WEEK_START_FIRST = datetime.date(2022, 1, 2)
WEEK_START_LAST = datetime.date(2026, 7, 5)
WEEK_SECONDS = 7 * 86400

MAX_FILE_BYTES = 1_500_000

UTC = datetime.timezone.utc

# ---------------------------------------------------------------------------
# Volume arcs: expected reddit items/week, piecewise-linear between anchors.
# YouTube volume is roughly one third of reddit's. Arcs encode the shapes the
# lifecycle math should later recover (BRIEF §3 narrative per trend); Poisson
# sampling adds realistic week-to-week noise around them.
# ---------------------------------------------------------------------------

ARC_ANCHORS = {
    # near-zero 2022-23, gentle rise 2024, steep rise 2025, high 2026
    "matcha": [
        ("2022-01-02", 2.5),
        ("2023-06-25", 3.0),
        ("2023-12-31", 4.0),
        ("2024-12-28", 10.0),
        ("2025-12-28", 22.0),
        ("2026-07-05", 26.0),
    ],
    # rise 2022-2024, peak early 2025, visible decline through 2026
    "protein_snacks": [
        ("2022-01-02", 4.0),
        ("2024-12-28", 19.0),
        ("2025-03-01", 22.0),
        ("2025-06-29", 21.0),
        ("2026-07-05", 12.0),
    ],
    # high-ish and flat with noise, tiny upward drift
    "genz_fragrance": [
        ("2022-01-02", 14.0),
        ("2026-07-05", 16.5),
    ],
    # explosive 2022, peak 2023, plateau with slight decline 2024-2026
    "korean_skincare": [
        ("2022-01-02", 3.0),
        ("2022-12-25", 20.0),
        ("2023-04-02", 22.5),
        ("2023-10-01", 22.0),
        ("2023-12-31", 20.0),
        ("2024-06-30", 17.5),
        ("2026-07-05", 15.0),
    ],
}


def arc_value(trend: str, day: datetime.date) -> float:
    """Piecewise-linear interpolation of the trend's arc at `day`."""
    anchors = [
        (datetime.date.fromisoformat(d).toordinal(), lam)
        for d, lam in ARC_ANCHORS[trend]
    ]
    x = day.toordinal()
    if x <= anchors[0][0]:
        return anchors[0][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return anchors[-1][1]


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's Poisson sampler; fine for the small lambdas used here (< 30)."""
    threshold = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


# ---------------------------------------------------------------------------
# Phrase banks. Deliberately generic templates — development fixtures, never
# shown as real. Each trend mixes venue/experience phrasing with home/CPG
# phrasing plus shared off-topic noise, so the intent labeler (BRIEF §6) can
# be exercised on this text before real data lands.
# ---------------------------------------------------------------------------

AREAS = [
    "Indiranagar", "Koramangala", "Bandra West", "Hauz Khas",
    "Connaught Place", "Powai", "Aundh", "Jubilee Hills",
    "Salt Lake", "Anna Nagar",
]
CITIES = [
    "Bangalore", "Delhi", "Mumbai", "Pune",
    "Hyderabad", "Chennai", "Kolkata", "Gurgaon",
]
PRICES = [280, 320, 350, 380, 420, 450]

REDDIT_TITLES = {
    "matcha": {
        "venue": [
            "Tried the matcha latte at a cafe in {area}, worth the hype?",
            "Any cafes in {city} doing a proper ceremonial matcha?",
            "This {area} coffee shop just added an iced matcha to the menu",
            "Matcha latte for Rs {price} at a {city} cafe, is that normal now?",
            "Weekend cafe hop in {area}: ended up ordering matcha twice",
        ],
        "home": [
            "Which matcha powder to buy online for home use?",
            "Best budget matcha whisk and bowl for beginners in India?",
            "Making matcha at home vs paying cafe prices, recipes?",
            "Is culinary grade matcha okay for daily home lattes?",
            "Ordered matcha powder online, how do I store it in {city} humidity?",
        ],
    },
    "protein_snacks": {
        "venue": [
            "The smoothie bar at my {city} gym started stocking protein chips",
            "Post-workout cafe near {area} with actual high protein options?",
            "Tried a protein shake bowl at a cafe in {area}, decent macros",
            "Gym canteen in {city} now sells protein bars at Rs {price}, fair?",
        ],
        "home": [
            "Which protein bar to buy online that doesn't taste like chalk?",
            "Best high protein snacks to keep in the office desk drawer?",
            "Homemade protein chips recipe, worth the effort vs store bought?",
            "Bulk ordering protein bars online, any tips before I commit?",
            "High protein snacks for late night study sessions at home?",
        ],
    },
    "genz_fragrance": {
        "venue": [
            "Spent an hour at the {city} mall perfume counter, totally lost",
            "Attar shop recommendations in {area}? Want to try before buying",
            "Is it okay to ask for testers repeatedly at a {city} store?",
            "Fragrance section at the new {area} department store is huge",
        ],
        "home": [
            "Long lasting perfume under 500 to order online?",
            "Best attar to buy online for daily office wear?",
            "Perfume for men that survives {city} humidity, bottle suggestions",
            "Ordered a perfume for Rs {price} online, decant storage tips?",
            "Building a small fragrance shelf at home on a student budget",
        ],
    },
    "korean_skincare": {
        "venue": [
            "Booked a glass skin facial at a {area} salon, experiences?",
            "Korean skincare studio opened in {city}, has anyone tried it?",
            "Salon in {area} offers a 7-step Korean facial for Rs {price}",
        ],
        "home": [
            "Which snail mucin serum to buy online in India?",
            "Building a 5-step Korean skincare routine at home on a budget",
            "Where to order genuine Korean sunscreens online?",
            "Glass skin routine for {city} weather, what worked for you?",
            "Snail mucin vs plain moisturiser for a home routine?",
        ],
    },
}

# Shared off-topic noise: realistic contamination in keyword search results
# ("match" vs "matcha" and friends). The labeler should mark these "other".
OFFTOPIC_TITLES = [
    "Best breakfast places open early in {area}?",
    "Where to watch the match this weekend in {city}?",
    "Monsoon prep checklist for {city} apartments",
    "Looking for a weekend trek group near {city}",
    "Power cut in {area} again, anyone else?",
    "Good coworking spaces in {area} with day passes?",
    "Moving to {city} next month, which neighbourhoods to consider?",
]

REDDIT_BODIES = [
    "Posting from {city}. Any suggestions appreciated.",
    "First post here, be gentle.",
    "Budget is flexible but quality matters more.",
    "Links welcome if the mods allow them.",
    "Asking for a friend who just moved to {area}.",
]

YT_TITLES = {
    "matcha": [
        "I Tried Making Matcha At Home For 30 Days",
        "Matcha Latte Recipe | 5 Minute Cafe Style",
        "Rating Every Matcha Latte I Found In {city}",
        "Matcha Kaise Banaye | Easy Home Recipe",
        "Is Matcha Worth The Hype? Honest Review",
        "Cafe Vlog: Matcha Tasting Afternoon In {area}",
        "My Morning Routine In {city} | Vlog",
    ],
    "protein_snacks": [
        "Testing 7 Protein Bars So You Don't Have To",
        "High Protein Snacks For Busy Weekdays",
        "Protein Chips: Gimmick Or Actually Good?",
        "DIY Protein Bar Recipe Under Rs 50",
        "What I Eat In A Day | High Protein Edition",
        "Grocery Haul: Protein Snacks Worth Buying In {city}",
        "Full Day Of Eating On A Desk Job",
    ],
    "genz_fragrance": [
        "Best Perfumes For Men Under 500 | Honest Ranking",
        "Attar vs Perfume: What Lasts Longer?",
        "Building A Fragrance Wardrobe On A Budget",
        "Top 5 Long Lasting Perfumes For {city} Weather",
        "Perfume Shopping Vlog At The {city} Mall",
        "Fragrance Mistakes Beginners Make",
        "What's In My Bag | College Edition",
    ],
    "korean_skincare": [
        "Korean Skincare Routine For Indian Skin | Step By Step",
        "Glass Skin In 14 Days? Testing The Routine",
        "Snail Mucin First Impressions | Worth It?",
        "Affordable Korean Skincare Haul Under Rs 2000",
        "Dermat Reacts To My 7-Step Routine",
        "Skincare Shopping In {city} | Vlog",
        "My Honest Skincare Journey",
    ],
}

YT_DESCRIPTIONS = [
    "Sharing my honest take in this one. Timestamps in the pinned comment.",
    "Not sponsored. Everything shown was bought with my own money.",
    "New videos every week. Tell me in the comments what to try next.",
    "Recorded in {city}. Apologies for the traffic noise in the background.",
    "Part of my budget-friendly series. Full list in the description.",
]

# Generic-fake channels; names start with "Mock" so no frame from a fixture
# can pass as real footage of a real creator.
YT_CHANNELS = {
    "matcha": [
        ("Mock Brew Diaries", "MOCK_UC_brewdiaries"),
        ("Mock Kitchen Notes", "MOCK_UC_kitchennotes"),
        ("Mock Cafe Crawl India", "MOCK_UC_cafecrawl"),
        ("Mock Home Barista", "MOCK_UC_homebarista"),
    ],
    "protein_snacks": [
        ("Mock Fit Fuel", "MOCK_UC_fitfuel"),
        ("Mock Macro Meals", "MOCK_UC_macromeals"),
        ("Mock Gym Bag Reviews", "MOCK_UC_gymbag"),
        ("Mock Desk Athlete", "MOCK_UC_deskathlete"),
    ],
    "genz_fragrance": [
        ("Mock Scent Notes", "MOCK_UC_scentnotes"),
        ("Mock Attar Archive", "MOCK_UC_attararchive"),
        ("Mock Budget Scents", "MOCK_UC_budgetscents"),
        ("Mock Fragrance Basics", "MOCK_UC_fragbasics"),
    ],
    "korean_skincare": [
        ("Mock Skin Journal", "MOCK_UC_skinjournal"),
        ("Mock Glow Lab", "MOCK_UC_glowlab"),
        ("Mock Routine Reviews", "MOCK_UC_routinereviews"),
        ("Mock Beauty Shelf", "MOCK_UC_beautyshelf"),
    ],
}

# Two-letter id prefixes keep ids unique ACROSS files, not just within one.
ID_PREFIX = {
    "matcha": "ma",
    "protein_snacks": "pr",
    "genz_fragrance": "ge",
    "korean_skincare": "ko",
}

# Fixed (venue, home, offtopic) intent mixes. Matcha's is time-varying instead:
# home/CPG share rises over the window, which is exactly the M3 whitespace
# story the intent-split chart should later surface.
FIXED_INTENT_MIX = {
    "protein_snacks": (0.25, 0.55, 0.20),
    "genz_fragrance": (0.30, 0.50, 0.20),
    "korean_skincare": (0.20, 0.60, 0.20),
}


def intent_mix(trend: str, t_frac: float) -> tuple[float, float, float]:
    if trend == "matcha":
        home = 0.15 + 0.30 * t_frac  # 0.15 in Jan 2022 -> 0.45 by Jul 2026
        return (0.80 - home, home, 0.20)
    return FIXED_INTENT_MIX[trend]


def fill(rng: random.Random, template: str) -> str:
    """Fill a template. Always draws area/city/price so RNG use is uniform."""
    return template.format(
        area=rng.choice(AREAS),
        city=rng.choice(CITIES),
        price=rng.choice(PRICES),
    )


# ---------------------------------------------------------------------------
# Item builders
# ---------------------------------------------------------------------------

def week_starts() -> list[datetime.date]:
    n_days = (WEEK_START_LAST - WEEK_START_FIRST).days
    assert n_days % 7 == 0, "window must contain only full weeks"
    assert WEEK_START_FIRST.weekday() == 6, "weeks must start on Sunday"
    assert WEEK_START_LAST.weekday() == 6, "weeks must start on Sunday"
    return [
        WEEK_START_FIRST + datetime.timedelta(days=7 * i)
        for i in range(n_days // 7 + 1)
    ]


def week_epoch(week: datetime.date) -> int:
    return int(
        datetime.datetime.combine(week, datetime.time(), tzinfo=UTC).timestamp()
    )


def t_fraction(week: datetime.date) -> float:
    return (week - WEEK_START_FIRST).days / (WEEK_START_LAST - WEEK_START_FIRST).days


def build_reddit_items(rng: random.Random, trend: str) -> list[dict]:
    banks = REDDIT_TITLES[trend]
    items: list[dict] = []
    idx = 0
    for week in week_starts():
        count = poisson(rng, arc_value(trend, week))
        venue_w, home_w, off_w = intent_mix(trend, t_fraction(week))
        base_ts = week_epoch(week)
        # Spread item timestamps inside the week, oldest first.
        offsets = sorted(rng.randrange(WEEK_SECONDS) for _ in range(count))
        for off in offsets:
            intent = rng.choices(
                ("venue", "home", "offtopic"), weights=(venue_w, home_w, off_w)
            )[0]
            if intent == "offtopic":
                title = fill(rng, rng.choice(OFFTOPIC_TITLES))
            else:
                title = fill(rng, rng.choice(banks[intent]))
            body = "" if rng.random() < 0.4 else fill(rng, rng.choice(REDDIT_BODIES))
            items.append(
                {
                    "id": f"MOCK_{ID_PREFIX[trend]}_{idx:06d}",
                    "created_utc": base_ts + off,
                    "title": title,
                    "text": body,
                    "score": min(int(rng.expovariate(1 / 18.0)), 350),
                    "subreddit": rng.choice(trends_config.SUBREDDITS),
                    "num_comments": min(int(rng.expovariate(1 / 5.0)), 60),
                }
            )
            idx += 1
    return items


def build_youtube_items(rng: random.Random, trend: str) -> list[dict]:
    titles = YT_TITLES[trend]
    channels = YT_CHANNELS[trend]
    items: list[dict] = []
    idx = 0
    for week in week_starts():
        count = poisson(rng, arc_value(trend, week) / 3.0)  # ~1/3 of reddit
        base_ts = week_epoch(week)
        offsets = sorted(rng.randrange(WEEK_SECONDS) for _ in range(count))
        for off in offsets:
            published = datetime.datetime.fromtimestamp(base_ts + off, tz=UTC)
            channel_title, channel_id = rng.choice(channels)
            items.append(
                {
                    "video_id": f"MOCK{ID_PREFIX[trend]}{idx:05d}",
                    "published_at": published.isoformat(),
                    "title": fill(rng, rng.choice(titles)),
                    "description": fill(rng, rng.choice(YT_DESCRIPTIONS)),
                    "view_count": min(int(rng.lognormvariate(8.0, 1.25)), 2_000_000),
                    "channel_id": channel_id,
                    "channel_title": channel_title,
                }
            )
            idx += 1
    return items


# ---------------------------------------------------------------------------
# Envelopes + validation
# ---------------------------------------------------------------------------

def query_spec(source: str, trend: str) -> dict:
    """Echo what a real pull for this source x trend would ask of the API."""
    basket = trends_config.basket(trend)
    if source == "reddit":
        return {
            "queries": list(basket["reddit_queries"]),
            "subreddits": list(trends_config.SUBREDDITS),
            "sort": "new",
            "time_filter": "all",
            "history_start": trends_config.HISTORY_START,
        }
    return {
        "queries": list(basket["youtube_queries"]),
        "region_code": trends_config.GEO,
        "order": "date",
        "published_after": trends_config.HISTORY_START + "T00:00:00Z",
        "part": "snippet,statistics",
    }


def item_epoch(source: str, item: dict) -> float:
    if source == "reddit":
        return float(item["created_utc"])
    return datetime.datetime.fromisoformat(item["published_at"]).timestamp()


def write_fixture(source: str, trend: str, items: list[dict]) -> Path:
    pull = base.Pull(
        source=source,
        trend=trend,
        retrieved_at=RETRIEVED_AT,
        provenance=provenance.FIXTURE,
        query_spec=query_spec(source, trend),
        data={"items": items},
    ).validate()

    stamp = datetime.datetime.fromisoformat(RETRIEVED_AT).strftime("%Y%m%d")
    path = base.FIXTURES_DIR / f"MOCK_{source}_{trend}_{stamp}.json"
    path.write_text(pull.to_json())

    # R1: nothing in a pull may be timestamped after its retrieval.
    retrieval_epoch = datetime.datetime.fromisoformat(RETRIEVED_AT).timestamp()
    assert all(item_epoch(source, it) < retrieval_epoch for it in items), (
        f"{path.name}: item timestamped at/after retrieved_at (R1 violation)"
    )

    # No-fake-data rule: the file must round-trip through the shared loader,
    # which enforces MOCK_ naming + fixture provenance + directory placement.
    loaded = base.load(path)
    assert loaded.provenance == provenance.FIXTURE
    assert loaded.source == source and loaded.trend == trend
    assert loaded.retrieved_at == RETRIEVED_AT
    assert loaded.query_spec == pull.query_spec
    assert loaded.data == pull.data

    size = path.stat().st_size
    assert size <= MAX_FILE_BYTES, f"{path.name}: {size} bytes exceeds budget"
    return path


def main() -> None:
    rng = random.Random(SEED)  # single seeded instance; never the global RNG
    builders = {"reddit": build_reddit_items, "youtube": build_youtube_items}

    with run("make_fixtures", notes=f"MOCK_ fixtures, seed={SEED}") as ctx:
        ctx.set("seed", SEED)
        ctx.set("retrieved_at", RETRIEVED_AT)
        ctx.set("weeks", len(week_starts()))
        total_items = 0
        for trend in trends_config.ALL_TRENDS:
            for source in ("reddit", "youtube"):
                items = builders[source](rng, trend)
                path = write_fixture(source, trend, items)
                ctx.add_output(path)
                total_items += len(items)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                print(
                    f"{path.name}: {len(items)} items, "
                    f"{path.stat().st_size:,} bytes, sha256={digest[:12]}"
                )
        ctx.set("total_items", total_items)
        print(f"total: {total_items} items across 8 files (provenance=fixture)")


if __name__ == "__main__":
    main()
