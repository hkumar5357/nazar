"""Single ingestion envelope: real pulls and MOCK_* fixtures flow through
identical code paths, differing only in the `provenance` field.

Envelope (one JSON file per source × trend pull):

    {
      "source": "trends" | "reddit" | "youtube",
      "trend": "<slug from trends_config>",
      "retrieved_at": "<ISO-8601 with offset>",
      "provenance": "real" | "real_manual" | "fixture",
      "query_spec": {...},          # exactly what was asked of the API
      "data": {...}                 # source-specific, see below
    }

Source-specific `data`:

- trends:  {"series": [{"week_start": "YYYY-MM-DD",
                        "values": {"<term>": int, ...},
                        "is_partial": bool}, ...]}
           Weeks start on Sunday (Google Trends weekly buckets).
- reddit:  {"items": [{"id": str, "created_utc": int, "title": str,
                       "text": str, "score": int, "subreddit": str,
                       "num_comments": int}, ...]}
- youtube: {"items": [{"video_id": str, "published_at": "ISO-8601",
                       "title": str, "description": str, "view_count": int,
                       "channel_id": str, "channel_title": str}, ...]}

Placement rules (enforced on save and load):
- data/raw/{source}_{trend}_{YYYYMMDD}.json — real provenance only
- data/fixtures/MOCK_{source}_{trend}_{YYYYMMDD}.json — fixture provenance only
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pipeline import provenance
from pipeline.trends_config import TRENDS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"

SOURCES = ("trends", "reddit", "youtube")


class MissingCredentials(RuntimeError):
    """Raised by a source's fetch() when its API keys are absent from the env."""


class EnvelopeError(ValueError):
    """Malformed pull envelope or a file in the wrong directory for its provenance."""


@dataclass
class Pull:
    source: str
    trend: str
    retrieved_at: str
    provenance: str
    query_spec: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    path: Path | None = None  # set on load/save; not serialized

    def validate(self) -> "Pull":
        if self.source not in SOURCES:
            raise EnvelopeError(f"unknown source {self.source!r}")
        if self.trend not in TRENDS:
            raise EnvelopeError(f"unknown trend {self.trend!r}")
        provenance.validate(self.provenance)
        if not isinstance(self.data, dict):
            raise EnvelopeError("data must be a dict")
        return self

    def to_json(self) -> str:
        d = asdict(self)
        d.pop("path")
        return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()


def save_raw(pull: Pull) -> Path:
    """Write a REAL pull to data/raw/. Fixtures never enter data/raw."""
    pull.validate()
    if not provenance.is_real(pull.provenance):
        raise EnvelopeError(
            f"only real pulls may be saved to data/raw/ (got {pull.provenance!r}); "
            "fixtures are generated into data/fixtures/ by scripts/make_fixtures.py"
        )
    stamp = datetime.datetime.fromisoformat(pull.retrieved_at).strftime("%Y%m%d")
    path = RAW_DIR / f"{pull.source}_{pull.trend}_{stamp}.json"
    path.write_text(pull.to_json())
    pull.path = path
    return path


def load(path: str | Path) -> Pull:
    """Load and validate an envelope; enforce directory/provenance consistency."""
    path = Path(path)
    d = json.loads(path.read_text())
    pull = Pull(
        source=d["source"],
        trend=d["trend"],
        retrieved_at=d["retrieved_at"],
        provenance=d["provenance"],
        query_spec=d.get("query_spec", {}),
        data=d.get("data", {}),
        path=path,
    ).validate()
    in_fixtures = FIXTURES_DIR in path.parents
    if in_fixtures:
        if not path.name.startswith("MOCK_"):
            raise EnvelopeError(f"fixture file must be MOCK_-prefixed: {path.name}")
        if provenance.is_real(pull.provenance):
            raise EnvelopeError(f"file in data/fixtures/ claims real provenance: {path}")
    else:
        if not provenance.is_real(pull.provenance):
            raise EnvelopeError(f"fixture-provenance file outside data/fixtures/: {path}")
    return pull


def latest(source: str, trend: str) -> Pull | None:
    """Newest real raw pull for (source, trend); falls back to the newest
    MOCK_ fixture when no real pull exists. Returns None if neither exists.
    Downstream code must consult .provenance — never assume real."""
    real = sorted(RAW_DIR.glob(f"{source}_{trend}_*.json"))
    if real:
        return load(real[-1])
    fixtures = sorted(FIXTURES_DIR.glob(f"MOCK_{source}_{trend}_*.json"))
    if fixtures:
        return load(fixtures[-1])
    return None
