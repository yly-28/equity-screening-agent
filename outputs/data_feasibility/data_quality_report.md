# Data Feasibility Validation Report

> Superseded market-source decision: this report records the initial field experiment. Nasdaq website capture is not approved for new requests. Current validation uses Twelve Data; see `outputs/pre_model_validation/market_provider_decision.md`.

Generated: 2026-07-11T05:49:09+00:00<br>
Market-data window: 2025-06-06 to 2026-07-11<br>
Sample: 22 S&P 500 securities across 11 sectors

## Executive Decision

The initial experiment established field feasibility. Its Nasdaq rows are retained only as historical evidence; Nasdaq website capture is not approved for continued use. The approved stack is Wikipedia for the universe, Twelve Data for adjusted daily prices, and SEC Company Facts for filing-based fundamentals.

The product should be described as using **latest available daily market data**, not real-time data. The first scoring model must be missing-aware and sector-relative because SEC accounting tags and metric meaning are not uniform across sectors.

## Run Summary

- Universe rows: 503
- Universe sectors: 11
- Nasdaq historical-price success: 22/22
- Nasdaq summary success: 22/22
- SEC Company Facts retrieval success: 22/22
- SEC core accounting extraction success: 22/22
- Latest market-data date: 2026-07-10
- Median fundamental age: 192 days
- Oldest fundamental age: 376 days
- Weak fields in this sample: none in the tested field set

## Source Validation

| source | role | success_count | attempt_count | success_rate | observation |
| --- | --- | --- | --- | --- | --- |
| wikipedia_sp500 | universe | 1 | 1 | 100.0% | 503 rows with GICS sector, industry, and CIK |
| nasdaq_web_json | daily_market_data | 22 | 22 | 100.0% | daily OHLCV available; endpoint is undocumented and closes are not labeled adjusted |
| nasdaq_web_json | market_summary | 22 | 22 | 100.0% | market cap and classification fields tested |
| sec_companyfacts | annual_fundamentals | 22 | 22 | 100.0% | authoritative filings; cross-company tags require normalization |
| yahoo_chart | optional_market_fallback | 0 | 1 | 0.0% | HTTP 429; anonymous requests are rate limited |
| stooq_csv | optional_market_fallback | 0 | 1 | 0.0% | browser verification returned instead of CSV |

## Field Coverage

| group | field | available_count | sample_count | missing_rate | status |
| --- | --- | --- | --- | --- | --- |
| universe | ticker | 22 | 22 | 0.0% | strong |
| universe | company_name | 22 | 22 | 0.0% | strong |
| universe | sector | 22 | 22 | 0.0% | strong |
| universe | industry | 22 | 22 | 0.0% | strong |
| universe | cik | 22 | 22 | 0.0% | strong |
| market | price | 22 | 22 | 0.0% | strong |
| market | return_1m | 22 | 22 | 0.0% | strong |
| market | return_3m | 22 | 22 | 0.0% | strong |
| market | return_6m | 22 | 22 | 0.0% | strong |
| market | volatility_20d | 22 | 22 | 0.0% | strong |
| market | volatility_60d | 22 | 22 | 0.0% | strong |
| market | max_drawdown_1y | 22 | 22 | 0.0% | strong |
| market | ma20_gap | 22 | 22 | 0.0% | strong |
| market | volume_trend | 22 | 22 | 0.0% | strong |
| market | relative_strength_3m | 22 | 22 | 0.0% | strong |
| market | beta_1y | 22 | 22 | 0.0% | strong |
| market | market_cap | 22 | 22 | 0.0% | strong |
| fundamental | annual_revenue | 22 | 22 | 0.0% | strong |
| fundamental | annual_net_income | 22 | 22 | 0.0% | strong |
| fundamental | annual_free_cash_flow | 19 | 22 | 13.6% | usable |
| fundamental | revenue_growth | 22 | 22 | 0.0% | strong |
| fundamental | profit_margin | 22 | 22 | 0.0% | strong |
| fundamental | roe | 22 | 22 | 0.0% | strong |
| fundamental | liabilities_to_equity | 22 | 22 | 0.0% | strong |
| fundamental | annual_pe_proxy | 22 | 22 | 0.0% | strong |

## Observed Limitations

1. Nasdaq historical closes are not explicitly labeled as adjusted prices. Split-like daily moves are flagged, and an adjusted-price provider remains a production requirement.
2. Nasdaq's JSON endpoint is used by its public website but is not a documented stability contract. It must remain behind a provider adapter and local cache.
3. SEC Company Facts is authoritative filing data, but tags differ across issuers and sectors. Financial companies and REITs require sector-aware feature definitions.
4. SEC data does not provide forward PE or analyst estimates. These fields are deferred from the MVP rather than filled with unreliable scraped values.
5. Fundamental timestamps are filing-based and older than daily market timestamps. Both dates must be shown in the UI and MCP responses.
6. Free cash flow was unavailable for JPM, PLD, NEE. It should be optional or replaced with sector-appropriate measures for financials, REITs, and utilities.

## Project Adjustments

- Make Wikipedia + Twelve Data + SEC the approved prototype stack.
- Replace the original generic `debt_to_equity` target with the clearly labeled `liabilities_to_equity` proxy until debt-tag mapping is validated.
- Calculate beta from stock and SPY daily returns instead of relying on a vendor metadata field.
- Use annual PE only as a labeled proxy derived from market capitalization and annual net income; do not call it forward PE.
- Score stocks within sectors where accounting comparability matters, then combine those scores with market-based factors.
- Renormalize factor weights over available inputs; never convert missing fundamentals to zero scores.

## Adjusted Development Order

1. Harden the provider interfaces, caching, timestamps, and data-quality flags.
2. Review provider terms or select a documented API before full-universe bulk downloads.
3. Expand market-data validation to the full S&P 500 and measure request failures.
4. Expand SEC validation by sector and finalize the reliable fundamental feature set.
5. Build sector-relative, missing-aware factor scores and validate ranking stability.
6. Add explanations and a simple Streamlit screener.
7. Expose stable analytical functions through MCP.
8. Add the AI agent only after tool outputs and data contracts are stable.

This validation supports proceeding with the project, but with a narrower and more defensible data claim: an explainable daily equity research screener built on cached public data, not a real-time market-data product.
