# Equity Screening Agent: Product and System Specification

## 1. Product Definition

### Title

**AI Agent-Assisted U.S. Equity Screening System with MCP**

### Positioning

An explainable, preference-aware, universe-agnostic stock screening framework for market analysis and investment research support.

The system helps users identify securities worth further research by combining latest-available daily market data, filing-based fundamentals, sector context, risk metrics, and configurable preferences. It returns rankings, factor breakdowns, risk notes, comparisons, and structured research briefs.

It is not:

- a stock-price prediction model;
- a trading bot or order-execution system;
- a portfolio optimizer;
- an automated financial adviser;
- a source of guaranteed returns or unsupported buy/sell recommendations;
- a tick-level or real-time market-data product.

Required wording:

> The system is designed as a decision-support and research-assistance tool, not as an automated trading system or financial advisory service.

## 2. Users and Core Jobs

Primary users are students, retail investors, and analysts who need a reproducible first-pass research screen.

The system should answer questions such as:

- Which stocks are worth further research under current market conditions?
- Which sectors are relatively strong or weak?
- Which stocks best match balanced, growth, value, or low-risk preferences?
- Why does a stock rank highly or poorly?
- What are the main strengths, risks, missing inputs, and next research questions?
- How do several selected stocks compare under the same scoring framework?

Every user-facing claim must be grounded in normalized data, computed factors, or explicit quality flags. The agent must not invent financial analysis when tools return insufficient evidence.

## 3. Design Principles

### Analytical Core Before Agent

Build and validate the data pipeline, feature matrix, scoring model, ranking behavior, and structured explanations before adding Streamlit, MCP, or an AI agent.

### Universe-Agnostic Interfaces

The initial production universe is the current S&P 500, but functions must accept a universe identifier or ticker list:

```python
screen_stocks(universe="sp500", mode="balanced", top_n=20)
```

Do not create S&P-500-only analytical functions such as `screen_sp500_stocks()`.

Initial support:

- `sp500`;
- `custom` ticker list.

Future extensions:

- Nasdaq 100;
- Russell 1000;
- a documented small-cap opportunity universe.

### Explainability and Provenance

Every ranking row and tool response must expose the market-data date, fundamental period, filing date, source names, missing fields, quality flags, exclusion reason, and score breakdown when applicable.

### Missing-Aware and Sector-Aware Analytics

Missing values remain null. Optional factor weights are renormalized over available and economically applicable inputs. Accounting and valuation comparisons are sector-relative where cross-sector meaning is weak.

## 4. Scope

### MVP Must Have

- Current S&P 500 and custom ticker-list support.
- Resumable market and fundamental data pipelines with local caching.
- Versioned unified feature matrix.
- Momentum, quality, valuation, risk, and sector-strength scores.
- Balanced, growth, value, and low-risk modes.
- Preference-aware ranking with filters and score breakdowns.
- Structured strengths, risks, and research-brief inputs.
- Stock Screener and Stock Detail views.
- MCP tools over stable analytical functions.
- Research-only disclaimers and data-quality warnings.

### Should Have

- Agent chat grounded in MCP outputs.
- Stock comparison.
- Market and sector overviews.
- Research brief generation.
- Streamlit demonstration interface.

### Nice to Have

- Additional documented equity universes.
- News or sentiment from an approved source.
- Advanced visualizations.
- Demo video.

### Explicitly Deferred

- Forward PE, analyst targets, ratings, and consensus estimates.
- News and sentiment until a reliable source is approved.
- Point-in-time historical constituent backtesting.
- Automated trading, order execution, and portfolio optimization.

## 5. Target Architecture

```text
User
  -> Streamlit dashboard or chat
  -> AI agent: intent, universe, mode, filters, tool selection
  -> MCP tools: normalized analytical capabilities
  -> Analytics engine: features, scores, ranking, explanations
  -> Data layer: universe, adjusted market data, SEC fundamentals, cache
  -> Outputs: rankings, details, comparisons, sector views, research briefs
```

Dependency direction is strict:

```text
Provider clients -> normalized data -> analytics -> application services
-> MCP tools -> agent/UI
```

