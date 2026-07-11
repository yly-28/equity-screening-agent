# AI Agent-Assisted U.S. Equity Screening System with MCP

## 1. Project Overview

### Project Title

**AI Agent-Assisted U.S. Equity Screening System with MCP**

### Subtitle

**A Preference-Aware, Universe-Agnostic Stock Screening Framework for Market Analysis and Investment Research Support**

### One-Sentence Summary

This project builds a user-facing AI agent that uses MCP tools to screen U.S. equities based on current market data, fundamentals, sector trends, risk metrics, and user investment preferences, then generates interpretable rankings and analyst-style research briefs for further research.

---

## 2. Project Goal

The goal of this project is to build a practical stock screening and market analysis system for retail investors and institutional analysts.

The system does **not** predict future stock prices and does **not** provide direct buy/sell recommendations.

Instead, it helps users answer questions such as:

- Which stocks are worth further research under current market conditions?
- Which sectors look strong or weak?
- Which stocks match a growth, value, balanced, or low-risk preference?
- Why does a stock appear in the screening result?
- What are the key strengths and risks of a stock?

The project focuses on:

- Market analysis
- Stock screening
- User-preference-aware ranking
- Factor-based explanation
- AI-generated research briefs
- MCP-based tool-calling architecture

---

## 3. Core Product Concept

Users interact with the system through a dashboard or chat interface.

Example user queries:

```text
Find high-quality growth stocks today.
Show undervalued stocks with strong fundamentals.
Which sectors look strong right now?
Find lower-risk large-cap stocks.
Generate a research brief for the top 5 ranked stocks.
Compare MSFT, NVDA, and AAPL.
```

The AI agent interprets the user intent, selects the appropriate stock universe and screening mode, calls MCP tools, and returns:

- Personalized stock rankings
- Score breakdowns
- Market and sector insights
- Stock-level explanations
- Analyst-style research briefs
- Risk notes and next-step research questions

---

## 4. Key Design Principle

### Universe-Agnostic Architecture

The system should **not** be hardcoded for only S&P 500 stocks.

S&P 500 is the default initial universe because it has better data quality, better liquidity, and more reliable fundamental information.

However, the architecture must support future expansion to broader stock universes.

The system should be designed as:

```python
screen_stocks(universe="sp500", mode="balanced", top_n=20)
```

Not as:

```python
screen_sp500_stocks()
```

This allows future support for:

- S&P 500
- Nasdaq 100
- Russell 1000
- Small-cap opportunity pool
- Custom ticker list

The initial implementation can focus on S&P 500, but the architecture must be extensible.

---

## 5. Final System Architecture

```text
User
 ↓
Streamlit Dashboard / Chat Interface
 ↓
AI Agent Layer
 ├── Understands user intent
 ├── Detects investment preference
 ├── Selects screening mode
 └── Selects stock universe
 ↓
MCP Tool Layer
 ├── Universe Tool
 ├── Market Data Tool
 ├── Fundamental Tool
 ├── Risk & Sector Tool
 ├── Preference-Aware Screening Tool
 └── Report Tool
 ↓
Analytics Engine
 ├── Universe Filtering
 ├── Data Standardization
 ├── Feature Engineering
 ├── Factor Scoring
 ├── Dynamic Weight Adjustment
 ├── Stock Ranking
 └── Explanation Generation
 ↓
Output Layer
 ├── Personalized Ranking Table
 ├── Market Overview
 ├── Sector Insights
 ├── Stock-Level Score Breakdown
 └── User-Specific Research Brief
```

---

## 6. Main Components

### 6.1 User Interface Layer

The user interface can be built with Streamlit.

Recommended pages:

#### Page 1: Market Overview

Shows:

- Overall market condition
- Major index movement
- Strong and weak sectors
- Market breadth
- Top movers
- Risk environment

#### Page 2: Stock Screener

Allows users to select:

- Stock universe
- Screening mode
- Sector filter
- Top N results
- Minimum market cap
- Minimum price
- Minimum average volume

Displays:

- Ranking table
- Final score
- Factor scores
- Sector
- Company name
- Risk level

#### Page 3: Stock Detail

Displays for one selected stock:

- Recent price trend
- Momentum metrics
- Fundamental metrics
- Risk metrics
- Sector context
- Score breakdown
- AI-generated research brief

#### Page 4: Agent Chat

Allows natural language queries such as:

```text
Find undervalued large-cap stocks.
Show stocks with strong momentum but moderate risk.
Why is this stock ranked highly?
Compare MSFT and NVDA.
Generate a research brief for COST.
```

---

### 6.2 AI Agent Layer

The AI Agent is responsible for:

- Understanding user intent
- Detecting investment preference
- Selecting the appropriate screening mode
- Selecting the stock universe
- Choosing which MCP tools to call
- Generating a natural language response based on tool outputs

The agent should not invent financial analysis without tool results.

All stock rankings and explanations should be grounded in:

- Actual market data
- Fundamental metrics
- Factor scores
- Sector analysis
- Risk metrics
- Screening results

Example:

User query:

```text
Find undervalued stocks with strong fundamentals.
```

Agent interpretation:

```text
Preference: Value + Quality
Mode: value
Universe: default sp500
Tools needed:
- get_stock_universe
- fetch_market_data
- fetch_fundamental_data
- screen_stocks
- generate_screening_summary
```

---

### 6.3 MCP Tool Layer

The MCP layer exposes system capabilities as standardized tools that the AI Agent can call.

#### Required MCP Tools

##### 1. `get_stock_universe`

Purpose:

Returns the list of tickers in the selected universe.

Input:

```json
{
  "universe": "sp500"
}
```

Output fields:

```text
ticker
company_name
sector
industry
market_cap
exchange
universe_name
```

Supported universes in initial design:

```text
sp500
custom
```

Future supported universes:

```text
nasdaq100
russell1000
small_cap_opportunity
```

---

##### 2. `get_market_overview`

Purpose:

Provides current market and sector-level overview.

Input:

```json
{
  "universe": "sp500"
}
```

Output:

```text
market_return
sector_performance
top_sectors
weak_sectors
market_breadth
risk_environment
```

---

##### 3. `get_market_data`

Purpose:

Fetches latest and historical market data for selected tickers.

Input:

```json
{
  "tickers": ["MSFT", "NVDA", "AAPL"],
  "period": "1y"
}
```

Output:

```text
date
ticker
open
high
low
close
adjusted_close
volume
```

---

##### 4. `get_fundamental_data`

Purpose:

Fetches fundamental metrics for selected tickers.

Input:

```json
{
  "tickers": ["MSFT", "NVDA", "AAPL"]
}
```

Output:

```text
ticker
market_cap
pe_ratio
forward_pe
price_to_sales
profit_margin
revenue_growth
roe
debt_to_equity
free_cash_flow
beta
```

---

##### 5. `screen_stocks`

Purpose:

Runs the full screening pipeline.

Input:

```json
{
  "universe": "sp500",
  "mode": "balanced",
  "sector": null,
  "top_n": 20,
  "filters": {
    "min_price": 5,
    "min_market_cap": null,
    "min_avg_volume": null
  }
}
```

Output:

```text
rank
ticker
company_name
sector
final_score
momentum_score
quality_score
valuation_score
risk_score
sector_strength_score
main_strengths
main_risks
```

---

##### 6. `get_stock_detail`

Purpose:

Returns detailed factor breakdown for one stock.

Input:

```json
{
  "ticker": "MSFT",
  "mode": "balanced"
}
```

Output:

```text
ticker
company_name
sector
market_metrics
fundamental_metrics
risk_metrics
factor_scores
ranking_reason
risk_notes
```

---

##### 7. `compare_stocks`

Purpose:

Compares multiple stocks using the same scoring framework.

Input:

```json
{
  "tickers": ["MSFT", "NVDA", "AAPL"],
  "mode": "balanced"
}
```

Output:

```text
comparison_table
relative_strengths
relative_weaknesses
best_fit_by_preference
```

---

##### 8. `generate_research_brief`

Purpose:

Generates an analyst-style research brief based on computed data.

Input:

```json
{
  "ticker": "MSFT",
  "mode": "balanced"
}
```

Output:

```text
research_brief
key_strengths
main_risks
sector_context
next_research_questions
disclaimer
```

The brief must clearly state that it is for further research only and not financial advice.

---

### 6.4 Analytics Engine

The Analytics Engine is the core calculation layer.

It transforms raw market and fundamental data into:

- Features
- Factor scores
- Stock rankings
- Risk explanations
- Sector insights
- Research brief inputs

#### Main Responsibilities

##### 1. Universe Filtering

Applies universe-specific filters.

Examples:

```text
minimum price
minimum market cap
minimum average volume
sector filter
data quality filter
```

##### 2. Data Standardization

Converts different data sources into one consistent schema.

Standard stock-level schema:

```text
ticker
company_name
sector
industry
exchange
market_cap
price
volume
avg_volume
return_1d
return_5d
return_1m
return_3m
return_6m
volatility_20d
volatility_60d
max_drawdown
ma_20
ma_50
ma_gap
pe_ratio
forward_pe
profit_margin
revenue_growth
roe
debt_to_equity
beta
quality_score
valuation_score
momentum_score
risk_score
sector_strength_score
final_score
data_quality_score
```

##### 3. Feature Engineering

Market features:

```text
1D return
5D return
1M return
3M return
6M return
20D volatility
60D volatility
maximum drawdown
moving average gap
volume trend
relative strength versus benchmark
```

Fundamental features:

```text
PE ratio
forward PE
price-to-sales
profit margin
revenue growth
ROE
debt-to-equity
free cash flow
beta
```

Sector features:

```text
sector average return
sector momentum
sector ranking
sector relative strength
```

Risk features:

```text
volatility
drawdown
beta
liquidity
valuation risk
data quality risk
```

##### 4. Factor Scoring

Core factor scores:

```text
Momentum Score
Quality Score
Valuation Score
Risk Score
Sector Strength Score
```

Each score should be normalized to a consistent scale, for example:

```text
0 to 100
```

Recommended approach:

- Use percentile ranking within the selected universe.
- Higher is better for positive factors.
- Reverse the percentile for risk metrics where lower risk is better.
- Penalize missing or unreliable data through `data_quality_score`.

##### 5. Preference-Aware Dynamic Weighting

This is a core feature of the project.

The system should not use one fixed formula for every user.

Instead, it should adjust factor weights based on the user's investment preference.

Supported screening modes:

```text
balanced
growth
value
low_risk
high_opportunity
```

Initial mode weights:

| Factor | Balanced | Growth | Value | Low-Risk | High-Opportunity |
|---|---:|---:|---:|---:|---:|
| Momentum | 0.25 | 0.35 | 0.10 | 0.15 | 0.35 |
| Quality | 0.25 | 0.25 | 0.25 | 0.25 | 0.15 |
| Valuation | 0.20 | 0.10 | 0.35 | 0.15 | 0.10 |
| Risk | 0.15 | 0.10 | 0.20 | 0.35 | 0.15 |
| Sector Strength | 0.15 | 0.20 | 0.10 | 0.10 | 0.25 |

Final score:

```text
Final Score =
Momentum Score × Momentum Weight
+ Quality Score × Quality Weight
+ Valuation Score × Valuation Weight
+ Risk Score × Risk Weight
+ Sector Strength Score × Sector Strength Weight
```

##### 6. Explanation Generation

The Analytics Engine should produce structured explanation inputs.

Example:

```text
Main strengths:
- Strong 3-month momentum
- Above-average profitability
- Strong sector relative performance

Main risks:
- Valuation above sector median
- Higher-than-average volatility
- Recent drawdown risk
```

The AI Agent can then convert these structured explanations into natural language.

---

## 7. Universe Configuration

Universe definitions should be stored in a config file, such as:

```yaml
universes:
  sp500:
    description: "Large-cap U.S. stocks with high liquidity and better data quality"
    enabled: true
    min_price: 5
    min_market_cap: null
    min_avg_volume: 500000
    allow_missing_fundamentals: false

  custom:
    description: "User-provided ticker list"
    enabled: true
    min_price: 5
    min_market_cap: null
    min_avg_volume: null
    allow_missing_fundamentals: true

  nasdaq100:
    description: "Large-cap growth-oriented Nasdaq stocks"
    enabled: false
    min_price: 5
    min_market_cap: null
    min_avg_volume: 500000
    allow_missing_fundamentals: false

  russell1000:
    description: "Broader U.S. large and mid-cap equity universe"
    enabled: false
    min_price: 5
    min_market_cap: 1000000000
    min_avg_volume: 300000
    allow_missing_fundamentals: true

  small_cap_opportunity:
    description: "Higher-risk small-cap opportunity universe"
    enabled: false
    min_price: 5
    min_market_cap: 300000000
    min_avg_volume: 500000
    allow_missing_fundamentals: true
```

The initial project only needs to implement:

```text
sp500
custom
```

Other universes can remain as future extensions.

---

## 8. Screening Mode Configuration

Screening modes should also be configurable.

Example:

```yaml
screening_modes:
  balanced:
    description: "General-purpose stock screening with balanced factor weights"
    weights:
      momentum: 0.25
      quality: 0.25
      valuation: 0.20
      risk: 0.15
      sector_strength: 0.15

  growth:
    description: "Focuses on momentum, revenue growth, and sector strength"
    weights:
      momentum: 0.35
      quality: 0.25
      valuation: 0.10
      risk: 0.10
      sector_strength: 0.20

  value:
    description: "Focuses on valuation, profitability, and financial quality"
    weights:
      momentum: 0.10
      quality: 0.25
      valuation: 0.35
      risk: 0.20
      sector_strength: 0.10

  low_risk:
    description: "Focuses on lower volatility, lower drawdown, and stable quality"
    weights:
      momentum: 0.15
      quality: 0.25
      valuation: 0.15
      risk: 0.35
      sector_strength: 0.10

  high_opportunity:
    description: "Focuses on momentum, sector tailwinds, and opportunity signals with risk controls"
    weights:
      momentum: 0.35
      quality: 0.15
      valuation: 0.10
      risk: 0.15
      sector_strength: 0.25
```

---

## 9. Data Sources

### Initial Data Sources

Validated for the prototype after the 2026-07-11 feasibility test:

```text
Wikipedia S&P 500 constituents table: universe, company, GICS sector, industry, CIK
Twelve Data API: adjusted latest-available daily OHLCV
SEC EDGAR Company Facts: filing-based annual accounting fundamentals
Local CSV / Parquet / JSON cache: reproducible analysis and rate-limit protection
```

Nasdaq website capture was rejected after reviewing its legal terms. Yahoo Finance returned HTTP 429 and Stooq returned browser verification. These sources are not MVP dependencies.

### Data Types

Required:

```text
ticker list
company name
sector
industry
historical daily prices
latest price
volume
basic fundamental metrics
```

Data claims and fields must match source capabilities:

```text
Use "latest available daily data," not real-time data.
Show the market-data date and fundamental filing period.
Calculate beta from stock and SPY returns.
Request Twelve Data daily prices with `adjust=all` and record the adjustment mode.
Defer forward PE and analyst estimates until a reliable source is selected.
Use sector-relative, missing-aware accounting scores.
```

Optional:

```text
recent news headlines
news sentiment
analyst rating changes
earnings calendar
```

### Notes

The system should use local caching to reduce repeated requests.

Recommended local files:

```text
data/raw/sp500_universe.csv
data/cache/twelve_data/*.json
data/cache/sec/*.json
data/processed/data_feasibility_market_prices.parquet
data/processed/data_feasibility_unified_features.parquet
data/processed/rankings.csv
outputs/data_feasibility/data_quality_report.md
```

---

## 10. Important Scope Decisions

### In Scope

The project includes:

```text
market analysis
stock screening
factor scoring
preference-aware ranking
sector analysis
risk explanation
MCP tool-calling
AI-generated research brief
Streamlit dashboard
```

### Out of Scope

The project does not include:

```text
stock price prediction
automated trading
portfolio optimization
order execution
financial advice
guaranteed return generation
tick-level real-time trading data
```

Use this wording:

```text
The system is designed as a decision-support and research-assistance tool, not as an automated trading system or financial advisory service.
```

---

## 11. Recommended Repository Structure

```text
equity-screening-agent/
│
├── app/
│   ├── streamlit_app.py
│   └── pages/
│       ├── 1_market_overview.py
│       ├── 2_stock_screener.py
│       ├── 3_stock_detail.py
│       └── 4_agent_chat.py
│
├── config/
│   ├── universes.yaml
│   ├── screening_modes.yaml
│   ├── data_sources.yaml
│   └── data_contract.yaml
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── cache/
│
├── src/
│   ├── __init__.py
│   ├── universe.py
│   ├── market_data.py
│   ├── twelve_data.py
│   ├── fundamentals.py
│   ├── features.py
│   ├── market_coverage.py
│   ├── sec_coverage.py
│   ├── unified_data.py
│   ├── scoring.py
│   ├── screening.py
│   ├── sector_analysis.py
│   ├── explanations.py
│   ├── report_generation.py
│   └── utils.py
│
├── mcp_servers/
│   ├── __init__.py
│   ├── universe_server.py
│   ├── market_server.py
│   ├── fundamentals_server.py
│   ├── screening_server.py
│   └── report_server.py
│
├── agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── intent_parser.py
│   └── prompts.py
│
├── notebooks/
│   └── 01_data_feasibility.ipynb
│
├── outputs/
│   ├── pre_model_validation/
│   ├── rankings/
│   ├── reports/
│   └── screenshots/
│
├── tests/
│   ├── test_universe.py
│   ├── test_features.py
│   ├── test_scoring.py
│   └── test_screening.py
│
├── requirements.txt
├── DATA_QUALITY_POLICY.md
├── README.md
└── PROJECT_SPEC.md
```

