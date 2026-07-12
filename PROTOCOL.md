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

*(none yet)*
