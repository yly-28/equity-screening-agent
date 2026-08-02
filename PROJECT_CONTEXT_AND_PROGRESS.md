# Project Context and Progress

Last updated: 2026-08-02

## 1. Current Outcome

The repository now implements the intended compact product:

> Enter a ticker or factor constraints, then receive a concise, auditable equity research view.

Phase 6 is complete for this scope. The post-Phase-6
`agent/ai-report-upgrade` branch adds an evidence-cited AI brief refinement
without changing accepted data, factors, scores, or rankings.

| Area | Current state |
|---|---|
| Runtime | Python 3.12.7, pip 26.2, `pip check` clean |
| Accepted feature run | `2026-07-13_sp500_v1_0_0` |
| Accepted scoring run | `2026-07-13_sp500_scores_v1_0_2` |
| Scored matrix SHA-256 | `32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81` |
| Frozen contracts | Data `1.0.0`, scoring `1.0.2`, factor model `1.0.0`, modes `1.0.0` |
| Product UI | Analyze Ticker, Screen Stocks, Compare Stocks, Market / Sector |
| MCP | Five identical stdio and authenticated localhost HTTP tools |
| Online behavior | Explicit quote/identity refresh; quote never enters factor scoring |
| AI behavior | Optional hybrid 200–300-character English brief: model-authored fundamental/factor views plus locally rendered conditional outlook and stance |
| Trading | Not implemented |
| Tests | `508 passed in 21.57s` |

All processed accepted artifacts and provider caches remain ignored and must be preserved.

## 2. Product Boundaries

The project is a research-support system. It is not:

- a validated numeric price-prediction model;
- a personalized financial adviser;
- a personalized or execution-linked buy/sell recommendation engine;
- a broker or order-execution system;
- a tick-level real-time data product;
- a current cross-sectional score unless a new accepted snapshot is built and validated.

Latest provider quotes are an explicit display overlay. They never modify the frozen accepted score, factor weights, eligibility, reason codes, or rank.

The permanent disclaimer remains:

> This output is generated for educational and research purposes only. It is not financial advice, investment advice, or a recommendation to buy or sell any security.

## 3. Phase History and Preserved Contracts

### Phase 1 — provider feasibility

- 503/503 current S&P 500 securities were retrieved from Twelve Data.
- 499/503, or 99.20%, passed the market usability gate.
- SEC Company Facts extraction passed for a stratified 88-security, 11-sector sample.

### Phase 2 — frozen feature matrix

- Contract: `config/data_contract.yaml`, version `1.0.0`, `frozen_v1`.
- Accepted run: `data/processed/2026-07-13_sp500_v1_0_0/`.
- As-of date: `2026-07-13`.
- Rows: 503 retained, 499 eligible.
- Explicit ineligible rows: `ECHO`, `FDXF`, `HONA`, `Q`.
- Accepted run had zero provider errors, zero market network batches, and no metric-period or stale-non-null violations.

### Phase 3 — frozen factors and scores

- Factor model: `config/factor_model.yaml`, version `1.0.0`, `frozen_v1`.
- Screening modes: `config/screening_modes.yaml`, version `1.0.0`, `frozen_v1`.
- Scoring contract: `config/scoring_contract.yaml`, version `1.0.2`.
- Accepted run: `data/processed/2026-07-13_sp500_scores_v1_0_2/`.
- Scored matrix SHA-256: `32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81`.
- Ranking eligibility: 499 Balanced, Growth, and Low Risk; 435 Value.
- Quality is unavailable only for `PSKY`; Valuation is unavailable for 64 otherwise eligible rows.
- The accepted loader independently verifies input identity, hashes, configuration, quality, provenance, row accounting, and ranking state.

The five frozen factors remain Momentum, Quality, Valuation, Risk, and Sector Strength. A higher Risk score means lower measured risk.

### Phase 4 — screening service

`src.screening.screen_stocks` remains the authority for ticker normalization, accepted-run loading, eligibility, filtering, ordering, rank, exclusions, warnings, evidence, dates, and terminology.