---

## 12. Development Roadmap

### Phase 1: Project Setup

Goal:

Set up project structure and define the core scope.

Tasks:

- Create GitHub repository
- Create folder structure
- Create config files
- Install dependencies
- Define universe schema
- Define screening mode schema
- Confirm project does not include price prediction

Deliverable:

```text
Working repo skeleton
Config files
Initial README
```

---

### Phase 2: Data Pipeline

Goal:

Collect and cache stock universe, price data, and fundamental data.

Tasks:

- Implement `get_stock_universe(universe)`
- Implement S&P 500 universe loader
- Implement custom ticker list support
- Fetch historical price data
- Fetch latest price data
- Fetch basic fundamentals
- Save data locally
- Handle missing data

Deliverable:

```text
S&P 500 ticker list
Historical price data
Fundamental metrics
Cached data files
```

---

### Phase 3: Analytics Engine

Goal:

Convert raw data into features and factor scores.

Tasks:

- Calculate returns
- Calculate volatility
- Calculate drawdown
- Calculate moving average gap
- Calculate volume trend
- Calculate quality score
- Calculate valuation score
- Calculate risk score
- Calculate sector strength score
- Normalize scores from 0 to 100

Deliverable:

```text
Feature table
Factor score table
Sector summary table
```

---

### Phase 4: Preference-Aware Screening

Goal:

Rank stocks based on user preference.

Tasks:

- Load screening mode weights
- Implement dynamic weighting
- Implement final score calculation
- Implement `screen_stocks(universe, mode, filters, top_n)`
- Add sector filter
- Add minimum price, market cap, and volume filters
- Generate ranking result

Deliverable:

```text
Personalized stock ranking table
Balanced / Growth / Value / Low-Risk modes
```

---

### Phase 5: Explanation and Research Brief Inputs

Goal:

Make screening results explainable.

Tasks:

- Identify main strengths for each stock
- Identify main risks for each stock
- Generate score breakdown
- Generate structured explanation fields
- Prepare inputs for research brief generation

Deliverable:

```text
Ranking table with explanations
Stock-level score breakdown
Risk notes
```

---

### Phase 6: MCP Tool Layer

Goal:

Expose system capabilities as MCP tools.

Tasks:

- Implement `get_stock_universe`
- Implement `get_market_overview`
- Implement `get_market_data`
- Implement `get_fundamental_data`
- Implement `screen_stocks`
- Implement `get_stock_detail`
- Implement `compare_stocks`
- Implement `generate_research_brief`
- Test each MCP tool independently

Deliverable:

```text
Working MCP tools
Agent-callable financial analytics functions
```

---

### Phase 7: AI Agent Layer

Goal:

Allow natural language interaction.

Tasks:

- Implement intent parser
- Map user intent to screening mode
- Map user intent to universe selection
- Let agent call MCP tools
- Generate user-facing responses based on tool outputs
- Prevent unsupported financial advice language

Deliverable:

```text
Agent that can answer screening, comparison, and stock detail queries
```

---

### Phase 8: Streamlit Dashboard

Goal:

Build a user-facing demo application.

Tasks:

- Build Market Overview page
- Build Stock Screener page
- Build Stock Detail page
- Build Agent Chat page
- Add filtering controls
- Add ranking table
- Add factor score visualization
- Add research brief display

Deliverable:

```text
Interactive Streamlit dashboard
```

---

### Phase 9: Testing and Refinement

Goal:

Improve reliability and presentation quality.

Tasks:

- Test all screening modes
- Check missing data handling
- Check ranking reasonableness
- Check agent grounding
- Add disclaimers
- Improve UI
- Add screenshots
- Write README

Deliverable:

