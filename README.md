# Equity Screening Agent

An explainable, preference-aware U.S. equity research screener. The project uses cached public data and is designed as research support, not financial advice or an automated trading system.

## Current Phase

Data feasibility validation is implemented before scoring, MCP, agent, or UI work. The validated prototype stack is:

- Wikipedia S&P 500 table for ticker, company, GICS sector, industry, and CIK.
- Twelve Data's documented API for adjusted, latest-available daily OHLCV.
- SEC EDGAR Company Facts for filing-based annual accounting data.

Nasdaq website requests are disabled because its legal terms prohibit automated capture. Yahoo Finance and Stooq are not dependencies because their feasibility probes failed.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Create a local `.env` from `.env.example` and fill in the two values. The file is ignored by Git:

```bash
cp .env.example .env
```

## Run Pre-Model Validation

Validate the Twelve Data adapter with its AAPL demo symbol:

```bash
.venv/bin/python -m src.market_coverage --demo --as-of 2026-07-11
```

After setting `TWELVE_DATA_API_KEY`, run the resumable full S&P 500 coverage audit. The free plan requires roughly 63 rate windows for 503 securities plus SPY:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-11
```

Run the cached, stratified SEC audit with eight securities per sector:

```bash
.venv/bin/python -m src.sec_coverage --as-of 2026-07-11 --per-sector 8
```

Primary outputs:

- `outputs/pre_model_validation/market_provider_decision.md`
- `outputs/pre_model_validation/market_coverage_demo.csv`
- `outputs/pre_model_validation/sec_fundamental_coverage_report.md`
- `outputs/pre_model_validation/sec_field_coverage.csv`
- `outputs/pre_model_validation/sec_sector_coverage.csv`
- `outputs/pre_model_validation/pre_model_readiness_report.md`
- `config/data_contract.yaml`
- `DATA_QUALITY_POLICY.md`
- `notebooks/01_data_feasibility.ipynb`

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
```

## Data Boundaries

Twelve Data requests use `adjust=all`; the pipeline still checks extreme moves, missing rows, duplicate dates, freshness, and provenance. Forward PE and analyst estimates are deferred. Market-cap and annual PE proxies are optional because usable SEC shares outstanding covered 77/88 of the stratified sample. Scoring will be sector-relative and will renormalize weights when inputs are inapplicable or missing.