Phase 6 adds optional minimums for the five stored factor scores:

```python
minimum_factor_scores={"quality": 60.0, "risk": 55.0}
```

Each threshold must be finite and between 0 and 100. Missing active factor values are explicitly excluded. Filtering never rescales scores or fits a new reference distribution.

### Phase 5 — application services and UI

The complete `src.stock_detail.get_stock_detail` service is preserved. It remains the low-level accepted-evidence audit interface and is exposed through MCP.

The visible Streamlit product was simplified. The former independent long-form Stock Detail page and per-result screener detail expanders were removed from navigation. The default product flow is now a concise ticker analysis, while complete audit evidence remains available through the preserved service.

### Phase 6 — research workspace, MCP, online overlay, and HTTP

The current Phase 6 expansion adds:

- minimum stored-factor filters in `src.screening`;
- deterministic concise reports in `src.research_report`;
- requested-order comparison in `src.comparison`;
- accepted market/sector aggregation in `src.overview`;
- normalized Twelve Data quote/profile boundaries in `src.twelve_data`;
- official SEC ticker identity resolution in `src.security_identity`;
- a unified accepted/live ticker boundary in `src.live_analysis`;
- optional OpenAI synthesis over cited accepted factor, market, fundamental, date, and quality evidence in `src.ai_report`;
- one five-tool stdio MCP server in `mcp_servers/equity_screening.py`;
- one authenticated localhost Streamable HTTP entry point in `mcp_servers/http_app.py`;
- one streamlined four-task Streamlit workspace in `app/stock_screener.py`.

No provider logic, factor fitting, scoring, arbitrary Parquet access, or LLM prompt logic was moved into the MCP adapter.

## 4. Current Service Contracts

### `screen_stocks`

Inputs:

- `universe`
- `custom_tickers`
- `mode`
- `sectors`
- `minimum_price`
- `minimum_market_cap_proxy`
- `minimum_average_volume_20d`
- `minimum_factor_scores`
- `top_n`

The service returns accepted-run identity, filters, warnings, unknown tickers, ranked rows, exclusions, reason codes, dates, factor scores, effective weights, and evidence. Order is the stored selected-mode score descending with the existing deterministic tie-break.

### `get_stock_detail`

Inputs: `ticker`, `mode`.

Returns complete accepted-snapshot identity, selected-mode score and weights, factor/component evidence, market and filing-based fundamentals, dates, quality, strengths, risks, and research questions.

### `get_research_report`

Inputs: `ticker`, `mode`.

Returns schema `1.1.0`, a concise projection of Stock Detail. Posture is one of `strong`, `mixed`, `weak`, or `insufficient_evidence` and means fit with the selected screening mode, not a trade instruction. Its additive `analysis_evidence` schema `1.0.0` projects three market-snapshot fields, eight market signals, and nine fundamental metrics in fixed order. Values, nulls, units, dates, source tags, and warnings are deep-copied without recomputation.

### `analyze_ticker`

Public signature:

```python
analyze_ticker(ticker, mode="balanced", refresh=False)
```

Accepted ticker:

- `refresh=False` is completely local.
- `refresh=True` fetches only a latest quote.
- The quote must carry `scoring_use=display_only_not_used_for_factor_scoring`.
- Accepted scores, factor values, eligibility, and report evidence remain unchanged.

Outside ticker:

- `refresh=False` forces all provider clients into cache-only mode.
- An identity cache miss raises a clear `online_refresh_required` data error.
- `refresh=True` refreshes SEC identity, latest quote, and an optional profile.
- SEC identity supplies ticker, company name, CIK, and exchange, not project GICS.
- Twelve Data provider sector/industry stays under explicit provider taxonomy fields and is never promoted to canonical project GICS.
- Without trusted GICS and a validated reference row, all five factor scores, selected score, and rank stay null.
- Quote/profile failure returns partial evidence plus a provider error and warning.

### `compare_stocks`

Inputs: two to five unique `tickers`, plus `mode`.