```text
Stable demo-ready system
```

---

### Phase 10: Final Report and Presentation

Goal:

Prepare the final academic and portfolio deliverables.

Tasks:

- Write final report
- Explain business problem
- Explain architecture
- Explain MCP design
- Explain analytics methodology
- Show example results
- Discuss limitations
- Discuss future expansion
- Prepare demo screenshots
- Optional: record demo video

Deliverable:

```text
Final paper/report
Demo screenshots
GitHub README
Portfolio-ready project
```

---

## 13. Suggested Implementation Order

The safest implementation order is:

```text
1. Data feasibility and provider validation
2. Full-universe market coverage test
3. Sector-level SEC fundamental coverage test
4. Unified data contract and quality rules
5. Sector-relative, missing-aware factor scoring
6. Preference-aware ranking and explanations
7. Minimal Streamlit screener and stock detail views
8. MCP tools over stable analytical functions
9. AI Agent and research brief generation
10. Final report
```

Important rule:

```text
Build the analytical core first, then let the AI Agent call it.
```

Do not build a chatbot before the stock screening logic works.

---

## 14. Example User Flow

User asks:

```text
Find lower-risk stocks with strong fundamentals.
```

System process:

```text
1. Agent detects preference: low_risk + quality
2. Agent selects default universe: sp500
3. Agent calls screen_stocks(universe="sp500", mode="low_risk")
4. Analytics Engine calculates factor scores
5. Screening Tool returns top-ranked stocks
6. Agent explains why the stocks rank highly
7. Report Tool generates brief research notes
```

Output example:

```text
Top stocks for further research under Low-Risk Mode:

1. MSFT
2. COST
3. JNJ
4. PG
5. AAPL

MSFT ranks highly because it combines strong profitability, relatively stable price behavior, lower drawdown compared with other technology stocks, and strong sector positioning. However, valuation remains above the market average, so further research should evaluate whether future earnings growth justifies the premium.
```

---

## 15. Research Brief Template

Each stock research brief should include:

```text
Ticker:
Company:
Sector:
Screening Mode:
Rank:
Final Score:

Why it appears in the screen:
Key strengths:
Main risks:
Sector context:
Score breakdown:
Suggested next research questions:
Disclaimer:
```

Example disclaimer:

```text
This output is generated for educational and research purposes only. It is not financial advice, investment advice, or a recommendation to buy or sell any security.
```

---

## 16. Success Criteria

The project is successful if:

- The system can screen the S&P 500 universe.
- The system supports multiple screening modes.
- The system adjusts rankings based on user preference.
- The system produces explainable factor scores.
- The system can generate stock-level research briefs.
- The system uses MCP tools for core functions.
- The system provides a usable dashboard or chat interface.
- The project is clearly positioned as decision support, not stock prediction.

---

## 17. Resume Description

Suggested resume bullet:

```text
Built an MCP-based AI equity screening agent using Python, market data APIs, factor scoring, and Streamlit to rank U.S. equities based on user investment preferences and generate analyst-style research briefs for further investment research.
```

More technical version:

```text
Developed a universe-agnostic, preference-aware stock screening system with MCP tool-calling, dynamic factor weighting, sector analysis, risk scoring, and AI-generated research summaries for S&P 500 equities.
```

---

## 18. Final Scope Recommendation

For the two-month project, the recommended final scope is:

### Must Have

```text
S&P 500 universe
Custom ticker list support
Market data pipeline
Fundamental data pipeline
Analytics Engine
Preference-aware screening
Multiple screening modes
Ranking table
Score breakdown
Research brief generation
Streamlit dashboard
MCP tools
```

### Should Have

```text
Agent chat interface
Stock comparison
Sector overview
Market overview
Data caching
Basic risk notes
```

### Nice to Have

```text
Nasdaq 100 universe
Russell 1000 universe
Small-cap opportunity universe
News sentiment
Advanced visualizations
Demo video
```

The key is to implement the system as extensible from the beginning, while only fully enabling the most reliable universe first.

---

## 19. Final Positioning Statement

This project should be presented as:

```text
An AI Agent-Assisted U.S. Equity Screening System that uses MCP tools, current market data, fundamental metrics, sector trends, risk analysis, and preference-aware scoring to help users identify stocks worth further research.
```

It should not be presented as:

```text
A stock price prediction model
A trading bot
A financial advisor
A guaranteed return system
```
