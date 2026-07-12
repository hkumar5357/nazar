# NAZAR — Build Brief for Claude Code

You are building **NAZAR** (नज़र — "the watchful eye"), a trend-lifecycle radar for Indian consumer culture. It is the proof-of-work artifact in a founding-team job application to OFF/BEAT (Aman Gupta's stealth consumer venture). The audience is a founder who built a ₹3,000 Cr brand on marketing instinct, and his team. The bar is founder-grade: honest, reproducible, sharp.

**Read `PROTOCOL.md` in the repo root before writing any code. It is the contract. This brief operationalizes it; if they ever conflict, PROTOCOL.md wins and you stop and flag it.**

---

## 0. Prime directives (non-negotiable)

1. **Point-in-time discipline (R1).** Any computation "as of date T" uses only data timestamped ≤ T. No exceptions, including chart annotations.
2. **The LLM boundary (R5).** LLMs label/cluster text only. The lifecycle judgment comes from time-series math. Never let an LLM output a lifecycle state, a trend score, or an affinity number.
3. **No fake data, ever.** Mock fixtures are allowed during development but must live in `data/fixtures/`, be named `MOCK_*`, and never appear in any output, chart, or screenshot presented as real. If a real pull fails, the lab notes say so.
4. **Thresholds freeze before demo scoring (R3).** Calibrate state cutoffs ONLY on the calibration trend (Korean skincare). After Harsh approves them at Milestone 1, they are frozen — no per-category tuning afterward, even if the demo categories land "wrong." If results look bad, we report them (that is the whole point of pre-registration).
5. **Every scoring run is logged (R4)** to `runs/` with timestamp, config hash, and outputs — including failed and ugly runs.
6. **Public repo hygiene.** The repo is public from first commit. NEVER commit API keys, tokens, or `.env`. Add `.gitignore` before anything else. Secrets load from environment only.
7. **Checkpoint commits, not hard stops.** Harsh reviews asynchronously — do NOT block on him. At every milestone (§4): append to `LABNOTES.md`, write a summary to `CHECKPOINTS.md`, and make a tagged commit (`m1-freeze`, `m2-backtest`, `m3-slices`, `m4-app`, `m5-final`). One ordering rule is absolute and enforced by git history: **the threshold-freeze commit (`m1-freeze`) must exist BEFORE any commit that scores the demo categories.** That commit order is the pre-registration proof.
8. **Lab notes are a deliverable.** At the end of every working session, append to `LABNOTES.md`: date, what was built, decisions + why, what was cut, what failed, open questions. Write like an engineer's log, not marketing.
9. **No OFF/BEAT branding.** NAZAR has its own identity (§7). Do not use OFF/BEAT's logo, pink/black identity, or trademarks anywhere. One respectful text mention in the app footer: "Built as an independent application artifact for the OFF/BEAT team. Not affiliated."
10. **Scope discipline.** Anything not in this brief is out of scope. When in doubt, ask Harsh instead of building.

---

## 1. Repo layout

```
nazar/
  PROTOCOL.md            # committed first (Phase 0) — do not edit except §7 Amendments
  LABNOTES.md            # append-only build log
  CHECKPOINTS.md         # milestone summaries for Harsh's async review
  README.md              # setup, one-command repro instructions
  .env.example           # documented env vars, no values
  pipeline/              # Python 3.11+
    ingest/
      trends.py          # pytrends, geo=IN, weekly
      reddit.py          # Reddit API (script app)
      youtube.py         # YouTube Data API v3
      news_events.py     # manually curated dated events (CSV in data/)
    label/
      llm_client.py      # provider-agnostic (env LLM_PROVIDER: gemini|openai|anthropic), temp=0
      intent_labeler.py  # café vs home/CPG vs other; cached to JSONL
    features.py          # composite index + feature computation (§5.2)
    lifecycle.py         # state rules (§5.3)
    backtest.py          # walk-forward harness (§5.4)
    map/
      creators.py        # creator metadata + topic vectors
      affinity.py        # affinity scoring (§5.5)
    launch_math.py       # simulator model (§5.6) → emits JSON for UI
    export.py            # writes app/public/data/*.json for the dashboard
  data/
    raw/                 # timestamped raw pulls (committed; small JSON/CSV)
    fixtures/            # MOCK_* development fixtures only
    events.csv           # confirmation events with dates + source URLs (locked at M1)
    labels/              # cached LLM label JSONL (committed)
  runs/                  # logged run outputs incl. failures
  app/                   # React + Vite dashboard (reads static JSON only)
```

Python: `uv` or `pip` + `requirements.txt`. No database — files are fine at this scale. The dashboard consumes only committed JSON exports, so every chart is reproducible from the repo alone.

## 2. Environment / keys (from Harsh, via .env — NOT a dependency)

`YOUTUBE_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `LLM_PROVIDER` + one of `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. Default `LLM_PROVIDER=gemini`.

**Keys arrive late in the build — never block on them.** Workflow: build the entire pipeline, backtest harness, and dashboard against `MOCK_*` fixtures first (pytrends needs no key, so real Google Trends pulls can start immediately — that alone covers the composite index's backbone). When keys land, run the real ingestion, re-freeze on real calibration data (new tagged commit `m1-freeze-real` if cutoffs change, with amendment note), rerun everything, and regenerate all exports. The definition-of-done rule stands: nothing fixture-derived may appear in any final output.

## 2b. Phase 0 — repo bootstrap (your first task)

1. `git init` + create the **public** GitHub repo `nazar` using Harsh's authenticated `gh` CLI (`gh repo create nazar --public --source=. --push`).
2. **First commit: `PROTOCOL.md` alone.** That commit date is the pre-registration timestamp — nothing else in it.
3. Second commit: this brief as `BRIEF.md`, plus `.gitignore` (Python, Node, `.env`, `data/fixtures/` optional) and `.env.example`.
4. Then scaffold the repo layout (§1).

## 3. Trend definitions (term baskets)

Each trend = a basket of signals. Store in `pipeline/trends_config.py`:

- **matcha (golden thread):** Trends terms: "matcha", "matcha latte", "matcha powder", "matcha price"; Reddit search "matcha" across r/india, r/IndianFood, r/bangalore, r/delhi, r/mumbai, r/Cooking (India-filtered where possible); YouTube: "matcha india", "matcha recipe", "matcha kaise banaye".
- **protein snacks (contrast):** "protein chips", "protein bar", "high protein snacks", "protein snacks india"; analogous Reddit/YouTube queries.
- **gen-z fragrance (contrast):** "perfume for men", "attar", "long lasting perfume", "perfume under 500"; analogous queries.
- **korean skincare (calibration only — never in demo):** "korean skincare", "glass skin", "snail mucin".

History window: Jan 2022 → present, weekly.

## 4. Milestones (checkpoint commits — tag, summarize, continue)

Harsh reviews asynchronously via `CHECKPOINTS.md` and tagged commits; you do not wait for approval except where noted.

**M1 — Data + freeze (tag `m1-freeze`).** Data coverage report (per source, per trend, date ranges, gaps — fixtures clearly marked until keys arrive); `data/events.csv` with locked confirmation-event dates + source URLs; calibration on Korean skincare (real pytrends data — available keyless) → threshold cutoffs chosen, documented, COMMITTED AND TAGGED before any demo-category scoring. PROTOCOL amendments (incl. §5.5 C4 swap) written into PROTOCOL.md §7 with date + reason — self-approved, flagged in CHECKPOINTS.md for Harsh's async review.

**M2 — Backtest (tag `m2-backtest`). The moment of truth.** Walk-forward results table, matcha first-"Heating" date, lead time vs each locked event, intent-split series. Raw numbers committed before any UI styling. If lead time < 60 days or discrimination fails: report it exactly as-is in CHECKPOINTS.md with a proposed honest framing — do not massage, do not re-tune.

**M3 — Map + Math slices (tag `m3-slices`).** Affinity board JSON for ~12 creators with validation-pair outcomes (use the §5.5 starter list; flag substitutions in CHECKPOINTS.md); simulator with sourced defaults.

**M4 — Dashboard (tag `m4-app`).** Five screens (§7) running locally from committed JSON.

**M5 — Final (tag `m5-final`).** Reruns verified from clean clone; README, LABNOTES, CHECKPOINTS complete; exports polished. (Video script, PDF, and email are handled outside this repo — do not write them.)

## 5. Module specs

### 5.1 Ingestion
Every pull writes `data/raw/{source}_{trend}_{YYYYMMDD}.json` with a `retrieved_at` field. Respect rate limits (pytrends: sleep + retry; Reddit/YouTube: stay far under quotas). Public data only; nothing behind logins; no personal-data harvesting (aggregate counts and public metadata only).

### 5.2 Features (weekly, per trend, computed at date T over data ≤ T)
- Per-source normalization: expanding-window z-score (no lookahead).
- **Composite index** = mean of available source z-scores; record source count.
- `velocity_8w`: OLS slope of composite over trailing 8 weeks.
- `accel`: velocity_8w now minus velocity_8w 8 weeks prior.
- `peak_proximity`: composite ÷ max(composite up to T).
- `drawdown`: (max-to-date − current) ÷ max-to-date.
- `breadth`: count of sources with positive 8-week slope.

### 5.3 Lifecycle states (initial rules — calibrate cutoffs on Korean skincare, then freeze at M1)
- **Emerging:** level below L1; velocity > 0; accel > 0.
- **Heating:** velocity ≥ V1; accel ≥ 0; breadth ≥ 2; new 26-week high within the last 4 weeks.
- **Peaked:** made ≥90% of all-time high earlier; now velocity ≤ 0 with drawdown 5–30%, or accel strongly negative at high level.
- **Mature:** level ≥ L2 with |velocity| < V0 for ≥ 12 consecutive weeks.
- Else: **Dormant/Undetermined** (show honestly).
Calibration = choose L1, L2, V0, V1 so Korean skincare's known arc (explosive 2022–23 → mature/plateau by 2025) is reproduced. Document chosen values + rationale in LABNOTES and PROTOCOL amendment log if the rule *forms* (not just cutoffs) change.

### 5.4 Backtest
Walk-forward: T = first of each month, Jan 2025 → Jul 2026. At each T: recompute features/states from data ≤ T. Outputs: state timeline table (trend × month), matcha first-Heating date, lead-time vs each event in `events.csv`, and a JSON export for the money-shot chart (composite series + flag markers + event markers). One command: `python -m pipeline.backtest`.

### 5.5 Map (surface slice)
~12 Indian creators with public YouTube presence across niches: wellness/food (e.g., Fit Tuber, Bake with Shivesh, Your Food Lab), lifestyle/café-aesthetic (e.g., Kritika Khurana, Komal Pandey), fitness, plus 2 deliberate mismatch controls (e.g., Technical Guruji). Final list confirmed with Harsh at M1. Per creator: recent ~50 video titles/descriptions → topic vector (embeddings or keyword taxonomy — pick one, document it); engagement quality = median views ÷ subscribers. **Affinity = cosine(creator topic vector, trend topic vector) × engagement factor**, presented as relative ranks, not fake precision.
**Validation (PROTOCOL C4 amendment at M1):** original C4 named SuperYou×Ranveer Singh, but celebrity YT data is thin; amend to: (a) fitness-creator × protein-snacks ranks HIGH, (b) tech-creator × matcha ranks LOW, (c) SuperYou×Ranveer becomes a qualitative case study in the pitch materials. Write the amendment into PROTOCOL.md §7 with date + reason at M1 (self-approved; flag in CHECKPOINTS.md — the visible amendment process is a credibility feature).

### 5.6 Launch Math (surface slice)
Parameterized simulator, all assumptions visible and editable as sliders, each default annotated with a source note: RTD matcha price ₹120–180; COGS = matcha powder (import ₹3–6/g × 2g) + packaging ₹15–25 + co-packing; quick-commerce commission 25–35%; creator-led CAC vs paid CAC benchmark (₹150–400 F&B trial); repeat-rate assumption slider; outputs: contribution per order, CAC payback (orders and months). Permanent banner: **"Simulation on public benchmarks — not a forecast."**

## 6. LLM labeling (the only LLM use)
Sampled Reddit posts/comments + YouTube titles/descriptions mentioning matcha → classify {cafe_experience, home_or_CPG, other}. Temperature 0, fixed prompt committed to repo, all inputs/outputs cached to `data/labels/*.jsonl` and committed. Produce a 50-item random sample file for Harsh to hand-check; report agreement rate in LABNOTES and on the dashboard's protocol page. Output: café-vs-CPG intent share over time (M3, the whitespace chart).

## 7. Dashboard (React + Vite)
Identity: NAZAR's own — dark indigo background, warm amber accent, a minimal "eye" motif, Devanagari नज़र in the wordmark, tagline "Nazar rakhna." Clean, product-grade, no OFF/BEAT assets. Five screens:
1. **Radar** — the lifecycle map: three dots (matcha/protein/fragrance) positioned by state with key features on hover; calibration note visible ("thresholds frozen on a fourth trend — see Protocol").
2. **Golden Thread: Matcha** — the money shot: composite index chart with NAZAR's Heating-flag date vs confirmation-event markers, lead-time badge ("flagged N days early"); below it the café-vs-CPG intent split area chart with the whitespace annotation.
3. **Map** — creator affinity board, ranked, with validation-pair results shown (including the LOW control — showing a low score builds trust).
4. **Math** — the simulator with sliders and the not-a-forecast banner.
5. **Protocol** — renders PROTOCOL.md + amendment log + label QA agreement rate + honest costs (build hours, API spend).
Footer on every screen: independent-artifact disclaimer + "Built by Harsh Sinha" + repo link.

## 8. Definition of done
- [ ] Clean clone → `README` steps → `python -m pipeline.backtest` + `npm run dev` reproduce every number and chart from committed data
- [ ] All five screens working locally; no mock data anywhere user-visible
- [ ] `runs/` contains the full run history including failures
- [ ] LABNOTES.md complete through M5; PROTOCOL amendments (if any) dated and reasoned
- [ ] No secrets in git history; `.env.example` documented
- [ ] Label QA sample generated and agreement rate reported
- [ ] Honest-costs numbers (hours, ₹ API spend) computed for the Protocol screen

## 9. Explicitly out of scope
Real-time ingestion/cron; user auth; deployment (may come later — build so `vite build` works); email/video/PDF copy; any additional trends or modules; Instagram scraping; anything requiring login-walled or paid data; UI features beyond the five screens.

## 10. Timeline context
Harsh records the demo video on **Sat–Sun Jul 18–19** and sends the application **Mon Jul 20**. Suggested pace: M1 by Mon Jul 13, M2 by Wed Jul 15, M3 Thu Jul 16, M4 Fri Jul 17, M5 Sat Jul 18 morning. Keys may arrive mid-build — sequence fixture-independent work first (scaffold, pytrends pulls, calibration, harness, UI shell). If time runs short, cut scope in this order: fragrance contrast dot → Math sliders → Map creator count — never the backtest, the protocol page, or honesty features.