The service preserves requested order and stored values. Unknown tickers remain in their requested position. It does not rescore, rescale, or rerank.

### `get_market_overview`

Inputs: `mode`, optional `sectors`.

The service loads only the verified accepted scored matrix and returns equal-security metric coverage, medians, return breadth, eligibility counts, data-date ranges, and alphabetical sector summaries. It is not a live, forecast, or capitalization-weighted market index.

### `render_ai_research_report`

Input: a normalized accepted `get_research_report` result.

The official OpenAI Responses API structured-output call returns internal AI draft schema `5.0.0`. The model authors one 50–74-character cited English fundamental claim and one factor claim, selects a general stance (`Buy-leaning`, `Hold/watch`, `Sell-leaning`, or `Insufficient evidence`), a qualitative 6–12 month outlook, confidence, and one `conditional_driver_evidence_id` from an explicit list of available accepted evidence.

Local validation requires factor and risk/quality evidence plus a fundamental citation whenever a non-null fundamental metric is available. Each model-cited item must be named with its canonical English topic, and numeric/date facts are bound to the matching cited topic within the same clause. It rejects non-English claims, out-of-schema output, guaranteed returns, targets, personalized wording, position sizing, execution language, reversed Risk semantics, common unsupported-company assertions, unknown/duplicate claim IDs, and non-conservative output for an ineligible report.

The application does not ask the model to write conditional-outlook or stance prose. It renders the condition locally from an allowed non-null evidence ID and outlook enum, using an improvement condition so weak current evidence is not recast as positive support. Unknown driver IDs are deterministically replaced with the first available accepted driver. It renders the stance locally from the accepted date plus a consistency-checked stance, outlook, confidence, and accepted posture; conflicting direction pairs become `Hold/watch` without discarding otherwise valid model analysis. This guarantees a cited, two-sided, qualitative English scenario without interpreting model wording through brittle regular expressions. The final public brief still has four 50–74-character sections and one 200–300-character paragraph. Per-section provenance is `openai` for fundamental/factor analysis and `local_structured_render` for conditional outlook/research stance.

Model-authored prose must be single-line plain text. Local checks reject URLs and bare domains, Markdown/HTML, control and Unicode formatting characters, claimed live/provider/intraday quote evidence, uncited canonical or generic fundamental topics, spelled numeric-return forecasts, guaranteed outcomes, and direct buy/sell/trade/entry/position/stake wording. Direction checks associate each cited topic with its nearest directional wording and interpret direct negation, which permits correctly grounded mixed-direction metrics without accepting a distant contradiction. Quality direction is checked against actual missing inputs, warnings, stale metrics, exclusions, and scoring eligibility; clean quality is not counted as limitation evidence. Risk-score relationships must state the frozen higher-score/lower-measured-risk semantics, and model-authored sections cannot restate the locally controlled outlook or confidence level. Fundamental availability is determined from normalized non-null metric values, not by searching rendered warning text for the word `unavailable`.

Missing keys, SDK/API errors, refusals, or invalid output return the same schema with a deterministic 200–300-character English fallback and safe reason code. A rejected model response also returns a non-sensitive validation category for accurate UI diagnostics; model text, exception details, tracebacks, and credentials are not exposed. Deprecated Phase 6 plan classes remain importable but are not used for current requests.

Default model: `OPENAI_MODEL` or `gpt-5.6-sol`. The request uses medium reasoning effort, low text verbosity, a strict Pydantic schema, a `2000` total output-token ceiling, a 45-second client timeout, zero automatic retries, and `store=False`. The display-only live quote and real-time news are not included.

Refresh and AI can be enabled together. The accepted report passed to OpenAI is identical whether refresh is on or off; the provider quote remains a separate display-only field and is not included in the request.

The deterministic fallback was exhaustively rescanned across all `503 × 4 = 2,012` accepted ticker/mode combinations. All succeeded; English output length ranged from 232 to 266 characters including spaces.

## 5. Streamlit Product

Launch:

```bash
.venv/bin/python -m streamlit run app/stock_screener.py
```

Visible tasks:

