# Adjusted Development Plan

Updated after live data-feasibility testing on 2026-07-11.

## Validated Direction

The project remains an AI agent-assisted equity screening system, but its defensible MVP is now defined as an **explainable daily-data research screener** rather than a real-time market product.

Validated prototype sources:

| Data role | Primary source | Key limitation |
| --- | --- | --- |
| S&P 500 universe | Wikipedia constituents table | Cache and validate schema changes |
| Daily OHLCV | Twelve Data `/time_series` | API key and free-plan rate limits |
| Market cap | Price × validated SEC shares | Optional because shares coverage is not complete |
| Annual fundamentals | SEC EDGAR Company Facts | Filing lag and issuer-specific XBRL tags |
| Beta | Calculated from stock and SPY returns | Depends on common daily history |

Nasdaq website capture was rejected after reviewing its legal terms. Yahoo Finance returned HTTP 429 and Stooq returned browser verification. None is an MVP dependency.

## Scope Changes

- Use the wording "latest available daily data" instead of "real-time" or "near-real-time."
- Defer forward PE, analyst targets, ratings, news, and sentiment.
- Derive annual profitability and growth from SEC filings and expose their period end and filing date.
- Use `liabilities_to_equity` as a clearly labeled leverage proxy until debt taxonomy mapping is validated.
- Calculate beta rather than relying on vendor metadata.
- Apply sector-relative scoring for valuation and accounting quality.
- Renormalize factor weights over available metrics; missing values must never become zero scores.

## Phase 1: Data Foundation

Status: in progress.

Completed:

- Reproducible S&P 500 universe loader with CIK mapping.
- Documented Twelve Data adapter with adjusted-price parsing and resumable batching.
- AAPL official-demo market quality validation.
- Cached SEC Company Facts adapter.
- Stratified SEC validation of 88 securities, eight per GICS sector.
- Frozen pre-model data contract and data-quality policy.
- Negative-equity, stale-shares, XBRL-tag transition, and missing-field rules.

Next gate:

1. Configure `TWELVE_DATA_API_KEY`.
2. Run the resumable full S&P 500 market coverage audit.
3. Confirm at least 95% of securities pass the market quality gate.
4. Review failed or special-format symbols and freeze provider ticker mappings.

Exit criteria:

- At least 95% of the S&P 500 has usable daily market history.
- Every factor has a documented source, timestamp, missing-data policy, and direction.
- Sector-specific accounting gaps are measured rather than assumed.
- Split/outlier handling is defined before rankings are produced.

Current status: all criteria except full-universe market coverage are complete. Do not begin factor scoring until the API-key run passes.

## Phase 2: Analytics and Scoring

1. Finalize the unified feature schema.
2. Winsorize outliers and calculate sector-relative percentiles.
3. Build Momentum, Quality, Valuation, Risk, and Sector Strength scores.
4. Renormalize component and mode weights when fields are unavailable.
5. Add ranking stability tests and metric-level explanations.

Do not begin this phase until the Phase 1 exit criteria are met.

## Phase 3: Minimal Product Surface

1. Build the Stock Screener and Stock Detail views first.
2. Show source names, market-data date, filing period, missing fields, and warnings.
3. Add Market Overview and Sector Analysis only after ranking outputs are stable.

## Phase 4: MCP Tools

Expose stable analytical functions as narrow tools:

- `get_stock_universe`
- `get_market_overview`
- `screen_stocks`
- `get_stock_detail`
- `compare_stocks`
- `generate_research_brief`

Raw provider calls should remain internal. MCP responses should return normalized project schemas, not provider-specific JSON.

## Phase 5: AI Agent and Research Briefs

1. Map natural-language intent to validated modes and filters.
2. Ground every statement in MCP output fields.
3. Include data dates, missing-data warnings, and the research-only disclaimer.
4. Reject direct trading instructions and unsupported predictions.

## Final Delivery

- Reproducible data pipeline and cached demo dataset.
- Explainable preference-aware screener.
- Streamlit dashboard.
- MCP tool layer and grounded agent interaction.
- Research paper documenting data limitations, design decisions, and results.
