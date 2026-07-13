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

**Smoke test result (same session):** both Trends backends work. One
payload each, terms = korean-skincare basket, geo=IN, timeframe
2022-01-01→2026-07-12: pytrends 4.9.2 returned 238 weekly rows
(2021-12-26 → 2026-07-12) despite pandas 3.x; trendspy 0.1.6 returned the
identical series (nice mutual cross-check). Last week is `isPartial=True` —
ingestion must exclude partial weeks from scoring. Default backend stays
pytrends per BRIEF §1; `TRENDS_BACKEND=trendspy` is a working fallback.
No 429s tonight; real pulls will still sleep between payloads.

---

## Session 1 — 2026-07-12 (Sun, late night) → M1 build

**Built:** ingestion for all three sources + events loader; deterministic
MOCK_ fixtures (never presentable as real — provenance-stamped, export
gate refuses them); feature math (expanding/trailing only, with a
bit-for-bit no-lookahead invariance test); lifecycle rules with the R3
freeze guard; calibration harness. 81 tests passing.

**Events locked before any model run** (data/events.csv, R2): both matcha
events named in PROTOCOL §4 failed source verification — no dated public
source for a Costa Coffee *India* matcha launch (the 2026-01 launch was
UK/Ireland), and the WCP Matcha Report 2026's publication date is only
boundable to Feb–Jul 2026. Replaced with dated India-specific events
(Tata Starbucks national iced matcha 2026-02-12; India Food Network
mainstream confirmation 2026-05-12), keeping Costa as a clearly-labeled
global marker. FSSAI event renamed honestly: the general
scientific-evidence-for-claims regime effective 2026-01-01 — no
protein-specific dated notification exists in public sources. All five
URLs returned HTTP 200 at lock time. Full reasoning → Amendment A1 at
the freeze commit.

**Pre-registered calibration arc — written and committed BEFORE the
calibration grid ran on any real feature values** (this commit precedes
the first calibration run in git history): per the BRIEF §5.3 prior for
Korean skincare in India — (a) Heating must fire at least once in
2022-07-01..2023-12-31; (b) the majority of complete weeks in
2025-01-01..2026-06-30 should classify Mature; (c) Heating firing in
2026 contradicts the known plateau and is penalised. Mechanical score
(max 90) = 40·(a) + 50·mature_share(b) − min(2·late_heating_weeks, 20).
Grid: L1∈{0.3,0.5,0.8,1.0}, L2∈{0.8,1.0,1.2,1.5} (L1<L2),
V0∈{0.01,0.02,0.03,0.05}, V1∈{0.05,0.08,0.10,0.15},
A1∈{−0.05,−0.08,−0.12} — encoded in pipeline/calibrate.py. Top-5 combos
are printed for human inspection; the pick gets a written rationale in
thresholds_frozen.json. Calibration reads REAL-provenance pulls only.

**Real pulls:** first pytrends attempt tonight hit a Google 429 (the
smoke test earlier probably warmed the rate limiter). Backoff/retry is
running and every attempt is logged; trendspy is the fallback backend if
pytrends exhausts its five attempts. Failures, if any, stay in runs/.

---

## Session 2 — 2026-07-13 (Mon evening) → M1 calibration + freeze

**Machine-sleep confession:** the pull job launched late Sunday actually
executed Monday evening after the laptop woke — data files are dated
2026-07-13, which is fine (fresher data), and the run logs show the real
timeline. matcha + protein_snacks landed via pytrends (protein needed
all 5 backoff attempts); genz_fragrance exhausted pytrends' retries
(failed run committed in runs/, per R4) and landed via the trendspy
backend along with korean_skincare.

**Calibration, first grid run (624 combos):** every combo scored 40/90 —
Heating fires 2022-08-07 (inside the pre-registered window) for
essentially any cutoffs, but mature_share_2025_26 = 0.0 across the whole
grid. Diagnosis on the real feature values, structural not noise: the
composite is a mean of EXPANDING z-scores, so a trend that explodes and
then plateaus decays toward its own expanding mean — Korean skincare's
2025-26 composite lives around 0.2-0.6 with z-scale drawdowns of
0.7-0.9, below the blind grid's L2 floor (0.8); and 12 consecutive weeks
of |velocity| < 0.05 never occur on a noisy z series (longest qualifying
run: 6 weeks even with L2 = 0).

**Grid extension (before re-run, calibration-trend data only):** L2
gains {0.2, 0.4, 0.6}; V0 gains {0.08}. The pre-registered arc windows
and score formula are UNCHANGED. Reasoning: freezing a V0 ≤ 0.05 would
make Mature structurally unreachable for every trend forever — a
degenerate cutoff chosen blind, not a finding.

**Honest headline, written before the re-run:** even the most permissive
probe (L2=0, V0=0.10) yields ≤ 14% Mature weeks in 2025-26. The BRIEF's
prior ("explosive 2022-23 → mature/plateau by 2025") is NOT reproduced
on real geo=IN data with the pre-registered rule forms: the actual arc
is rise 2022-23 → peak 2024 → oscillating decline to a still-elevated
base (raw weekly mean 12 → 37 → ~30). Whatever combo is frozen, that
mismatch gets reported as-is in CHECKPOINTS and on the Protocol screen —
that is what the pre-registration is for.

**FROZEN (grid rank 2 of the 960-combo extended grid, score 41.28/90):**
L1=0.3, L2=0.4, V0=0.08, V1=0.08, A1=−0.12. First Heating 2022-08-07
(inside the pre-registered window); zero false Heating in 2026;
mature_share_2025_26 = 0.026, disclosed. Why this one among the four
score-tied leaders: V1=0.08 gives the identical first flag as 0.05 with
fewer marginal flags afterwards; A1=−0.12 keeps the strongly-negative
accel branch strict so Peaked doesn't cannibalise rare Mature weeks
under precedence. Full rationale + input hash in
pipeline/thresholds_frozen.json. PROTOCOL §7 amendments A1–A5 written.
Tag: m1-freeze. From this commit on, the freeze guard allows demo-trend
scoring — always and only with these frozen values.