1. `Analyze Ticker` — default, concise accepted/live result.
2. `Screen Stocks` — accepted factor and proxy filters.
3. `Compare Stocks` — two-to-five requested-order comparison.
4. `Market / Sector` — accepted equal-security summaries.

The UI performs only form mapping and rendering. Service tests verify that it does not directly load accepted artifacts, read Parquet, score, normalize, filter, or rerank.

Streamlit telemetry remains disabled in `.streamlit/config.toml`.

## 6. MCP and HTTP

### Canonical five tools

| Tool | Input schema |
|---|---|
| `screen_stocks` | `universe`, `custom_tickers`, `mode`, `sectors`, `minimum_price`, `minimum_market_cap_proxy`, `minimum_average_volume_20d`, `minimum_factor_scores`, `top_n` |
| `get_stock_detail` | `ticker`, `mode` |
| `analyze_ticker` | `ticker`, `mode`, `refresh` |
| `compare_stocks` | `tickers`, `mode` |
| `get_market_overview` | `mode`, `sectors` |

`mcp_servers.equity_screening.register_tools` is the one registration source for stdio and HTTP. Tool order and schemas cannot drift through separate manual registration. The `refresh` field is a strict JSON boolean; string and numeric lookalikes are rejected before service dispatch and cannot authorize network access.

### stdio launch

```bash
.venv/bin/python -m mcp_servers.equity_screening
```

stdio is a local transport and has no HTTP authentication.

### localhost HTTP launch

```bash
EQUITY_MCP_TOKEN='<random-token-at-least-32-characters>' \
  .venv/bin/python -m mcp_servers.http_app
```

- MCP: `http://127.0.0.1:8000/mcp`
- Public fixed liveness: `http://127.0.0.1:8000/healthz`
- Binding to a non-loopback address is rejected.
- Missing, short, whitespace-containing, or incorrect tokens fail closed.
- Token comparison uses `secrets.compare_digest`.
- Global scope is `equity:read`.
- MCP Host and Origin protections are enabled through the SDK.
- No CORS middleware is installed.
- Health reports only fixed status and server version; it does not verify accepted data, providers, or OpenAI.

The server uses an out-of-band static bearer token and is not an OAuth authorization server. `resource_server_url=None` prevents it from advertising misleading RFC 9728 metadata that points back to itself.

This mode is acceptable only for a local single-user process. It has no token expiry, revocation, user attribution, rotation grace period, IdP, TLS, rate limits, request budgets, or public deployment audit trail.

### Protocol smoke

The stdio smoke launches `python -m mcp_servers.equity_screening` as a real subprocess, initializes an MCP session, and discovers exactly the five tools above.

The authenticated Streamable HTTP smoke initializes protocol version `2026-07-28`, discovers the same five tools, verifies identical input and output schemas, and performs an authenticated tool call whose response preserves JSON nulls and warnings.

## 7. Provider and Online Smoke

Provider logic remains in normalized boundaries, not UI or MCP.

### Twelve Data

`TwelveDataClient.latest_quote` returns a versioned JSON-compatible schema with ticker, timestamps, price fields, market-open state, retrieval timestamp, and the required display-only scoring marker.

`TwelveDataClient.company_profile` keeps provider sector and industry under `provider_sector` and `provider_industry`. Canonical `sector` and `industry` remain null until an approved mapping exists.

Both endpoints are cache-aware, validate cached identity, reject malformed payloads, redact the configured API key in provider messages, and never expose provider JSON directly as an application result.

### SEC identity

`SecTickerResolver` reads the official SEC company-ticker association dataset and returns normalized ticker, company name, ten-digit CIK, exchange, retrieval timestamp, and explicit missing-classification warnings. Online refresh requires `SEC_USER_AGENT`.

### Controlled real calls on 2026-07-31

- `AAPL`, Balanced, refresh true: accepted score stayed `69.72731242719172`; latest quote succeeded with no provider error and was marked display-only.
- `RDDT`, Growth, refresh true: SEC identity and quote succeeded; `data_scope=live_unscored`, `analysis_status=insufficient_evidence`, score and rank null. `/profile` returned HTTP 403 for the configured tier and was retained as a non-fatal provider warning.

