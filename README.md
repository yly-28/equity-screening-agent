# Equity Screening Agent

An explainable U.S. equity research workspace built around one simple flow:

> Enter a ticker or factor constraints, then receive a concise, evidence-backed research view.

The project is read-only research software. It is not a validated numeric price-prediction model, personalized financial adviser, trading bot, or order-execution system.

## Current Status

Phase 6 is complete for the current product scope. The post-Phase-6
`agent/ai-report-upgrade` refinement adds a concise, evidence-cited AI research
brief without changing any accepted-data or scoring contract.

- The project virtual environment now uses Python `3.12.7` and pip `26.2`.
- The complete deterministic suite passes: `508 passed`.
- The accepted Phase 2 feature run remains `2026-07-13_sp500_v1_0_0`.
- The accepted Phase 3 scoring run remains `2026-07-13_sp500_scores_v1_0_2`.
- The accepted scored-matrix SHA-256 remains `32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81`.
- Frozen data, scoring, factor-model, and screening-mode contracts are unchanged.
- The Streamlit workspace now defaults to concise ticker analysis and also provides factor screening, requested-order comparison, and accepted market/sector summaries.
- A local stdio MCP server and an authenticated localhost Streamable HTTP MCP server expose the same five read-only tools.
- Online refresh is explicit. A latest quote is display-only and never changes an accepted factor score, eligibility decision, or ranking.
- A ticker outside the accepted run can be resolved and quoted, but remains unscored when a trusted project GICS classification is unavailable.
- Optional OpenAI-assisted report rendering produces one 200–300-character English-language brief. The model authors cited fundamental and factor views and selects a structured outlook, stance, confidence, and accepted-evidence driver; the application renders the conditional outlook and stance wording locally so semantically equivalent model phrasing cannot trigger a false `outlook_mismatch`.
- No trading integration was added.

Phase 5 was organized into `main` at `1e2f7a9`; Phase 6 was merged through PR #2 at `fe2ea89`. The AI-report refinement is published separately from `agent/ai-report-upgrade` for review, while `.env`, provider caches, and accepted processed artifacts remain outside version control.

## Product Surface

Launch the Streamlit workspace:

```bash
.venv/bin/python -m streamlit run app/stock_screener.py
```

The sidebar contains four focused tasks:

1. **Analyze Ticker** — the default. Returns a concise posture, stored factor scores, strengths, limitations, dates, and next questions. An explicit refresh can add a current provider quote or resolve a ticker outside the accepted run. An optional AI-assisted brief analyzes accepted factor and fundamental evidence without changing scores. Refresh and AI may be enabled together; the display-only quote remains outside the AI request.
2. **Screen Stocks** — filters the accepted snapshot by mode, sector, price, market-cap proxy, 20-day average share volume, and minimum stored factor scores.
3. **Compare Stocks** — compares two to five accepted-run securities in the requested order without rescaling or reranking them.
4. **Market / Sector** — reports equal-security medians, coverage, and return breadth for the accepted market snapshot and selected sectors.

The former long, standalone Stock Detail page was removed from navigation. The underlying `src.stock_detail.get_stock_detail` service remains intact and available through MCP for complete audit evidence.

## Setup and Virtual Environment

Create or recreate the supported environment with Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

Verified environment:

```text
Python 3.12.7
pip 26.2
No broken requirements found.
```

The official pinned `mcp==2.0.0` SDK requires Python 3.10 or newer. The former Python 3.9 environment was replaced; its temporary backup is outside the repository and is not part of project state.

Copy the environment template and fill only the capabilities you intend to use:

```bash
cp .env.example .env
```

```text
TWELVE_DATA_API_KEY=...
SEC_USER_AGENT="equity-screening-agent/0.1 Your Name your-email@example.com"
OPENAI_API_KEY=...              # optional
OPENAI_MODEL=gpt-5.6-sol        # optional override; this is the current default
EQUITY_MCP_TOKEN=...            # 32+ characters for localhost HTTP
```

`.env`, provider caches, processed artifacts, and security-level provider data are ignored by Git. Never print or commit secrets.

## Accepted Data and Frozen Scoring

The accepted feature bundle is local and ignored:

```text
data/processed/2026-07-13_sp500_v1_0_0/
```

It contains 503 securities, of which 499 are eligible. The explicit base exclusions remain `ECHO`, `FDXF`, `HONA`, and `Q`.

The accepted score bundle is also local and ignored:

