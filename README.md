# Equity Screening Agent

An explainable U.S. equity research workspace built around one simple flow:

> Enter a ticker or factor constraints, then receive a concise, evidence-backed research view.

The project is read-only research software. It is not a price predictor, personalized financial adviser, trading bot, or order-execution system.

## Current Status

Phase 6 is complete for the current product scope.

- The project virtual environment now uses Python `3.12.7` and pip `26.2`.
- The complete deterministic suite passes: `346 passed`.
- The accepted Phase 2 feature run remains `2026-07-13_sp500_v1_0_0`.
- The accepted Phase 3 scoring run remains `2026-07-13_sp500_scores_v1_0_2`.
- The accepted scored-matrix SHA-256 remains `32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81`.
- Frozen data, scoring, factor-model, and screening-mode contracts are unchanged.
- The Streamlit workspace now defaults to concise ticker analysis and also provides factor screening, requested-order comparison, and accepted market/sector summaries.
- A local stdio MCP server and an authenticated localhost Streamable HTTP MCP server expose the same five read-only tools.
- Online refresh is explicit. A latest quote is display-only and never changes an accepted factor score, eligibility decision, or ranking.
- A ticker outside the accepted run can be resolved and quoted, but remains unscored when a trusted project GICS classification is unavailable.
- Optional OpenAI report rendering can only rearrange sentences already present in the deterministic report. It cannot add facts, target prices, or buy/sell instructions.
- No trading integration was added.

Phase 5 was organized into `main` at `1e2f7a9`, and Phase 6 was developed on `agent/phase-6-mcp`. GitHub publication preserves that history while keeping `.env`, provider caches, and accepted processed artifacts outside version control.

## Product Surface

Launch the Streamlit workspace:

```bash
.venv/bin/python -m streamlit run app/stock_screener.py
```

The sidebar contains four focused tasks:

1. **Analyze Ticker** — the default. Returns a concise posture, stored factor scores, strengths, limitations, dates, and next questions. An explicit refresh can add a current provider quote or resolve a ticker outside the accepted run.
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
OPENAI_MODEL=gpt-5.6-terra      # optional override
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

The renderer uses the official OpenAI Responses API structured-output interface. The default model is `OPENAI_MODEL` or `gpt-5.6-terra`.

The model receives normalized accepted evidence and returns only an editorial plan containing a headline style and existing evidence IDs. Final sentences are copied from the deterministic source report. Missing credentials, API errors, refusals, or invalid structured output produce a deterministic fallback without leaking exception details or keys.

No OpenAI key was configured during the final local smoke, so no live model request was made. Sixteen network-disabled AI boundary tests cover the OpenAI and fallback paths with an injected fake client.

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

Latest provider/live/AI boundary result: `51 passed`.

Run the combined Phase 4/5/6 service, UI, MCP, and HTTP boundary:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_screening.py \
  tests/test_stock_detail.py \
  tests/test_research_report.py \
  tests/test_live_analysis.py \
  tests/test_comparison.py \
  tests/test_overview.py \
  tests/test_stock_screener_app.py \
  tests/test_stock_detail_app.py \
  tests/test_mcp_server.py \
  tests/test_mcp_http.py
```

Latest combined boundary result: `181 passed in 4.89s`.

Run everything:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Latest complete result: `346 passed in 20.47s` on Python 3.12.7.

## Operational Limitations

- Accepted scores are frozen at as-of date `2026-07-13`; online quotes do not make those scores current.
- No live factor recomputation, refitting, rescoring, or cross-sectional reranking is performed.
- Outside-run tickers remain unscored without trusted project GICS classification and a validated reference snapshot.
- Twelve Data quote/profile availability, freshness, credit cost, and exchange timing depend on the configured subscription. `/profile` was not available under the tested account tier.
- Provider cache writes are not yet atomic. This is acceptable for the current local single-user process, but concurrent refresh deployment needs atomic replace or locking.
- SEC online access requires an identifying `SEC_USER_AGENT`.
- AI rendering is optional and accepted-evidence-only. It does not generate new investment facts or advice.
- The HTTP token is suitable only for a local single-user process. There is no production IdP, TLS termination, user attribution, expiry, revocation, rate limit, or audit service.
- There is no broker connection, portfolio optimization, transaction execution, price target, or personalized buy/sell recommendation.
- Ignored accepted artifacts and provider caches must be preserved locally.

## Next Assignment

The next useful increment is operational hardening, not more product surface:

1. Decide whether the localhost HTTP server should be deployed. If yes, select a real IdP/reverse-proxy design and add HTTPS, expiring tokens, audience checks, rate and spend limits.
2. Approve a trustworthy exact GICS-compatible classification source before scoring any outside-run ticker.
3. Build and validate a new accepted snapshot before claiming current factor scores.
4. Add outcome/backtest evaluation before changing posture thresholds or presenting stronger investment conclusions.

Do not add trade execution or personalized recommendations without a separate product, security, legal, and broker-integration design.

## Authoritative Documentation

- [`PROJECT_SPEC.md`](PROJECT_SPEC.md) — stable product and analytical requirements.
- [`PROJECT_CONTEXT_AND_PROGRESS.md`](PROJECT_CONTEXT_AND_PROGRESS.md) — detailed implementation, test, Git, and handoff state.

Official implementation references used for this phase include the [MCP Python SDK documentation](https://py.sdk.modelcontextprotocol.io/), [OpenAI Responses and Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs), [Twelve Data API documentation](https://twelvedata.com/docs), and [SEC developer resources](https://www.sec.gov/about/developer-resources).