No secret value was printed. Caches created by these calls are ignored and intentionally preserved.

## 8. Environment and Dependencies

The repository `.venv` was rebuilt with `/opt/anaconda3/bin/python3.12`.

Verified:

```text
Python 3.12.7
pip 26.2
No broken requirements found.
```

The previous Python 3.9 environment was moved outside the repository to:

```text
/private/tmp/equity-screening-agent-venv-py39-backup-20260731
```

It is a temporary backup, not project state.

New direct pins required by the current scope:

- `mcp==2.0.0`
- `httpx==0.28.1`
- `openai==2.51.0`
- `pydantic==2.13.4`
- `starlette==1.3.1`
- `uvicorn==0.52.0`

FastAPI was evaluated and removed because MCP's own Streamable HTTP ASGI application already provides the required server boundary. `fastapi` and its now-unused `annotated-doc` dependency were uninstalled from `.venv`.

## 9. Test Evidence

All deterministic tests disable or mock network access unless explicitly described as the controlled provider smoke above.

### Provider/live/AI boundaries

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_live_data.py \
  tests/test_security_identity.py \
  tests/test_live_analysis.py \
  tests/test_ai_report.py
```

Coverage includes quote/profile normalization, caches, secret-safe errors, SEC identity, accepted/local behavior, explicit refresh, outside tickers, partial provider failures, missing GICS, JSON nulls, English OpenAI structured prose, one-to-three evidence citations per model claim, clause-level metric/date grounding, all fundamental-null patterns, schema-enforced section and total length bounds, every available driver/outlook template, locally normalized general stances, direct-trade language rejection, bounded client behavior, safe categorized fallback, simultaneous Refresh+AI behavior, and network prohibition.

Current result: `207 passed in 1.77s`.

### MCP and HTTP boundaries

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_mcp_server.py \
  tests/test_mcp_http.py
```

Current result: `48 passed`.

Coverage includes exact five-tool discovery, strict argument validation, direct argument mapping, stable error conversion, stdio subprocess smoke, HTTP protocol negotiation, input/output schema equality, authentication-before-dispatch, token leakage, weak-token rejection, no fake OAuth metadata, Host/Origin rejection, loopback binding, and authenticated tool calls. Non-boolean refresh lookalikes are rejected with zero service dispatch.

### Streamlit workspace boundaries

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_stock_screener_app.py \
  tests/test_stock_detail_app.py
