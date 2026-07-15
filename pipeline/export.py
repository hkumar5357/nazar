"""Exports committed pipeline artifacts to app/public/data/ for the dashboard.

The dashboard reads ONLY committed static JSON from app/public/data/ — every
chart is reproducible from the repo alone. This module is also the final
enforcement point of the no-fake-data rule (BRIEF §0.3):

- default mode copies artifacts as-is; anything whose provenance block says
  ``contains_fixture_data: true`` is listed loudly on stdout, and the app
  renders a persistent "FIXTURE DATA — NOT REAL" banner for it.
- ``--final`` HARD-FAILS (non-zero exit, nothing written) if any artifact
  would carry fixture-derived data. The demo build must pass --final for
  every artifact presented as real.

Exports:
- data/backtest/{state_timeline,first_flags,lead_times,goldenthread_chart}.json
- data/labels/intent_split_matcha.json   (fixture_heuristic until LLM key)
- data/map/affinity_board.json           (fixture creators until YT key)
- protocol.json — assembled: PROTOCOL.md markdown, frozen thresholds,
  coverage report, label QA agreement rate (null until real labels are
  hand-checked), honest costs (null until data/costs.json exists at M5)

launch_math.json is written directly by ``python -m pipeline.launch_math``
(it has no data provenance — a bannered simulation on public benchmarks).

Entry point: ``python -m pipeline.export [--final]`` (logged to runs/, R4).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from pipeline import provenance, runlog

REPO_ROOT = runlog.REPO_ROOT
APP_DATA = REPO_ROOT / "app" / "public" / "data"

COPY_SOURCES = [
    REPO_ROOT / "data" / "backtest" / "state_timeline.json",
    REPO_ROOT / "data" / "backtest" / "first_flags.json",
    REPO_ROOT / "data" / "backtest" / "lead_times.json",
    REPO_ROOT / "data" / "backtest" / "goldenthread_chart.json",
    REPO_ROOT / "data" / "labels" / "intent_split_matcha.json",
    REPO_ROOT / "data" / "map" / "affinity_board.json",
]


def _provenance_blocks(payload: dict) -> list[dict]:
    """Every provenance block in an artifact (top-level or per-trend)."""
    blocks = []
    prov = payload.get("provenance")
    if isinstance(prov, dict):
        if "sources" in prov:
            blocks.append(prov)
        else:  # per-trend map of blocks
            blocks.extend(b for b in prov.values() if isinstance(b, dict) and "sources" in b)
    return blocks


def check_artifact(path: Path, final: bool) -> bool:
    """Returns True if the artifact carries fixture-derived data.

    In --final mode, fixture-derived data raises ProvenanceError instead.
    Artifacts with no provenance block at all are refused outright — an
    export without provenance cannot prove it is real.
    """
    payload = json.loads(path.read_text())
    blocks = _provenance_blocks(payload)
    if not blocks:
        raise provenance.ProvenanceError(
            f"{path.name}: no provenance block — refusing to export unprovable data"
        )
    has_fixture = any(b.get("contains_fixture_data") for b in blocks)
    if has_fixture and final:
        for b in blocks:
            provenance.assert_all_real(b.get("sources", {}), context=path.name)
    return has_fixture


def build_protocol_json() -> dict:
    thresholds = None
    tf = REPO_ROOT / "pipeline" / "thresholds_frozen.json"
    if tf.exists():
        thresholds = json.loads(tf.read_text())
    coverage = None
    cov = REPO_ROOT / "data" / "coverage_report.json"
    if cov.exists():
        coverage = json.loads(cov.read_text())
    costs = None
    costs_path = REPO_ROOT / "data" / "costs.json"
    if costs_path.exists():
        costs = json.loads(costs_path.read_text())
    qa = None
    qa_path = REPO_ROOT / "data" / "labels" / "qa_agreement.json"
    if qa_path.exists():
        qa = json.loads(qa_path.read_text())
    return {
        "markdown": (REPO_ROOT / "PROTOCOL.md").read_text(),
        "thresholds_frozen": thresholds,
        "coverage": coverage,
        "qa_agreement": qa,
        "costs": costs,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--final", action="store_true",
                    help="hard-fail if any export would contain fixture-derived data")
    args = ap.parse_args(argv)

    with runlog.run("export", notes="final" if args.final else "dev") as ctx:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        fixture_flagged = []
        for src in COPY_SOURCES:
            if not src.exists():
                print(f"[export] SKIP (missing): {src.relative_to(REPO_ROOT)}")
                continue
            ctx.add_input(src)
            if check_artifact(src, final=args.final):
                fixture_flagged.append(src.name)
            dst = APP_DATA / src.name
            shutil.copyfile(src, dst)
            ctx.add_output(dst)
            print(f"[export] wrote {dst.relative_to(REPO_ROOT)}")

        proto = APP_DATA / "protocol.json"
        proto.write_text(json.dumps(build_protocol_json(), indent=2, ensure_ascii=False) + "\n")
        ctx.add_output(proto)
        print(f"[export] wrote {proto.relative_to(REPO_ROOT)}")

        ctx.set("fixture_flagged", fixture_flagged)
        if fixture_flagged:
            print(
                "[export] FIXTURE-DERIVED (the app will banner these, and "
                f"--final refuses them): {', '.join(fixture_flagged)}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
