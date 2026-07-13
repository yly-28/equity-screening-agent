# Equity Screening Agent

An explainable, preference-aware U.S. equity research screener built on latest-available daily market data and filing-based fundamentals. It is a research-support system, not a price predictor, trading bot, or financial adviser.

## Status

Phase 1 data feasibility validation is complete:

- 503/503 current S&P 500 securities were retrieved from Twelve Data.
- 499/503, or 99.20%, passed the market usability gate.
- SEC Company Facts retrieval and core extraction passed for a stratified 88-security, 11-sector sample.
- The automated suite currently has 11 passing tests.

The active phase is the production feature pipeline. Factor scoring follows only after the full model matrix passes schema, freshness, coverage, and eligibility checks. Streamlit, MCP, and the AI agent remain intentionally deferred.

## Documentation

- [`PROJECT_SPEC.md`](PROJECT_SPEC.md): stable product requirements, architecture, analytical contracts, planned MCP tools, UI scope, and final success criteria.
- [`PROJECT_CONTEXT_AND_PROGRESS.md`](PROJECT_CONTEXT_AND_PROGRESS.md): current implementation state, complete validation evidence, data-quality policy, Git state, commands, and the next development tasks.

These are the only authoritative project Markdown documents. Machine-readable validation evidence is kept under `outputs/` as JSON and CSV.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Fill these local values in `.env`:

```text
TWELVE_DATA_API_KEY=...
SEC_USER_AGENT="equity-screening-agent/0.1 Your Name your-email@example.com"
```

`.env`, provider caches, and security-level provider exports are ignored by Git. Never print or commit their contents.

## Validation Commands

Cross-sector market sample:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-13 --tickers AAPL MSFT JPM XOM JNJ PG CAT NEE LIN AMT PLD
```

Full S&P 500 market audit, resumable from local cache:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-13
```

Stratified SEC audit:

```bash
.venv/bin/python -m src.sec_coverage --as-of 2026-07-13 --per-sector 8
```

Do not add `--refresh` without confirming API allowance, runtime, and the need for a new as-of snapshot.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
```

## Approved Data Boundary

- Universe: Wikipedia current S&P 500 table.
- Daily adjusted OHLCV and SPY benchmark: Twelve Data `/time_series` with `adjust=all`.
- Annual fundamentals: SEC EDGAR Company Facts.
- Local CSV, Parquet, and JSON: reproducibility and rate-limit protection.

Nasdaq website capture is prohibited for this project. Yahoo Finance and Stooq are not runtime dependencies. Forward PE, analyst estimates, targets, news, and sentiment are deferred until a documented and reliable source is approved.
