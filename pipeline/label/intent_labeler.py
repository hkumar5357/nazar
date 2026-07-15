"""Intent labeling workhorse: cafe_experience vs home_or_CPG vs other.

label_items(trend, source) reads the newest pull for (source, trend) via
pipeline.ingest.base.latest, extracts per-item text (reddit: title + text;
youtube: title + description), and labels each item CACHE-FIRST against
data/labels/intent_{trend}_{source}.jsonl (one JSON object per line):

    {item_id, text_sha256, label, method, provider, model,
     prompt_version, tokens_in, tokens_out}

method is "llm" when llm_client.has_api_key() is true (or becomes true
mid-run -- see below), else "heuristic" (prompts.CAFE_KEYWORDS /
HOME_CPG_KEYWORDS; "other" when neither list hits; provider/model are
null, prompt_version is prompts.KEYWORD_HEURISTIC_VERSION).

Cache-first, precisely: an item is skipped (no LLM call, no heuristic
recomputation) iff a cache line already exists for that item_id whose
`method` matches THIS run's method and whose text_sha256 matches the
item's current text. That scoping -- keyed on (method, text_sha256), not
just text_sha256 -- is what makes the "never mixes" rule work: a warm
re-run in the same key-state makes zero calls (method is unchanged, so
every item's existing line matches and is skipped), but the run right
after a real key first appears finds no method="llm" lines yet and labels
everything for real, APPENDING new lines rather than overwriting the old
heuristic ones. On read (build_intent_split), an llm-method line always
wins over a heuristic-method line for the same item.

build_intent_split(trend) aggregates the cache (+ the underlying pulls, to
recover each item's timestamp for weekly bucketing) into
data/labels/intent_split_{trend}.json -- the café-vs-CPG whitespace chart
(BRIEF §6, M3). Weekly bucketing uses the same Sunday-week convention as
pipeline.features (`weekday() + 1) % 7`), reimplemented locally since that
helper is private there.

CLI: `python -m pipeline.label.intent_labeler [trend]` (default "matcha"),
wrapped in pipeline.runlog.run("label_intent") per PROTOCOL R4. Labels
both reddit and youtube for the given trend, then builds the split.

R5 note: nothing in this module ever produces a lifecycle state, score, or
trend judgment -- it only ever writes {label, method, provenance} per item
and per-week counts. The lifecycle math (pipeline.lifecycle) never reads
these files.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

from pipeline import provenance, runlog
from pipeline.ingest import base
from pipeline.label import llm_client, prompts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LABELS_DIR = REPO_ROOT / "data" / "labels"

LABEL_SOURCES = ("reddit", "youtube")

_CACHE_FIELDS = (
    "item_id",
    "text_sha256",
    "label",
    "method",
    "provider",
    "model",
    "prompt_version",
    "tokens_in",
    "tokens_out",
)


def cache_path(trend: str, source: str) -> Path:
    return LABELS_DIR / f"intent_{trend}_{source}.jsonl"


def load_cache(path: Path) -> dict[str, list[dict]]:
    """item_id -> cache records for that item, in file order (oldest
    first). Missing file -> empty dict, not an error (first-ever run)."""
    records: dict[str, list[dict]] = {}
    if not path.exists():
        return records
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        records.setdefault(rec["item_id"], []).append(rec)
    return records


def item_id(source: str, item: dict) -> str:
    if source == "reddit":
        return str(item["id"])
    if source == "youtube":
        return str(item["video_id"])
    raise ValueError(f"unknown source {source!r}")


def item_text(source: str, item: dict) -> str:
    if source == "reddit":
        return f"{item.get('title', '')}\n{item.get('text', '')}".strip()
    if source == "youtube":
        return f"{item.get('title', '')}\n{item.get('description', '')}".strip()
    raise ValueError(f"unknown source {source!r}")


def _item_date(source: str, item: dict) -> datetime.date:
    if source == "reddit":
        return datetime.datetime.fromtimestamp(
            item["created_utc"], tz=datetime.timezone.utc
        ).date()
    if source == "youtube":
        return datetime.datetime.fromisoformat(
            item["published_at"].replace("Z", "+00:00")
        ).date()
    raise ValueError(f"unknown source {source!r}")


def _sunday_of(day: datetime.date) -> datetime.date:
    """Snap to the Sunday starting `day`'s week -- the same convention as
    pipeline.features._sunday_of (Google Trends weekly buckets, BRIEF
    §5.2), reimplemented locally since that helper is private there."""
    return day - datetime.timedelta(days=(day.weekday() + 1) % 7)


def _heuristic_label(text: str) -> str:
    """CAFE_KEYWORDS vs HOME_CPG_KEYWORDS hit counts, case-insensitive
    substring match. Ties (including 0-0) fall to "other" -- a heuristic
    placeholder should not force a confident split it can't support."""
    lowered = text.lower()
    cafe_hits = sum(1 for kw in prompts.CAFE_KEYWORDS if kw in lowered)
    home_hits = sum(1 for kw in prompts.HOME_CPG_KEYWORDS if kw in lowered)
    if cafe_hits > home_hits:
        return "cafe_experience"
    if home_hits > cafe_hits:
        return "home_or_CPG"
    return "other"


