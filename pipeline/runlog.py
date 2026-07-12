"""Run logging (PROTOCOL R4): every pipeline run is recorded, including failures.

Usage:

    from pipeline.runlog import run

    with run("backtest", notes="walk-forward Jan 2025 - Jul 2026") as ctx:
        ctx.add_input(path_to_raw_json)
        ...
        ctx.add_output(path_to_result_json)
        ctx.set("first_heating", "2025-03-01")

Writes runs/{YYYYMMDD_HHMMSS}_{command}/run.json with the git commit, a config
hash (sha256 over thresholds_frozen.json — if it exists — and trends_config.py),
sha256 of every input/output file, and status "ok" | "failed" (with traceback).
A failed run is a logged run: the context manager records the error and
re-raises. Ugly runs are committed, not deleted.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import traceback
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
FROZEN_THRESHOLDS_PATH = REPO_ROOT / "pipeline" / "thresholds_frozen.json"
TRENDS_CONFIG_PATH = REPO_ROOT / "pipeline" / "trends_config.py"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def config_hash() -> str:
    """sha256 over the frozen thresholds (empty if not yet frozen) + trend config."""
    h = hashlib.sha256()
    if FROZEN_THRESHOLDS_PATH.exists():
        h.update(FROZEN_THRESHOLDS_PATH.read_bytes())
    h.update(TRENDS_CONFIG_PATH.read_bytes())
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


class RunContext:
    def __init__(self, command: str, notes: str):
        started = datetime.datetime.now(datetime.timezone.utc).astimezone()
        stamp = started.strftime("%Y%m%d_%H%M%S")
        self.dir = RUNS_DIR / f"{stamp}_{command}"
        n = 2
        while self.dir.exists():
            self.dir = RUNS_DIR / f"{stamp}_{command}_{n}"
            n += 1
        self.dir.mkdir(parents=True)
        self._record = {
            "command": command,
            "notes": notes,
            "started_at": started.isoformat(),
            "finished_at": None,
            "git_commit": git_commit(),
            "config_hash": config_hash(),
            "thresholds_frozen": FROZEN_THRESHOLDS_PATH.exists(),
            "inputs": [],
            "outputs": [],
            "extra": {},
            "status": "running",
            "error": None,
        }
        self._flush()

    def add_input(self, path: str | Path) -> None:
        p = Path(path)
        self._record["inputs"].append(
            {"path": str(p.relative_to(REPO_ROOT) if p.is_absolute() else p),
             "sha256": sha256_file(p)}
        )
        self._flush()

    def add_output(self, path: str | Path) -> None:
        p = Path(path)
        self._record["outputs"].append(
            {"path": str(p.relative_to(REPO_ROOT) if p.is_absolute() else p),
             "sha256": sha256_file(p)}
        )
        self._flush()

    def set(self, key: str, value) -> None:
        self._record["extra"][key] = value
        self._flush()

    def _finish(self, status: str, error: str | None = None) -> None:
        self._record["status"] = status
        self._record["error"] = error
        self._record["finished_at"] = (
            datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        )
        self._flush()

    def _flush(self) -> None:
        (self.dir / "run.json").write_text(
            json.dumps(self._record, indent=2, ensure_ascii=False) + "\n"
        )


@contextmanager
def run(command: str, notes: str = ""):
    ctx = RunContext(command, notes)
    try:
        yield ctx
    except BaseException:
        ctx._finish("failed", error=traceback.format_exc())
        raise
    else:
        ctx._finish("ok")