Provider-specific JSON must not leak into analytics, MCP schemas, or UI code.

## 6. Data Contract

The normative field definitions live in `config/data_contract.yaml`. The row grain is one security per screening as-of date, keyed by `(as_of_date, ticker)`.

### Identity and Provenance

Required identity fields:

```text
ticker
company_name
sector
industry
cik
```

Required provenance and quality fields:

```text
as_of_date
market_data_source
price_data_end
market_data_age_days
fundamental_data_source
fundamental_period_end
fundamental_filed_date
fundamental_age_days
data_quality_flags
eligible_for_scoring
```

### Market Features

Required or planned market inputs:

```text
price
average_volume_20d
return_1m
return_3m
return_6m
volatility_20d
volatility_60d
max_drawdown_1y
ma20_gap
ma50_gap
volume_trend
relative_strength_3m
beta_1y
```

Beta and relative strength use SPY daily history from the same provider. Prices must be explicitly adjusted.

### Fundamental Features

```text
annual_revenue
annual_net_income
revenue_growth
profit_margin
roe
liabilities_to_equity
annual_free_cash_flow
shares_outstanding
```

Optional derived proxies:

```text
market_cap_proxy = price * valid shares_outstanding
annual_pe_proxy = market_cap_proxy / positive annual_net_income
```

Do not label these proxies as vendor market cap or forward PE. `liabilities_to_equity` remains the explicit leverage proxy until debt-taxonomy mapping is validated.

## 7. Analytics Engine

### Universe Filtering

Supported filters should include:

```text
universe or custom tickers
sector
minimum price
minimum market cap when available
minimum 20-day average volume
data eligibility
top_n
```

### Preprocessing

- Exclude rows that fail required market fields or hard freshness/quality rules.
- Winsorize continuous scoring inputs within sector at the 5th and 95th percentiles.
- Require enough valid observations before calculating a sector percentile.
- Use rank percentiles on a consistent 0-100 scale.
- Reverse direction for metrics where lower is better.
- Preserve raw feature values beside transformed scores.

### Factor Scores

The analytical core produces:

- **Momentum:** returns, moving-average gaps, relative strength, and optional volume trend.
- **Quality:** revenue growth, profit margin, ROE, and applicable cash-flow evidence.
- **Valuation:** annual PE proxy and other approved valuation measures when available.
- **Risk:** volatility, drawdown, beta, liquidity, and quality warnings.
- **Sector Strength:** sector-level relative market performance.

Do not create a score penalty merely because an optional or inapplicable field is null. Data-quality failures should instead produce explicit exclusion or warning states.

### Screening Modes

The source of truth is `config/screening_modes.yaml`.

| Factor | Balanced | Growth | Value | Low Risk |
| --- | ---: | ---: | ---: | ---: |
| Momentum | 0.25 | 0.35 | 0.10 | 0.15 |
| Quality | 0.25 | 0.25 | 0.25 | 0.25 |
| Valuation | 0.20 | 0.10 | 0.35 | 0.15 |
| Risk | 0.15 | 0.10 | 0.20 | 0.35 |
| Sector Strength | 0.15 | 0.20 | 0.10 | 0.10 |

Final score:

```text
sum(applicable factor score * normalized applicable mode weight)
```

A high-opportunity mode may be considered later, after the four initial modes are stable and defensible.

### Explanation Contract

The analytics layer, not the LLM, identifies structured evidence:

```text
main_strengths
main_risks
missing_inputs
quality_warnings
factor_score_breakdown
sector_context
ranking_reason_codes
next_research_questions
```

The LLM may turn these fields into prose but may not introduce unsupported facts.

## 8. Application and MCP Capabilities

MCP is an adapter over tested application services. Raw provider calls remain internal.

