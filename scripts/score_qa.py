"""LLM-label QA sample + scoring (BRIEF §6, M3 deliverable).

generate_sample(trend, n=50, seed=20260712): a stratified-ish, seeded
random sample of `n` REAL LLM-labeled items for `trend` into
data/labels/qa_sample_50.csv (columns: item_id,text,label,human_label --
human_label left empty for Harsh to fill by hand).

Honest refusal: this file exists to check REAL LLM labels against human
judgment. If the label cache for `trend` holds only heuristic placeholder
labels (no LLM key was ever available when label_items ran), a QA sample
would be checking nothing real -- generate_sample refuses outright rather
than silently shipping a sample that looks like QA but isn't.

score(path): reads a filled-in CSV and prints/returns the agreement rate
between the LLM `label` column and the hand-filled `human_label` column.
Rows where human_label is still empty are treated as not-yet-reviewed and
excluded from the rate.

CLI:
    ./venv/bin/python scripts/score_qa.py [trend]           # generate (default trend matcha)
    ./venv/bin/python scripts/score_qa.py score [path]      # score a filled CSV
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.ingest import base
from pipeline.label import intent_labeler

REPO_ROOT = Path(__file__).resolve().parent.parent
QA_SAMPLE_PATH = REPO_ROOT / "data" / "labels" / "qa_sample_50.csv"

CSV_FIELDS = ("item_id", "text", "label", "human_label")


def generate_sample(trend: str, n: int = 50, seed: int = 20260712) -> Path | None:
    """Write data/labels/qa_sample_50.csv; return its path, or None (and
    print an honest refusal) if `trend` has no real LLM labels yet."""
    llm_records: list[tuple[dict, str]] = []

    for source in intent_labeler.LABEL_SOURCES:
        pull = base.latest(source, trend)
        if pull is None:
            continue
        items_by_id = {
            intent_labeler.item_id(source, item): item
            for item in pull.data.get("items", [])
        }
        cache = intent_labeler.load_cache(intent_labeler.cache_path(trend, source))
        for iid, records in cache.items():
            item = items_by_id.get(iid)
            text = intent_labeler.item_text(source, item) if item is not None else ""
            for record in records:
                if record["method"] == "llm":
                    llm_records.append((record, text))

    if not llm_records:
        print(
            "QA sample is for real LLM labels; none exist yet "
            f"(trend={trend!r} cache holds heuristic-only or no labels)."
        )
        return None

    by_label: dict[str, list[tuple[dict, str]]] = {}
    for record, text in llm_records:
        by_label.setdefault(record["label"], []).append((record, text))

    rng = random.Random(seed)
    for bucket in by_label.values():
        rng.shuffle(bucket)

    # Stratified-ish: round-robin across labels in a fixed (sorted) order
    # so the sample isn't dominated by whichever label happens to be most
    # common in the corpus, then keep going until `n` is filled or every
    # bucket is exhausted.
    sample: list[tuple[dict, str]] = []
    labels_sorted = sorted(by_label)
    idx = 0
    while len(sample) < n and any(idx < len(by_label[label]) for label in labels_sorted):
        for label in labels_sorted:
            if len(sample) >= n:
                break
            bucket = by_label[label]
            if idx < len(bucket):
                sample.append(bucket[idx])
        idx += 1

    QA_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QA_SAMPLE_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_FIELDS)
        for record, text in sample:
            writer.writerow([record["item_id"], text, record["label"], ""])

    print(f"wrote {len(sample)} items to {QA_SAMPLE_PATH}")
    return QA_SAMPLE_PATH


def score(path: str | Path = QA_SAMPLE_PATH) -> float:
    """Print and return the agreement rate between `label` and a hand-filled
    `human_label` column. Rows with an empty human_label are skipped."""
    path = Path(path)
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    reviewed = [r for r in rows if r.get("human_label", "").strip()]
    if not reviewed:
        print(f"no reviewed rows in {path} (human_label is empty for all {len(rows)} rows)")
        return 0.0
    agree = sum(1 for r in reviewed if r["human_label"].strip() == r["label"].strip())
    rate = agree / len(reviewed)
    skipped = len(rows) - len(reviewed)
    print(f"agreement: {agree}/{len(reviewed)} = {rate:.3f} ({skipped} rows not yet reviewed)")
    return rate


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "score":
        score(args[1] if len(args) > 1 else QA_SAMPLE_PATH)
        return 0
    trend = args[0] if args else "matcha"
    result = generate_sample(trend)
    return 0 if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