def _heuristic_record(iid: str, text_sha256: str, label: str) -> dict:
    return {
        "item_id": iid,
        "text_sha256": text_sha256,
        "label": label,
        "method": "heuristic",
        "provider": None,
        "model": None,
        "prompt_version": prompts.KEYWORD_HEURISTIC_VERSION,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def label_items(trend: str, source: str) -> dict:
    """Cache-first labeling of every item in the newest (source, trend)
    pull. Returns a small summary dict (not the labels themselves --
    those live in the cache file); see the module docstring for the
    cache-first / method-mixing rules.
    """
    pull = base.latest(source, trend)
    if pull is None:
        raise FileNotFoundError(
            f"no pull found for source={source!r} trend={trend!r} "
            "(neither data/raw/ nor data/fixtures/)"
        )
    items = pull.data.get("items", [])

    path = cache_path(trend, source)
    existing = load_cache(path)

    method = "llm" if llm_client.has_api_key() else "heuristic"
    new_records: list[dict] = []
    calls_made = 0

    for item in items:
        iid = item_id(source, item)
        text = item_text(source, item)
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        records_for_item = existing.get(iid, [])
        already_cached = any(
            r["method"] == method and r["text_sha256"] == text_sha256
            for r in records_for_item
        )
        if already_cached:
            continue

        if method == "llm":
            try:
                result = llm_client.label_text(text)
            except llm_client.MissingLLMKey:
                # Key vanished between has_api_key() and here (or was
                # never actually usable) -- degrade gracefully to the
                # heuristic for the remainder of this run. Records already
                # written above stay method="llm"; nothing is rewritten.
                method = "heuristic"
                record = _heuristic_record(iid, text_sha256, _heuristic_label(text))
            else:
                calls_made += 1
                record = {
                    "item_id": iid,
                    "text_sha256": text_sha256,
                    "label": result["label"],
                    "method": "llm",
                    "provider": result["provider"],
                    "model": result["model"],
                    "prompt_version": prompts.PROMPT_VERSION,
                    "tokens_in": result["tokens_in"],
                    "tokens_out": result["tokens_out"],
                }
        else:
            record = _heuristic_record(iid, text_sha256, _heuristic_label(text))

        new_records.append(record)

    if new_records:
        LABELS_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for record in new_records:
                f.write(
                    json.dumps({k: record[k] for k in _CACHE_FIELDS}, ensure_ascii=False)
                    + "\n"
                )

    return {
        "trend": trend,
        "source": source,
        "method": method,
        "items_total": len(items),
        "items_new": len(new_records),
        "calls_made": calls_made,
    }


def _pick_record(records: list[dict], text_sha256: str) -> dict | None:
    """Pick the cached label for an item's CURRENT text.

    Only records whose text_sha256 matches the item's current text are
    eligible — a label produced for an older version of the text is stale
    and rendering it would silently mislabel the current item. Among
    eligible records, LLM wins over heuristic. None if the current text
    was never labeled (caller skips the item rather than fabricating)."""
    matching = [r for r in records if r["text_sha256"] == text_sha256]
    for record in matching:
        if record["method"] == "llm":
            return record
    return matching[0] if matching else None


def build_intent_split(trend: str) -> dict:
    """Aggregate cached labels + the underlying pulls into the weekly
    café-vs-CPG intent split (BRIEF §6, M3 whitespace chart). Writes
    data/labels/intent_split_{trend}.json and returns the same dict.

    Reads only what label_items already wrote/pulled -- calls no LLM.
    """
    pulls: dict[str, base.Pull] = {}
    for source in LABEL_SOURCES:
        pull = base.latest(source, trend)
        if pull is not None:
            pulls[source] = pull

    weekly_counts: dict[datetime.date, dict[str, int]] = {}
    methods_seen: set[str] = set()

    for source, pull in pulls.items():
        cache = load_cache(cache_path(trend, source))
        for item in pull.data.get("items", []):
            iid = item_id(source, item)
            text = item_text(source, item)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            record = _pick_record(cache.get(iid, []), sha)
            if record is None:
                continue  # current text never labeled -- skip, don't fabricate or serve stale
            methods_seen.add(record["method"])
            week = _sunday_of(_item_date(source, item))
            bucket = weekly_counts.setdefault(
                week, {"cafe_experience": 0, "home_or_CPG": 0, "other": 0}
            )
            bucket[record["label"]] += 1

    weekly = [
        {"week": week.isoformat(), **counts}
        for week, counts in sorted(weekly_counts.items())
    ]

    if methods_seen == {"llm"}:
        method_used = "llm"
    elif methods_seen == {"heuristic"}:
        method_used = "heuristic"
    elif methods_seen:
        method_used = "mixed"
    else:
        method_used = "none"
    label_provenance = "real" if methods_seen == {"llm"} else "fixture_heuristic"

    # A single input_provenance value summarizing possibly-two pulls:
    # conservative worst-case (fixture wins over real) so a mixed
    # reddit=real/youtube=fixture pull never reads as fully real at a
    # glance. The full per-source detail still lives in `provenance` below.
    pull_kinds = [p.provenance for p in pulls.values()]
    fixture_kind = next((k for k in pull_kinds if k in provenance.FIXTURE_KINDS), None)
    input_provenance = fixture_kind if fixture_kind is not None else (
        pull_kinds[0] if pull_kinds else None
    )

    labels_kind = provenance.REAL if method_used == "llm" else provenance.FIXTURE_HEURISTIC
    prov_block = provenance.summarize(
        {"labels": labels_kind, "items": input_provenance or provenance.FIXTURE}
    )

    result = {
        "trend": trend,
        "weekly": weekly,
        "method_used": method_used,
        "label_provenance": label_provenance,
        "input_provenance": input_provenance,
        "provenance": prov_block,
    }

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LABELS_DIR / f"intent_split_{trend}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    trend = args[0] if args else "matcha"

    with runlog.run("label_intent", notes=f"trend={trend}") as ctx:
        for source in LABEL_SOURCES:
            pull = base.latest(source, trend)
            if pull is None:
                continue
            if pull.path is not None:
                ctx.add_input(pull.path)
            summary = label_items(trend, source)
            ctx.set(f"labeled_{source}", summary)
            path = cache_path(trend, source)
            if path.exists():
                ctx.add_output(path)

        split = build_intent_split(trend)
        ctx.add_output(LABELS_DIR / f"intent_split_{trend}.json")
        ctx.set("method_used", split["method_used"])
        ctx.set("label_provenance", split["label_provenance"])
        ctx.set("weeks", len(split["weekly"]))


if __name__ == "__main__":
    main()
