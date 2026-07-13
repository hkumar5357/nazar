"""Liveness check for the source URLs locked in data/events.csv.

Run at M1 (lock time) and M5 (final verification). This is a helper, not a
gate: some publishers block non-browser clients (403), which still proves the
URL resolves. Anything unreachable gets flagged for a manual browser check.

Usage: ./venv/bin/python scripts/check_events.py
"""

import csv
import sys
from pathlib import Path

import requests

EVENTS_CSV = Path(__file__).resolve().parent.parent / "data" / "events.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


def main() -> int:
    rows = list(csv.DictReader(open(EVENTS_CSV, newline="", encoding="utf-8")))
    print(f"{len(rows)} events in {EVENTS_CSV.name}\n")
    worst = 0
    for row in rows:
        url = row["source_url"]
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
            status = resp.status_code
        except requests.RequestException as exc:
            status = None
            note = f"ERROR: {type(exc).__name__}: {exc}"
        if status == 200:
            note = "ok"
        elif status in (401, 403):
            note = "reachable but bot-blocked — verify manually in a browser"
        elif status is not None:
            note = f"HTTP {status} — verify manually"
            worst = max(worst, 1)
        else:
            worst = max(worst, 1)
        print(f"[{row['event_id']}] {row['event_date']}  {status}  {note}\n    {url}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
