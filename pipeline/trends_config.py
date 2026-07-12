"""Trend definitions (term baskets) and pipeline constants. BRIEF §3.

One shared pipeline for all trends (PROTOCOL C2): the same subreddit set and
the same query structure per source, only the terms differ. The calibration
trend (korean_skincare) is used ONLY to calibrate lifecycle thresholds and
never appears in the demo (PROTOCOL R3).
"""

HISTORY_START = "2022-01-01"
GEO = "IN"

CALIBRATION_TREND = "korean_skincare"
DEMO_TRENDS = ["matcha", "protein_snacks", "genz_fragrance"]
ALL_TRENDS = DEMO_TRENDS + [CALIBRATION_TREND]

# India-relevant subreddits, shared across all trends (India-filtered where
# possible; r/Cooking is global but query-filtered).
SUBREDDITS = ["india", "IndianFood", "bangalore", "delhi", "mumbai", "Cooking"]

TRENDS = {
    "matcha": {
        "label": "Matcha",
        "trends_terms": ["matcha", "matcha latte", "matcha powder", "matcha price"],
        "reddit_queries": ["matcha"],
        "youtube_queries": ["matcha india", "matcha recipe", "matcha kaise banaye"],
    },
    "protein_snacks": {
        "label": "Protein snacks",
        "trends_terms": [
            "protein chips",
            "protein bar",
            "high protein snacks",
            "protein snacks india",
        ],
        "reddit_queries": ["protein chips", "protein bar", "protein snacks"],
        "youtube_queries": [
            "protein snacks india",
            "protein chips india",
            "high protein snacks",
        ],
    },
    "genz_fragrance": {
        "label": "Gen-Z fragrance",
        "trends_terms": [
            "perfume for men",
            "attar",
            "long lasting perfume",
            "perfume under 500",
        ],
        "reddit_queries": ["perfume", "attar"],
        "youtube_queries": [
            "perfume for men india",
            "attar india",
            "best perfume under 500",
        ],
    },
    "korean_skincare": {
        "label": "Korean skincare (calibration only)",
        "trends_terms": ["korean skincare", "glass skin", "snail mucin"],
        "reddit_queries": ["korean skincare", "glass skin", "snail mucin"],
        "youtube_queries": [
            "korean skincare india",
            "glass skin routine",
            "snail mucin",
        ],
    },
}


def basket(trend: str) -> dict:
    if trend not in TRENDS:
        raise KeyError(f"unknown trend {trend!r}; known: {sorted(TRENDS)}")
    return TRENDS[trend]