```

Current result: `26 passed in 3.26s`.

### Combined Phase 4/5/6 boundary

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

Current result: `359 passed in 5.85s`.

### Complete suite

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Current result: `508 passed in 21.57s`.

## 10. Git and GitHub State

State verified before the Phase 6 expansion:

- Phase 5 branch: `agent/phase-5-streamlit-screener`.
- Phase 5 implementation commit: `1bd93489a8a2be2d5166b829f7edfd376205310c`.
- Phase 5 published branch head: `841bf7bea62120bc7edccbb05dc6648282b6f8e1`.
- Former remote/main baseline: `2dbc4301caa0dd64ea5ce4efaee5af380f71fe5c`.
- PR #1 was merged.
- The former Phase 4 branch had been deleted locally and remotely.
- No Phase 5 pull request existed.

With explicit user authorization in the preceding task, Phase 5 was merged locally into `main` at merge commit:

```text
1e2f7a9f988a52b1cccde3cccc75bc3abcedf4e6
```

Phase 6 was then created from that organized local main, so it was not stacked directly on an unmerged Phase 5 branch. Its development branch was:

```text
agent/phase-6-mcp
```

The publication workflow first synchronized the completed Phase 5 merge to remote `main`, then published Phase 6 through a dedicated pull request. Temporary Phase 5 and Phase 6 branches may be removed only after the merge is verified. Repository history is authoritative for the final pull-request and merge identifiers.

Phase 6 was merged to `main` through PR #2 at:

```text
fe2ea899013fbbe0e6709b95d4683f5f2583f394
```

The AI refinement is isolated on its dedicated publication branch:

```text
agent/ai-report-upgrade
```

It is published separately for review through a Draft PR against `main`. This
publication does not authorize merging the PR or deleting the branch; GitHub is
authoritative for the final commit and pull-request identifiers.

## 11. Operational Limitations

- Accepted factors and rankings remain as-of `2026-07-13` even when a newer quote is shown.
- The project does not refresh fundamental features, refit factors, rescore rows, or create a current reference distribution on demand.
- Outside tickers are not factor-scored until an exact trusted project GICS classification and validated current reference snapshot are available.
- Twelve Data endpoint access, freshness, exchange timing, and credit cost depend on account entitlement. `/profile` was unavailable in the tested tier.
- Provider cache writes are not atomic. The current local single-user mode is supported; concurrent refresh deployment needs atomic replacement or a lock.
- SEC refresh depends on an identifying `SEC_USER_AGENT` and SEC availability.
- The AI renderer requires an accepted deterministic report; it is skipped for live-unscored outside tickers. The model may propose a structured qualitative outlook and general buy/hold-watch/sell research stance, while their displayed wording is rendered locally. It does not receive news, arbitrary web content, forward analyst estimates, management guidance, multi-period raw fundamentals, or the display-only live quote.
- Evidence citations, prompt constraints, and local heuristics reduce unsupported output but cannot prove every qualitative inference. The model can still be wrong; its stance is not a backtested or otherwise validated return forecast.
- A configured `OPENAI_API_KEY` enables an explicit live call from the Streamlit checkbox. The UI discloses that normalized accepted report evidence is sent to OpenAI, may consume API credits, uses `store=False`, and excludes the display-only live quote. The key was detected without printing it. The former `outlook_mismatch` false rejection is removed structurally by accepting a driver ID and rendering conditional/stance prose locally. Deterministic tests prove Refresh+AI compatibility and never consume API credits. A post-fix external AAPL smoke has not been run because transmitting that accepted evidence to OpenAI requires separate explicit authorization.
- The local HTTP server is not suitable for direct Internet exposure.
- There is no broker, order preview, order submission, portfolio suitability, price target, or personalized trade recommendation. The AI stance is a general snapshot-based research signal, not a suitability determination.
- Market/sector aggregates are equal-security accepted-snapshot descriptions, not forecasts or cap-weighted index results.
- `average_volume_20d` is share volume, not dollar liquidity.
- `market_cap_proxy` is a proxy, not authoritative market capitalization.
- Ignored accepted artifacts and new provider caches must not be removed during Git cleanup.

## 12. Next Assignment

The next assignment should be one of these explicitly approved tracks:

1. **Production HTTP design:** select a real IdP and reverse proxy; add HTTPS, expiring signed/introspected tokens, audience/resource checks, revocation, rate/concurrency/spend limits, and operational logs.
2. **Current accepted snapshot:** build and independently validate a new feature/scoring run before claiming current factor values.
3. **Outside-ticker classification:** approve an exact GICS-compatible source and mapping policy before enabling sector-relative scoring.
4. **Evaluation:** add backtests or forward outcome evaluation before changing posture thresholds or treating the qualitative AI stance as a validated return signal.

Do not start trade execution, personalized buy/sell advice, or a broker integration as an incidental extension of this read-only research product.

## 13. Handoff Checklist

Before future work:

1. Run `git status -sb`, `git log -3 --oneline --decorate`, `git rev-parse HEAD`, and `git branch -a`.
2. Confirm ignored accepted run directories still exist.
3. Confirm `.venv/bin/python --version` is Python 3.12.7 or another supported Python 3.10+ runtime.
4. Run the complete suite and expect `508 passed` unless tests are intentionally added.
5. Preserve all frozen contract files and accepted identities.
6. Preserve provider caches and `.env`; never print secrets.
7. Stop before any commit, push, merge, branch deletion, or pull request unless explicitly authorized.
