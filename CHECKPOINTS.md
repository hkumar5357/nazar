# NAZAR — Checkpoints

Milestone summaries for async review. One section per tagged milestone:
`m1-freeze`, `m2-backtest`, `m3-slices`, `m4-app`, `m5-final` (plus
`m1-freeze-real` if real multi-source data shifts calibrated cutoffs after
API keys arrive). PROTOCOL.md §7 amendments are flagged here for review —
self-approved to avoid blocking, per BRIEF §0.7.

## M1 — Data + freeze (`m1-freeze`) — 2026-07-13

**What exists now.** Full ingestion (Google Trends real for all four trends;
Reddit/YouTube fixture-backed until keys arrive, clearly provenance-marked);
locked confirmation events; feature math with a bit-for-bit no-lookahead
test; lifecycle rules behind a freeze guard that makes demo-trend scoring
impossible without the frozen thresholds; calibration run and frozen. 81
tests passing. Every run (including a failed 429 run) logged in `runs/`.

**Data coverage.** Trends: real, 237 complete weeks (2021-12-26 → 2026-07-05,
geo=IN) per trend. Reddit/YouTube: FIXTURES ONLY so far (17k mock items) —
these never appear in outputs presented as real; the export gate refuses
them. Full table: `data/coverage_report.json`.

**Events locked** (`data/events.csv`, all URLs HTTP 200 at lock): three
matcha events (Costa global marker 2026-01-06; Tata Starbucks India
2026-02-12; India food-media confirmation 2026-05-12) and two protein events
(FSSAI evidence regime eff. 2026-01-01; Farmley report 2026-07-03).
⚠ Review: PROTOCOL §7 Amendment A1 — both protocol-named matcha events
failed source verification and were replaced/relabeled; FSSAI renamed
honestly.

**Thresholds frozen** (`pipeline/thresholds_frozen.json`): L1=0.3, L2=0.4,
V0=0.08, V1=0.08, A1=−0.12 — calibrated ONLY on korean_skincare, real
Trends data only, grid rank 2 (score 41.28/90), rationale in the file.
⚠ Review: Amendments A2 (rule-form clarifications, incl. breadth
min(2, n_sources)), A5 (grid extension after the first run, documented
before the re-run in LABNOTES and git history).

**Honest misses, reported as-is.**
1. The pre-registered calibration prior ("explosive 2022-23 → mature by
   2025") is NOT reproduced: real geo=IN Korean skincare rose 2022-23,
   peaked 2024, then declined ~25% to a still-elevated base. Mature share
   2025-26 = 0.026 at the frozen cutoffs. Heating detection DID fire inside
   the pre-registered window (first flag 2022-08-07), with zero false
   Heating in 2026.
2. Reddit/YouTube remain fixtures until keys arrive; the composite runs on
   n_sources=1 (Trends) real data for now, displayed honestly.
3. Machine slept mid-pull Sunday night; pulls executed Monday evening.
   genz_fragrance needed the trendspy fallback after pytrends exhausted
   five 429 retries — the failed run is committed in `runs/`.

**Amendments flagged for review:** A1–A5 in PROTOCOL.md §7.

**Next (M2).** Walk-forward backtest Jan 2025 → Jul 2026; state timeline for
the three demo trends (first scoring of demo categories — correctly AFTER
this tag); matcha first-Heating date; lead times vs locked events; raw
numbers committed before any UI.