```text
data/processed/2026-07-13_sp500_scores_v1_0_2/
```

All accepted application services load it through `src.scoring_contract.load_accepted_scoring_run`. They do not read arbitrary Parquet files. Identity, hashes, configuration versions, input lineage, quality evidence, and ranking state are verified before use.

The five factors remain:

- Momentum
- Quality
- Valuation
- Risk, where a higher score means lower measured risk
- Sector Strength

`average_volume_20d` means 20-day average share volume, not dollar liquidity. `market_cap_proxy` is price multiplied by validated shares outstanding and is not authoritative market capitalization.

## Online Ticker Analysis

The public service is:

```python
from src.live_analysis import analyze_ticker

result = analyze_ticker("AAPL", mode="balanced", refresh=False)
```

Behavior is deliberately asymmetric:

- Accepted ticker, `refresh=False`: entirely local; returns the frozen accepted report.
- Accepted ticker, `refresh=True`: fetches only a latest quote and preserves every accepted score and eligibility value.
- Outside ticker, `refresh=False`: provider access is forced to cache-only. A cache miss asks for explicit online refresh.
- Outside ticker, `refresh=True`: resolves SEC identity, requests a latest quote, and attempts an optional Twelve Data profile.
- Outside ticker without trusted project GICS: all factor scores, selected score, and rank remain JSON `null`; posture is `insufficient_evidence`.
- Quote or profile failure returns partial evidence plus structured warnings instead of fabricating data.

Controlled online smoke on 2026-07-31:

- `AAPL`: accepted evidence plus a display-only Twelve Data quote; accepted Balanced score remained unchanged and no provider error was returned.
- `RDDT`: SEC identity and latest quote succeeded outside the accepted run; score and rank remained null. The subscription-restricted `/profile` call returned HTTP 403 and was preserved as a non-fatal provider warning.

The project remains a latest-available daily research product, not a tick-level real-time feed. Provider values depend on account entitlement and exchange timing.

## Factor Screening

```python
from src.screening import screen_stocks

result = screen_stocks(
    universe="sp500",
    mode="balanced",
    sectors=["Information Technology"],
    minimum_price=10.0,
    minimum_market_cap_proxy=1_000_000_000.0,
    minimum_average_volume_20d=500_000.0,
    minimum_factor_scores={"quality": 60.0, "risk": 55.0},
    top_n=20,
)
```

Factor minimums filter stored accepted scores in the 0–100 range. The service still sorts only by the stored selected-mode score and ticker tie-break; it never fits transforms or reranks a filtered subset.

## Comparison and Market / Sector Summary

```python
from src.comparison import compare_stocks
from src.overview import get_market_overview

comparison = compare_stocks(["AAPL", "MSFT"], mode="value")
overview = get_market_overview(mode="growth", sectors=["Financials"])
```

Comparison preserves requested ticker order, nulls, eligibility, and unknown-ticker positions. It supports two to five unique tickers.

The overview uses the verified accepted matrix only. Its results are equal-security cross-sectional descriptions, not live market returns, forecasts, or capitalization-weighted index calculations.

## Optional AI Report Rendering

```python
from src.ai_report import render_ai_research_report
from src.research_report import get_research_report

source = get_research_report("AAPL", mode="balanced")
rendered = render_ai_research_report(source)
```

`get_research_report` schema `1.1.0` includes an `analysis_evidence` `1.0.0` block that only projects existing normalized Stock Detail values: three market-snapshot fields, eight market signals, and nine core fundamental metrics. Values, JSON nulls, units, dates, source tags, and warnings are preserved; the report layer does not calculate a new metric or score.

The renderer uses the official OpenAI Responses API structured-output interface. The default model is `OPENAI_MODEL` or `gpt-5.6-sol`. It uses medium reasoning effort, low text verbosity, a strict Pydantic schema, a `2000` total output-token ceiling, a 45-second client timeout, zero automatic retries, and `store=False`. AI response schema `5.0.0` contains:

- a general research stance: `Buy-leaning`, `Hold/watch`, `Sell-leaning`, or `Insufficient evidence`;
- a conditional 6–12 month outlook: `Constructive`, `Neutral`, `Cautious`, or `Uncertain`;
- confidence: `Low`, `Medium`, or `Moderately high`;
- exactly one 50–74-character cited English claim for fundamental analysis and one for factor analysis;
- one accepted `conditional_driver_evidence_id` selected from the request's available evidence IDs;
- no model-authored conditional-outlook or research-stance prose.

