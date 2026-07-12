# NAZAR (नज़र) — trend-lifecycle radar for Indian consumer culture

*Nazar rakhna.*

NAZAR detects where a consumer trend sits in its lifecycle (Emerging → Heating →
Peaked → Mature) from public signals — Google Trends, Reddit, YouTube — using
time-series rules with pre-registered, frozen thresholds and a point-in-time
walk-forward backtest. LLMs are used **only** to label text (café-consumption vs
at-home/CPG intent); the lifecycle judgment is math, not a model's opinion.

**Read [PROTOCOL.md](PROTOCOL.md) first.** It was committed alone, before any
code, as this repo's first commit — that commit date is the pre-registration
timestamp. Every deviation since is a dated amendment in its §7.

> Status: under construction. This README's reproduction steps are finalized at
> milestone `m5-final`.

## Reproduce

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python -m pipeline.backtest   # walk-forward backtest from committed data
cd app && npm ci && npm run dev          # dashboard (reads committed JSON only)
```

API keys are optional for reproduction: all charts render from committed data in
`data/` and `app/public/data/`. To run fresh ingestion, copy `.env.example` to
`.env` and fill in keys. Without keys, keyed sources fall back to `MOCK_*`
fixtures which are clearly marked and never presented as real (see BRIEF.md).

## Repo map

- `PROTOCOL.md` — pre-registered evaluation protocol (the contract)
- `BRIEF.md` — build brief operationalizing the protocol
- `LABNOTES.md` — append-only engineering log, including failures
- `CHECKPOINTS.md` — milestone summaries for async review
- `pipeline/` — Python ingestion → features → lifecycle → backtest → exports
- `data/` — committed raw pulls, fixtures (`MOCK_*` only), labels, events
- `runs/` — every scoring run, logged, including failed ones
- `app/` — React + Vite dashboard (static JSON only)

---

Built as an independent application artifact for the OFF/BEAT team. Not affiliated.
Built by Harsh Sinha.
