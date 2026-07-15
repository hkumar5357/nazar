"""Fixed classification prompt + keyword heuristic (PROTOCOL R5's ONLY LLM use).

Two independent classifiers produce the same output shape ({"label": ...}
in {cafe_experience, home_or_CPG, other}) so intent_labeler.py can swap
between them without the caller caring which one ran:

- The LLM prompt below (llm_client.py sends it verbatim). PROMPT_VERSION
  is bumped whenever the prompt text changes, so every cached label
  records exactly which prompt produced it.
- The keyword heuristic (CAFE_KEYWORDS / HOME_CPG_KEYWORDS), used by
  intent_labeler.py while no LLM key is configured. It is NOT an LLM and
  does not touch R5's boundary; it exists purely so the pipeline has
  *something* to label with before keys arrive, and everything it
  produces carries fixture_heuristic provenance (never presented as real).

Both constants below are committed data, not code that calls out to
anything -- importing this module never touches the network.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

# Committed verbatim. Any change to the wording below is a new prompt and
# MUST bump PROMPT_VERSION -- cached labels record the prompt_version they
# were produced under, so a version bump is what tells a future re-run
# "these cached labels came from a different prompt, don't treat them as
# equivalent to freshly-generated ones."
_INSTRUCTIONS = """You are classifying a single social-media post about a consumer trend in India.

Classify the post's INTENT as exactly one of:
- cafe_experience: the poster is consuming, ordering, or reviewing the product at a cafe, restaurant, or retail outlet (e.g. "grabbed a matcha latte at Third Wave", "the barista made it perfectly", "tried the new menu item at the outlet", "price at this cafe is steep").
- home_or_CPG: the poster is buying, making, or using the product at home; discussing a packaged/retail product; or asking where to buy it online (e.g. "made matcha at home with this powder", "ordered a 100g pack on Amazon", "what's the best matcha powder brand?", "found it on Blinkit").
- other: everything else -- jokes, unrelated news, general commentary with no consumption or purchase intent, or posts where intent cannot be determined from the text.

Respond with ONLY a single-line JSON object of the exact form {"label": "cafe_experience"} (or "home_or_CPG" or "other") and nothing else -- no explanation, no markdown, no extra keys.

Examples:

Text: "the barista at the Bandra outlet made the best iced matcha latte I've had, will be going back"
{"label": "cafe_experience"}

Text: "finally got my hands on ceremonial grade matcha powder from Amazon, whisking it up at home every morning now"
{"label": "home_or_CPG"}

Text: "why is everyone suddenly obsessed with matcha, feels like a meme at this point lol"
{"label": "other"}

Now classify this text:

Text: \""""

_SUFFIX = '"\n'


def build_prompt(text: str) -> str:
    """Render the fixed v1 prompt for one text item.

    Interpolation is plain string concatenation, not str.format -- the
    few-shot block above contains literal JSON braces that would otherwise
    need escaping, and concatenation sidesteps that entirely regardless of
    what `text` itself contains.
    """
    return _INSTRUCTIONS + text + _SUFFIX


KEYWORD_HEURISTIC_VERSION = "h1"

# ~15 terms indicating consumption/ordering AT a cafe, restaurant, or
# outlet. Sensible for India: chain names that actually sell matcha/CPG
# trend items locally, plus generic café-visit vocabulary.
CAFE_KEYWORDS = (
    "cafe",
    "café",
    "barista",
    "menu",
    "order",  # substring-matches "order"/"ordered"/"orders"/"ordering"
    "outlet",
    "branch",
    "starbucks",
    "costa",
    "third wave",
    "dine-in",
    "takeaway",
    "went to the",
    "tried the",
    "price at",
)

# ~15 terms indicating buying/making/using AT HOME, packaged retail
# products, or where-to-buy-online. Sensible for India: the quick-commerce
# apps that actually carry these products, plus generic home-prep terms.
HOME_CPG_KEYWORDS = (
    "powder",
    "whisk",
    "recipe",
    "buy online",
    "amazon",
    "blinkit",
    "zepto",
    "instamart",
    "pack",
    "brand",
    "homemade",
    "how to make",
    "grams",
    "jar",
    "where to buy",
)
