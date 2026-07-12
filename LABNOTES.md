# NAZAR — Lab Notes

Append-only engineering log. One entry per working session: what was built,
decisions and why, what was cut, what failed, open questions. Newest at the
bottom. Failures stay in.

---

## Session 0 — 2026-07-12 (Sun evening)

**Built:** Phase 0 repo bootstrap. Commit 1 = PROTOCOL.md alone (the
pre-registration timestamp, same date the protocol was written). Commit 2 =
BRIEF.md + .gitignore + .env.example. This commit = §1 scaffold, venv, pinned
requirements.

**Decisions:**
- pip + venv, not uv (uv not on the build machine; BRIEF allows either).
- Python 3.12.4. Installed pandas 3.0.3 / numpy 2.5.1 — noting that
  pytrends 4.9.2 is unmaintained (last release 2023) and its compatibility
  with pandas 3.x is unverified until the smoke test. trendspy 0.1.6
  installed as the fallback Trends backend (env `TRENDS_BACKEND`).
- Additions to the BRIEF §1 layout, noted here for transparency:
  `pipeline/ingest/base.py` (single ingestion interface so mock fixtures and
  real pulls flow through identical code paths, differing only in a
  `provenance` field), `pipeline/runlog.py` (R4: every scoring run logged,
  including failures), `pipeline/provenance.py` (no-fake-data rule enforced
  in code: exports hard-fail on fixture-derived data), `pipeline/calibrate.py`
  (R3: threshold calibration on the held-out trend).

**Open questions:**
- API keys (YouTube / Reddit / LLM) not yet available — fixture-first
  workflow per BRIEF §2 until they land.
- pytrends viability from this machine/network: smoke test is the next step
  tonight; result will be appended below.