The model is prompted to use only supplied evidence and may autonomously infer concise fundamental and factor views. Local validation requires factor and limitation evidence, plus fundamental evidence whenever it is available. Every model-cited item must be named with its canonical English topic, and numeric/date facts are bound to the corresponding cited topic within the same clause. Validation also checks each model-authored claim for English output, length, Risk-score direction, and known unsupported-company, guarantee, personalization, sizing, target, or execution language.

The application then constructs the two-sided 6–12 month condition from an allowed, non-null accepted-evidence ID and the outlook enum. The driver is phrased as an improvement condition, so negative growth or a low factor is not recast as current positive support. An unknown model-selected driver is replaced deterministically with the first available accepted driver. The stance sentence is built from the accepted date plus a locally consistency-checked stance, outlook, confidence, and accepted posture; contradictory buy/cautious, sell/constructive, weak/buy, or strong/sell combinations become `Hold/watch` instead of forcing a whole-report fallback.

The four claims are joined into one 200–300-character paragraph. Output provenance labels the fundamental/factor sections as `openai` and the conditional/stance sections as `local_structured_render`. Model prose must be single-line plain text and cannot introduce URLs or bare domains, Markdown/HTML, Unicode formatting controls, a live/provider/intraday quote, an uncited canonical or generic fundamental topic, spelled numeric-return forecasts, guaranteed outcomes, or direct buy/sell/trade/entry/position/stake language. Direction checks bind each cited topic to its nearest directional wording, including negation, so one sentence may describe two accepted metrics with different directions without a false mismatch. Clean quality cannot be presented as a limitation, actual quality problems cannot be presented as excellent, and Risk wording must preserve the frozen higher-score/lower-measured-risk meaning. Model-authored sections cannot restate the locally controlled outlook or confidence level. This removes the former brittle free-form outlook parser while preserving evidence IDs, qualitative safety, and consistent English output. An ineligible report can only return `Insufficient evidence / Uncertain / Low`.

Missing credentials, SDK/API errors, refusals, or invalid model output return the same response schema with a clearly labeled 200–300-character deterministic fallback. Invalid model output also carries a stable, non-sensitive validation category without exposing model output, an exception, or a traceback. Deterministic, network-disabled tests cover official SDK serialization, multi-evidence claims, clause-level metric binding, per-claim English checks, all locally rendered driver/outlook combinations, structured-driver normalization, general buy/hold-watch/sell stances, safe fallbacks, bounded client behavior, secret handling, JSON preservation, and the simultaneous Refresh+AI UI path. A real live-model call remains an explicit user action because it transmits normalized accepted evidence and consumes API credits. The post-fix external AAPL smoke is pending that explicit data-transmission authorization.

An exhaustive local fallback scan covered all `503 × 4 = 2,012` accepted ticker/mode combinations: `2,012` succeeded, zero failed, and every English brief was 232–266 characters including spaces.

## MCP Servers

### Local stdio

```bash
.venv/bin/python -m mcp_servers.equity_screening
```

### Authenticated localhost HTTP

Generate a cryptographically random bearer token, then launch:

```bash
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

```bash
EQUITY_MCP_TOKEN='<long-random-token>' \
  .venv/bin/python -m mcp_servers.http_app
```

Endpoints:

- MCP Streamable HTTP: `http://127.0.0.1:8000/mcp`
- Public static liveness only: `http://127.0.0.1:8000/healthz`

The HTTP server fails closed without a token, uses constant-time token comparison, requires the `equity:read` scope, rejects non-loopback binding, and relies on MCP Host/Origin protection. It has no CORS configuration.

This is a pre-provisioned localhost bearer-token mode, not OAuth login or a production authorization server. It intentionally publishes no fake OAuth protected-resource metadata. Public deployment requires HTTPS, a real IdP, signed or introspected expiring tokens, audience/resource validation, revocation, rate limits, concurrency/budget controls, and deployment-specific logging. stdio is local and is not protected by HTTP authentication.

### Tool schemas

| Tool | Inputs | Output boundary |
|---|---|---|
| `screen_stocks` | `universe`, `custom_tickers`, `mode`, `sectors`, `minimum_price`, `minimum_market_cap_proxy`, `minimum_average_volume_20d`, `minimum_factor_scores`, `top_n` | Accepted screening schema, original service order and exclusions |
| `get_stock_detail` | `ticker`, `mode` | Complete accepted Stock Detail audit schema |
| `analyze_ticker` | `ticker`, `mode`, `refresh` | Concise accepted report or clearly unscored live evidence |
| `compare_stocks` | `tickers`, `mode` | Two-to-five requested-order accepted comparison |
| `get_market_overview` | `mode`, `sectors` | Accepted market and sector aggregates |

