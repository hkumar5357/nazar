"""Provenance model: 'real' | 'real_manual' | 'fixture' | 'fixture_heuristic'.

The no-fake-data rule (BRIEF §0.3) is enforced in code, not by memory:
every raw pull is stamped with a provenance kind, every derived artifact
carries a per-source provenance map plus `contains_fixture_data`, and
final exports hard-fail if anything fixture-derived would be presented
as real.

Kinds:
- real:              fetched from the live public API by this pipeline
- real_manual:       manual CSV export from a public UI (e.g. trends.google.com),
                     imported with a documented procedure — still real data
- fixture:           MOCK_* development fixture from data/fixtures/
- fixture_heuristic: placeholder labels from a keyword heuristic used while
                     the LLM key is absent (not an LLM; PROTOCOL R5 unaffected)
"""

from __future__ import annotations

REAL = "real"
REAL_MANUAL = "real_manual"
FIXTURE = "fixture"
FIXTURE_HEURISTIC = "fixture_heuristic"

REAL_KINDS = frozenset({REAL, REAL_MANUAL})
FIXTURE_KINDS = frozenset({FIXTURE, FIXTURE_HEURISTIC})
ALL_KINDS = REAL_KINDS | FIXTURE_KINDS


class ProvenanceError(ValueError):
    """Unknown provenance kind, or fixture data where real data is required."""


def validate(kind: str) -> str:
    if kind not in ALL_KINDS:
        raise ProvenanceError(f"unknown provenance kind: {kind!r}")
    return kind


def is_real(kind: str) -> bool:
    return validate(kind) in REAL_KINDS


def summarize(source_to_kind: dict[str, str]) -> dict:
    """Provenance block for a derived artifact: per-source kinds + fixture flag.

    Every exported JSON embeds this block; the dashboard shows a persistent
    'FIXTURE DATA — NOT REAL' banner whenever contains_fixture_data is true.
    """
    for kind in source_to_kind.values():
        validate(kind)
    return {
        "sources": dict(source_to_kind),
        "contains_fixture_data": any(
            kind in FIXTURE_KINDS for kind in source_to_kind.values()
        ),
    }


def assert_all_real(source_to_kind: dict[str, str], context: str = "") -> None:
    """Hard gate for final outputs (export.py --final)."""
    fixtures = {s: k for s, k in source_to_kind.items() if k in FIXTURE_KINDS}
    if fixtures:
        raise ProvenanceError(
            f"fixture-derived data may never appear in final outputs"
            f"{' (' + context + ')' if context else ''}: {fixtures}"
        )
