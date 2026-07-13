# NAZAR — Pre-Registered Evaluation Protocol (v1)

**Author:** Harsh Sinha
**Date:** July 12, 2026 (written BEFORE any model was built or any backtest was run)
**Purpose:** Define what "working" means before building, so results cannot be quietly cherry-picked. Any deviation after the first model run is recorded as a dated AMENDMENT at the bottom of this file.

---

## 1. System under test

**NAZAR** — a trend-lifecycle radar for Indian consumer culture. Prototype scope:

- **Radar (deep):** lifecycle detection (Emerging → Heating → Peaked → Mature/Saturated) for consumer trends in India, from public signals, with a point-in-time backtest.
- **Map (surface):** creator–audience affinity scoring for the golden-thread trend.
- **Math (surface):** transparent launch-economics simulation for one hypothetical launch.

**Golden thread:** matcha (India). **Contrast set:** protein snacks (expected: Peaked), Gen-Z fragrance (expected: Mature/macro). **Calibration trend (thresholds set here, then frozen):** a fourth trend NOT shown in the demo — Korean skincare (India).

## 2. Falsifiable claims

- **C1 — Detection:** Using only data timestamped ≤ T, NAZAR assigns matcha the "Heating" state at some date T meaningfully before mainstream confirmation (events in §4).
- **C2 — Discrimination:** With one shared pipeline and frozen thresholds (no per-category tuning), NAZAR assigns different lifecycle states to matcha (Heating), protein snacks (Peaked), and fragrance (Mature). If all three land in the same state, the system fails this claim and we say so.
- **C3 — Lead time:** NAZAR's matcha "Heating" flag precedes at least one confirmation event by **≥ 60 days** (target; actual number reported whatever it is).
- **C4 — Map sanity:** The affinity model ranks a known creator–brand HIT pairing (SuperYou × Ranveer Singh's fitness-adjacent audience) above two deliberately mismatched control pairings on identical data. Pass/fail per pair.

## 3. Data sources (public only; every pull logged with retrieval date)

Google Trends (geo=IN, weekly series) · Reddit (India-relevant subreddits; post/comment counts, timestamps) · YouTube (India search/upload metadata, view velocities) · publicly retrievable Instagram hashtag counts · quick-commerce listings (manual dated snapshots) · dated news archive (date-filtered search).

**Not used:** private APIs, paid data, scraped personal data, anything behind login.

## 4. Anti-hindsight rules

- **R1 — Point-in-time discipline:** for any backtest date T, features use only data timestamped ≤ T.
- **R2 — Confirmation events fixed in advance.** Candidate events (exact dates locked during Day-1 data collection, before any model run; changes = amendment): matcha — Costa Coffee India matcha-range launch; World Coffee Portal "Matcha Report 2026" publication. Protein — Farmley report (July 2026); FSSAI 2026 protein-claim regulation announcement.
- **R3 — Threshold freezing:** lifecycle-state thresholds (velocity/acceleration/decay cutoffs) are calibrated ONLY on the calibration trend (Korean skincare), then frozen before scoring the three demo categories.
- **R4 — No silent retries:** every scoring run is logged; ugly results appear in lab notes.
- **R5 — LLM boundary:** LLMs may label/cluster raw text (e.g., classifying a post as café-consumption vs at-home/CPG intent). LLMs never produce the lifecycle judgment; that comes from the time-series math. This boundary is what makes NAZAR not a wrapper.

## 5. Metrics reported (all of them, pass or fail)

- **M1:** Lead time in days vs each confirmation event (C3).
- **M2:** Lifecycle state per category + underlying velocity/acceleration/decay numbers (C1, C2).
- **M3:** Matcha signal decomposition — café-intent vs CPG/home-intent share over time (quantifies the "CPG window open" whitespace argument).
- **M4:** Map validation — hit-above-control outcomes per pair (C4).
- **M5:** Honest costs — total build hours, data volume processed, API spend in ₹.

## 6. Declared limitations (in scope of honesty, out of scope of the prototype)

No revenue prediction. No per-post virality prediction. No causal claims. Batch snapshots, not real-time ingestion. India-metro bias in public signals acknowledged. Launch Math is a parameterized simulation on public benchmarks, not a forecast.

## 7. Amendments

All amendments are dated, self-approved to avoid blocking async review, and
flagged in CHECKPOINTS.md. Every one of them was made BEFORE the first
scoring of any demo category (git history: the `m1-freeze` tag precedes all
demo-category scoring commits).

**A1 — 2026-07-13 — Confirmation events (R2).** Of the candidate events in
§4: the Costa Coffee **India** matcha launch has no dated public source (the
January 2026 launch was UK/Ireland); it is kept only as a clearly-labeled
global mainstream marker, dated by its announcement article (2026-01-06).
The WCP "Matcha Report 2026" publication date is only boundable to
2026-02-20..2026-07-06 from public sources, failing R2's exact-date rule; it
is dropped from lead-time math. India-specific replacements, locked with
dated URLs in `data/events.csv` before any model run: Tata Starbucks puts
Iced Matcha on its national India menu (2026-02-12); mainstream India
food-media confirmation that matcha is a café-menu staple (2026-05-12). The
"FSSAI protein-claim regulation" shorthand had no protein-specific dated
notification; locked instead, honestly renamed, as the general
scientific-evidence-for-claims regime (announced 2025-12-31, effective
2026-01-01). Farmley report locked as named (2026-07-03). All five URLs
returned HTTP 200 at lock time.

**A2 — 2026-07-13 — Rule-form clarifications (R3).** Decided and committed
before the threshold freeze; all on the calibration trend only:
(1) state precedence peaked > heating > mature > emerging > undetermined;
(2) the Heating breadth requirement is `breadth >= min(2, n_sources)` so
single-source coverage (pre-API-keys) cannot structurally bar Heating;
(3) "made ≥90% of all-time high earlier" is operationalised as: the
expanding max of the composite reached ≥ L2 at some week strictly before the
current week (any series is trivially at 100% of its own running max);
(4) "accel strongly negative" is quantified as accel ≤ A1 and "high level"
as composite ≥ L2, with A1 calibrated and frozen alongside the cutoffs;
(5) peak_proximity and drawdown are computed on the min-shifted composite,
since a mean of z-scores can be ≤ 0 and ratios on it are undefined.

**A3 — 2026-07-13 — Map validation pairs (C4).** Celebrity-channel YouTube
data is too thin for the SuperYou × Ranveer Singh pairing. C4 becomes:
(a) a fitness/nutrition creator × protein snacks must rank HIGH (top 3);
(b) a tech creator × matcha must rank LOW (bottom 3). SuperYou × Ranveer
Singh moves to the pitch materials as a qualitative case study, outside the
scored artifact.

**A4 — 2026-07-13 — Data-source disclosures (§3, R1).** (1) Google Trends
normalizes a retrieved series over its full window; the backtest truncates
one retrieved series at each walk-forward date T, so datapoint timestamps
respect ≤ T but the normalization denominator does not — disclosed, not
hidden. (2) The prototype implements Google Trends + Reddit + YouTube + the
locked events file; Instagram hashtag counts, quick-commerce snapshots and
news-archive counts listed in §3 are not implemented (scope cut, disclosed).

**A5 — 2026-07-13 — Calibration grid extension (R3).** The first grid run
(blind bounds) could not produce Mature anywhere: a composite of expanding
z-scores decays toward its own expanding mean after a peak, so an aged
plateau lives near z ≈ 0.2–0.6, below the blind L2 floor of 0.8, and twelve
consecutive weeks of |velocity| < 0.05 never occur on a noisy z series. L2
gained {0.2, 0.4, 0.6} and V0 gained {0.08} before the re-run; the
pre-registered arc windows and score formula were not touched. Frozen:
L1=0.3, L2=0.4, V0=0.08, V1=0.08, A1=−0.12 (grid rank 2, score 41.28/90).
Disclosed shortfall: mature share of 2025-26 weeks on the calibration trend
is 0.026 — the "mature/plateau by 2025" prior in §1 is NOT reproduced on
real geo=IN data with the pre-registered rule forms; the real arc is rise
2022-23 → peak 2024 → oscillating decline to a still-elevated base. This is
reported as-is, per §5.