stdio and HTTP call the same `register_tools` function. Protocol discovery over a real stdio subprocess and authenticated Streamable HTTP both returned exactly those five tools with matching input and output schemas. `analyze_ticker.refresh` is a strict JSON boolean; strings and numbers are rejected before service dispatch so they cannot accidentally authorize provider calls.

## Testing

Run the focused online/provider boundaries without network access:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_live_data.py \
  tests/test_security_identity.py \
  tests/test_live_analysis.py \
  tests/test_ai_report.py
```

Latest provider/live/AI boundary result: `207 passed in 1.77s`.

Run the combined Phase 4/5/6 service, UI, MCP, and HTTP boundary:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_screening.py \
  tests/test_stock_detail.py \
  tests/test_research_report.py \
  tests/test_live_analysis.py \
  tests/test_ai_report.py \
  tests/test_comparison.py \
  tests/test_overview.py \
  tests/test_stock_screener_app.py \
  tests/test_stock_detail_app.py \
  tests/test_mcp_server.py \
  tests/test_mcp_http.py
```

Latest combined boundary result: `359 passed in 5.85s`.

Run everything:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Latest complete result: `508 passed in 21.57s` on Python 3.12.7.

## Operational Limitations

- Accepted scores are frozen at as-of date `2026-07-13`; online quotes do not make those scores current.
- No live factor recomputation, refitting, rescoring, or cross-sectional reranking is performed.
- Outside-run tickers remain unscored without trusted project GICS classification and a validated reference snapshot.
- Twelve Data quote/profile availability, freshness, credit cost, and exchange timing depend on the configured subscription. `/profile` was not available under the tested account tier.
- Provider cache writes are not yet atomic. This is acceptable for the current local single-user process, but concurrent refresh deployment needs atomic replace or locking.
- SEC online access requires an identifying `SEC_USER_AGENT`.
- AI rendering is optional and accepted-evidence-only. The model can propose a structured qualitative outlook and non-personalized general buy/hold-watch/sell research stance; the application renders their final wording locally. It does not receive news, forward estimates, management guidance, multi-period raw fundamentals, or the display-only live quote. It cannot refresh scores, provide target prices or position sizing, personalize advice, or issue trade instructions.
- Evidence citations make the output auditable, but prompt constraints and local heuristic checks cannot prove every qualitative inference. The AI can still be wrong, and the stance is not a validated return forecast.
- The HTTP token is suitable only for a local single-user process. There is no production IdP, TLS termination, user attribution, expiry, revocation, rate limit, or audit service.
- There is no broker connection, portfolio optimization, transaction execution, price target, or personalized buy/sell recommendation. The AI stance is a general snapshot-based research signal, not a suitability determination.
- Ignored accepted artifacts and provider caches must be preserved locally.

## Next Assignment

The next useful increment is operational hardening, not more product surface:

1. Decide whether the localhost HTTP server should be deployed. If yes, select a real IdP/reverse-proxy design and add HTTPS, expiring tokens, audience checks, rate and spend limits.
2. Approve a trustworthy exact GICS-compatible classification source before scoring any outside-run ticker.
3. Build and validate a new accepted snapshot before claiming current factor scores.
4. Add outcome/backtest evaluation before changing posture thresholds or treating the qualitative AI stance as a validated return signal.

Do not add trade execution or personalized recommendations without a separate product, security, legal, and broker-integration design.

## Authoritative Documentation

- [`PROJECT_SPEC.md`](PROJECT_SPEC.md) — stable product and analytical requirements.
- [`PROJECT_CONTEXT_AND_PROGRESS.md`](PROJECT_CONTEXT_AND_PROGRESS.md) — detailed implementation, test, Git, and handoff state.

Official implementation references used for this phase include the [MCP Python SDK documentation](https://py.sdk.modelcontextprotocol.io/), [OpenAI latest-model guide](https://developers.openai.com/api/docs/guides/latest-model), [OpenAI Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI reasoning best practices](https://developers.openai.com/api/docs/guides/reasoning-best-practices), [Twelve Data API documentation](https://twelvedata.com/docs), and [SEC developer resources](https://www.sec.gov/about/developer-resources).
