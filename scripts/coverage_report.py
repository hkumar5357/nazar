"""Data coverage report (M1 deliverable): per source x trend — provenance,
date range, volume, and gaps. Fixture-backed sources are clearly marked.

Usage: ./venv/bin/python scripts/coverage_report.py
Writes data/coverage_report.json and prints a markdown table.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.ingest import base
from pipeline.trends_config import ALL_TRENDS

OUT = Path(__file__).resolve().parent.parent / "data" / "coverage_report.json"


def summarize(pull: base.Pull) -> dict:
    d = {
        "provenance": pull.provenance,
        "retrieved_at": pull.retrieved_at,
        "file": pull.path.name if pull.path else None,
    }
    if "series" in pull.data:
        rows = pull.data["series"]
        complete = [r for r in rows if not r.get("is_partial")]
        d |= {
            "kind": "weekly_series",
            "weeks": len(complete),
            "partial_weeks_excluded": len(rows) - len(complete),
            "first_week": complete[0]["week_start"] if complete else None,
            "last_week": complete[-1]["week_start"] if complete else None,
        }
    else:
        items = pull.data.get("items", [])
        stamps = []
        for it in items:
            if "created_utc" in it:
                stamps.append(
                    datetime.datetime.fromtimestamp(
                        it["created_utc"], datetime.timezone.utc
                    ).date()
                )
            elif "published_at" in it:
                stamps.append(
                    datetime.datetime.fromisoformat(
                        it["published_at"].replace("Z", "+00:00")
                    ).date()
                )
        d |= {
            "kind": "items",
            "items": len(items),
            "first_item": min(stamps).isoformat() if stamps else None,
            "last_item": max(stamps).isoformat() if stamps else None,
        }
    return d


def main() -> int:
    report = {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).astimezone().isoformat(),
        "coverage": {},
    }
    lines = [
        "| trend | source | provenance | span | volume |",
        "|---|---|---|---|---|",
    ]
    for trend in ALL_TRENDS:
        report["coverage"][trend] = {}
        for source in base.SOURCES:
            pull = base.latest(source, trend)
            if pull is None:
                report["coverage"][trend][source] = None
                lines.append(f"| {trend} | {source} | — | no data | — |")
                continue
            s = summarize(pull)
            report["coverage"][trend][source] = s
            prov = s["provenance"].upper() if "fixture" in s["provenance"] else s["provenance"]
            if s["kind"] == "weekly_series":
                span = f"{s['first_week']} → {s['last_week']}"
                vol = f"{s['weeks']} wks"
            else:
                span = f"{s['first_item']} → {s['last_item']}"
                vol = f"{s['items']} items"
            lines.append(f"| {trend} | {source} | {prov} | {span} | {vol} |")

    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("\n".join(lines))
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
