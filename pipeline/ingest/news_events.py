"""Loader for data/events.csv: dated confirmation events, locked at M1.

PROTOCOL R2 fixes confirmation events in advance: the exact dates are locked
during Day-1 data collection, before any model run, and any later change is a
dated amendment. This loader is deliberately strict — lead-time claims (C3)
are computed against these dates, so a malformed row is an error, never a
silent skip.

CSV columns (exact set, header row required):
    event_id, trend, event_name, event_date, source_url, locked_at, notes

Validation (ValueError with row-by-row specifics on any violation):
  - event_id: non-empty and unique across the file
  - trend: a slug present in trends_config.TRENDS
  - event_date, locked_at: strict ISO YYYY-MM-DD calendar dates
  - source_url: starts with "http" (every event must be publicly checkable)

If the file does not exist yet, raises FileNotFoundError: events are locked
at Milestone 1, and nothing downstream may invent them.
"""

from __future__ import annotations

import csv
import datetime
import re
from pathlib import Path

from pipeline.ingest.base import REPO_ROOT
from pipeline.trends_config import TRENDS

EVENTS_CSV = REPO_ROOT / "data" / "events.csv"

COLUMNS = (
    "event_id",
    "trend",
    "event_name",
    "event_date",
    "source_url",
    "locked_at",
    "notes",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_iso_date(value: str) -> bool:
    """Strict YYYY-MM-DD: correct shape AND a real calendar date."""
    if not _ISO_DATE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def load_events(path: str | Path | None = None) -> list[dict]:
    """Load and validate the locked confirmation events.

    Returns a list of dicts (one per row, whitespace-stripped, columns as
    keys) in file order. Raises FileNotFoundError if the file is absent and
    ValueError listing every violation if any row is malformed.
    """
    csv_path = Path(path) if path is not None else EVENTS_CSV
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found — confirmation events are locked at "
            "Milestone 1 (PROTOCOL R2). Create data/events.csv with the "
            "locked event dates and source URLs before any lead-time "
            "computation; do not invent events downstream."
        )

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = [name.strip() for name in reader.fieldnames or []]
        if sorted(header) != sorted(COLUMNS):
            missing = sorted(set(COLUMNS) - set(header))
            extra = sorted(set(header) - set(COLUMNS))
            raise ValueError(
                f"{csv_path}: bad header — expected columns {list(COLUMNS)}"
                + (f"; missing {missing}" if missing else "")
                + (f"; unexpected {extra}" if extra else "")
            )
        rows = list(reader)

    problems: list[str] = []
    seen_ids: set[str] = set()
    events: list[dict] = []
    for line_no, raw in enumerate(rows, start=2):  # header is line 1
        row = {key: (raw.get(key) or "").strip() for key in COLUMNS}
        where = f"row {line_no} (event_id={row['event_id'] or '<empty>'})"

        if None in raw:  # extra unqualified cells beyond the header width
            problems.append(f"{where}: more cells than header columns")
        if not row["event_id"]:
            problems.append(f"{where}: event_id is empty")
        elif row["event_id"] in seen_ids:
            problems.append(f"{where}: duplicate event_id {row['event_id']!r}")
        else:
            seen_ids.add(row["event_id"])
        if row["trend"] not in TRENDS:
            problems.append(
                f"{where}: unknown trend {row['trend']!r}; known: {sorted(TRENDS)}"
            )
        for date_field in ("event_date", "locked_at"):
            if not _check_iso_date(row[date_field]):
                problems.append(
                    f"{where}: {date_field} {row[date_field]!r} is not a "
                    "valid ISO YYYY-MM-DD date"
                )
        if not row["source_url"].startswith("http"):
            problems.append(
                f"{where}: source_url {row['source_url']!r} must start "
                "with 'http' (events must be publicly checkable)"
            )
        events.append(row)

    if problems:
        raise ValueError(
            f"{csv_path}: {len(problems)} validation problem(s):\n  "
            + "\n  ".join(problems)
        )
    return events