| Capability | Purpose | Core input | Core output |
| --- | --- | --- | --- |
| `get_stock_universe` | Resolve a configured universe | universe or custom tickers | identity, sector, industry, eligibility |
| `get_market_overview` | Summarize market and sectors | universe, as-of date | market return, breadth, sector ranking, risk environment |
| `get_market_data` | Return normalized daily history | tickers, period | adjusted OHLCV with dates and provenance |
| `get_fundamental_data` | Return normalized filing metrics | tickers, as-of date | values, periods, filing dates, warnings |
| `screen_stocks` | Run filters and preference-aware ranking | universe, mode, filters, top_n | ranks, factor scores, strengths, risks, dates |
| `get_stock_detail` | Explain one security | ticker, mode, as-of date | features, factors, ranking reason, warnings |
| `compare_stocks` | Compare securities consistently | tickers, mode, as-of date | comparison table, relative strengths and risks |
| `generate_research_brief` | Format grounded research output | ticker, mode, computed evidence | brief, risks, context, questions, disclaimer |

All tool schemas must be narrow, versioned, deterministic for the same snapshot, and independently testable.

## 9. User Interface

The first usable screen should be the operational screener, not a marketing landing page.

### Stock Screener

Controls:

- universe or custom ticker list;
- screening mode;
- sector;
- top N;
- minimum price, market cap when available, and average volume.

Output:

- rank, ticker, company, sector, final score;
- factor scores and main reason codes;
- data date, warnings, and exclusion reason.

### Stock Detail

- Price history and market features.
- Fundamentals with fiscal and filing dates.
- Factor-score breakdown.
- Sector context.
- Strengths, risks, missing fields, and next research questions.

### Later Views

- Market Overview: index/benchmark condition, breadth, sectors, and risk environment.
- Comparison: same-mode side-by-side feature and score comparison.
- Agent Chat: natural-language routing to MCP tools with visible grounding.

## 10. Research Brief Contract

Each brief includes:

```text
Ticker and company
Sector
As-of date and source dates
Screening mode, rank, and final score
Why it appears in the screen
Key strengths
Main risks and missing inputs
Sector context
Factor score breakdown
Suggested next research questions
Disclaimer
```

Required disclaimer:

> This output is generated for educational and research purposes only. It is not financial advice, investment advice, or a recommendation to buy or sell any security.

## 11. Planned Code Boundaries

```text
config/       provider, universe, mode, and data-contract configuration
src/          provider adapters, feature pipeline, analytics, services
tests/        unit, contract, integration, and ranking-stability tests
app/          Streamlit application after analytics stabilizes
mcp_servers/  MCP adapters after application services stabilize
agent/        intent routing and grounded response generation
data/         ignored raw/cache data and versioned processed snapshots
outputs/      machine-readable validation, rankings, and reports
notebooks/    exploration only; no production orchestration
```

Likely future analytical modules:

```text
feature_pipeline.py
scoring.py
screening.py
sector_analysis.py
explanations.py
report_generation.py
```

## 12. Delivery Sequence

1. Validate providers, coverage, and data quality.
2. Build the resumable full-universe feature pipeline.
3. Validate and freeze the versioned model matrix contract.
4. Implement sector-relative factor scoring.
5. Implement preference-aware ranking and structured explanations.
6. Build the minimal Stock Screener and Stock Detail UI.
7. Expose stable services through MCP.
8. Add the grounded AI agent and research briefs.
9. Add market/sector views, comparison, and refinements.
10. Complete the academic paper, screenshots, and optional demo video.

The live status and exact next tasks are maintained in `PROJECT_CONTEXT_AND_PROGRESS.md`.

## 13. Success Criteria

The project is complete when it can:

- reproducibly screen the current S&P 500 and a custom ticker list;
- produce auditable, preference-sensitive rankings under all four modes;
- expose factor scores, strengths, risks, missing inputs, and source dates;
- handle missing and sector-inapplicable data without zero-score distortion;
- provide useful screener and detail interfaces;
- expose stable analytical capabilities as MCP tools;
- ground agent responses and research briefs entirely in tool output;
- clearly communicate limitations and the research-only boundary;
- document methodology, data limitations, design decisions, and example results in the final paper.

Suggested portfolio description:

> Developed a universe-agnostic, preference-aware U.S. equity screening system with adjusted market data, SEC fundamentals, sector-relative factor scoring, MCP tool-calling, and grounded AI research summaries.
