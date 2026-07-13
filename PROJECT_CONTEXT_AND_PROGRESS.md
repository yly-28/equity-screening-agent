# Equity Screening Agent: Context, Progress, and Data Policy

Last updated: 2026-07-13 (Asia/Shanghai)

This is the authoritative operational handoff for continuing the repository. It records the live project state, validation evidence, provider decisions, data-quality policy, Git state, and exact next tasks. Stable product requirements are in `PROJECT_SPEC.md`; setup and commands are summarized in `README.md`.

## 1. Executive Status

**Phase 1, data feasibility validation, is complete.**

The project passed the pre-model gate:

| Gate | Evidence | Status |
| --- | --- | --- |
| Universe identity and CIK mapping | 503 securities, 11 GICS sectors | Passed |
| Approved market provider | Documented Twelve Data API with adjusted prices | Passed |
| Cross-sector market sample | 11/11 retrieved and usable | Passed |
| Full market retrieval | 503/503 retrieved | Passed |
| Full market usability | 499/503, or 99.20%; threshold was 95% | Passed |
| SEC sector sample | 88/88 retrieved, eight per sector | Passed |
| SEC core extraction | 88/88 | Passed |
| Data contract and quality rules | Providers, fields, timestamps, missingness, and validity documented | Passed for pipeline work |
| Automated tests | 11/11 passed on 2026-07-13 | Passed |

The active phase is **Phase 2: production feature pipeline**. The next deliverable is a reproducible full-universe model matrix with a machine-readable quality audit.

Do not start factor scoring until that matrix passes. Do not start Streamlit, MCP, the AI agent, or LLM-generated briefs until the analytical core is stable.

## 2. Product Direction Confirmed by Validation

The defensible MVP is an **explainable latest-available daily-data equity research screener**, not a real-time market product.

The validated source stack is:

| Role | Source | Main limitation |
| --- | --- | --- |
| Current S&P 500 identity and CIK | Wikipedia constituents table | Current-universe survivorship bias and possible schema changes |
| Adjusted daily OHLCV | Twelve Data `/time_series`, `adjust=all` | API-key credits and rate windows |
| Benchmark | SPY through Twelve Data | Requires common daily history |
| Annual fundamentals | SEC EDGAR Company Facts | Filing lag and issuer-specific XBRL tags |
| Market-cap proxy | Price times validated SEC shares | Optional because shares coverage is incomplete |
| Beta | Calculated from stock and SPY returns | Depends on sufficient overlapping history |

Required product adjustments:

- Say “latest available daily data,” not “real-time” or “near-real-time.”
- Display market date, fiscal period end, and filing date.
- Use `liabilities_to_equity` as a labeled proxy until debt taxonomy mapping is validated.
- Treat market cap and annual PE as optional derived proxies.
- Defer forward PE, analyst estimates, ratings, targets, news, and sentiment.
- Compare accounting and valuation inputs within sectors.
- Renormalize weights over available and applicable inputs; never score missing values as zero.

## 3. Validation Evidence

### 3.1 Initial 22-Security Field Experiment

The first experiment covered 22 S&P 500 securities across all 11 sectors and established that the planned market and fundamental features could be calculated.

| Probe | Result | Interpretation |
| --- | --- | --- |
| Wikipedia universe | 503 rows with sector, industry, and CIK | Approved |
| Legacy Nasdaq market rows | 22/22 | Historical evidence only; not approved for new requests |
| SEC Company Facts | 22/22 retrieval and core extraction | Approved |
| Yahoo anonymous chart | 0/1, HTTP 429 | Not a runtime dependency |
| Stooq CSV | 0/1, browser verification | Not a runtime dependency |

The legacy sample had complete planned market fields and 19/22 free-cash-flow coverage. It is superseded by the larger approved-provider audits below. Its machine-readable evidence remains under `outputs/data_feasibility/`.

### 3.2 Full Market Audit

Assessment date: 2026-07-13

Data window: approximately 400 calendar days ending 2026-07-13

Latest trading observation: 2026-07-10, which is valid across the preceding weekend under the five-calendar-day rule.

Results:

- 503/503 current S&P 500 securities returned adjusted daily OHLCV.
- 499/503 met every model-usability rule.
- Retrieval success was 100%.
- Usability was 99.20%, above the 95% entry gate.

Four securities remain excluded:

| Ticker | Observation | Handling |
| --- | --- | --- |
| `FDXF` | 31 daily rows | Exclude until at least 180 rows exist |
| `HONA` | 18 daily rows | Exclude until at least 180 rows exist |
| `Q` | 176 daily rows | Exclude until at least 180 rows exist |
| `ECHO` | 70.2% daily move on 2025-08-26 | Exclude until reconciled with a documented corporate action |

The three short-history cases should be reevaluated automatically on each new snapshot. The `ECHO` move may be genuine, but policy requires explanation before scoring.

### 3.3 SEC Stratified Audit

Assessment date: 2026-07-13

Sample: 88 current S&P 500 securities, eight per GICS sector

- SEC retrieval success: 88/88.
- Core extraction success: 88/88.
- Median fundamental age: 194 days.
- Maximum fundamental age: 381 days.

Overall field coverage:

| Field | Available | Missing | Status |
| --- | ---: | ---: | --- |
| Annual revenue | 88/88 | 0.0% | Strong |
| Annual net income | 88/88 | 0.0% | Strong |
| Stockholders' equity | 88/88 | 0.0% | Strong |
| Total assets | 88/88 | 0.0% | Strong |
| Total liabilities | 88/88 | 0.0% | Strong |
| Annual operating cash flow | 88/88 | 0.0% | Strong |
| Annual capex | 80/88 | 9.1% | Strong |
| Annual free cash flow | 80/88 | 9.1% | Strong overall, optional by sector |
| Annual diluted EPS | 87/88 | 1.1% | Strong |
| Shares outstanding | 77/88 | 12.5% | Usable, optional |
| Revenue growth | 88/88 | 0.0% | Strong |
| Profit margin | 88/88 | 0.0% | Strong with outlier review |
| ROE | 86/88 | 2.3% | Strong after equity validity rules |
| Liabilities-to-equity | 86/88 | 2.3% | Strong after equity validity rules |

Material sector gaps, defined as at least 25% missing in the eight-security sector sample:

| Sector | Field | Missing |
| --- | --- | ---: |
| Financials | Annual capex | 25.0% |
| Real Estate | Annual capex | 37.5% |
| Financials | Annual free cash flow | 25.0% |
| Real Estate | Annual free cash flow | 37.5% |
| Communication Services | Shares outstanding | 75.0% |
| Financials | Shares outstanding | 25.0% |

Model implications:

- Free cash flow is optional for Financials, Real Estate, and Utilities.
- Negative or zero equity invalidates ROE and liabilities-to-equity instead of producing extreme scores.
- Profit margins above 100% are flagged and require sector-aware interpretation.
- Shares outstanding must pass freshness and plausibility checks before market-cap or annual-PE proxies are calculated.
- Current-universe SEC coverage supports cross-sectional screening, not a survivorship-bias-free backtest.

## 4. Provider Decision and Usage Rules

### Approved

- Wikipedia current S&P 500 constituents table.
- Twelve Data documented `/time_series` API.
- SEC EDGAR Company Facts.

### Rejected or Deferred

- Do not issue new automated requests to Nasdaq website endpoints. Nasdaq's [legal terms](https://www.nasdaq.com/legal) prohibit automated capture. The old 22-security response is historical evidence only.
- Yahoo Finance and Stooq failed anonymous feasibility probes and are not runtime dependencies.
- No scraped replacement may be introduced merely to fill a weak field.

### Twelve Data Evidence

As observed during validation on 2026-07-11:

- The Basic plan allowed eight symbol credits per minute and 800 per day.
- A clean S&P 500 plus SPY refresh required approximately 504 credits and 63 rate windows.
- Batch requests still charged one credit per symbol.
- The project requests `adjust=all`, records provenance, caches each symbol separately, and resumes after interruption.

Provider pricing and policy may change, so recheck them before a future clean refresh. Do not redistribute raw provider responses.

### SEC Fair Access

- Every request uses a configured identifying `SEC_USER_AGENT`.
- Requests use conservative pacing and local caching.
- Fiscal period and filing date remain attached to derived values.

## 5. Normative Data-Quality Policy

### Freshness

- Daily market data is usable when the latest row is no more than five calendar days old, accommodating weekends and normal U.S. market holidays.
- Annual fundamentals are usable up to 550 days after fiscal period end.
- Stale values remain available for diagnosis but are excluded from current ranking.

### Market Eligibility

A security is eligible only when it has:

- at least 180 daily observations in the validation window;
- no duplicate trading dates;
- no missing OHLCV rows;
- positive OHLC prices;
- no unexplained absolute daily return above 50%;
- a confirmed adjusted-price mode;
- all required market features.

### Fundamental Validity

- Merge XBRL synonyms by fiscal period so a stale tag cannot hide a newer equivalent.
- Calculate ratios only from values aligned to the same fiscal period.
- Set ROE and liabilities-to-equity to null when equity is zero or negative.
- Flag profit margins whose absolute value exceeds 100%; do not compare them blindly across sectors.
- Reject shares outstanding that are missing, below 100,000, or more than 550 days older than the latest fundamental period.
- Treat free cash flow as optional where it is unavailable or economically inappropriate.

### Missing Values and Outliers

- Missing values remain null and are never converted to zero scores.
- Missing required market inputs exclude the security from ranking.
- Missing optional inputs cause factor or mode weights to be renormalized over applicable fields.
- Global-mean imputation is forbidden for scoring.
- Winsorize continuous scoring inputs within sector at the 5th and 95th percentiles after validity rules.
- Require at least 10 valid observations per sector before computing sector percentiles.

### Reproducibility and Bias

- Cache raw network responses locally and exclude them from Git.
- Record provider, retrieval timestamp, as-of date, market-data date, fiscal period, and filing date.
- Keep security-level provider exports local unless redistribution rights are clear.
- The current S&P 500 list creates survivorship bias. The MVP is a current cross-sectional screener.
- Any future historical backtest requires point-in-time constituents and only filings available at each historical date.

### Model-Matrix Gate

Factor scoring may start only after:

1. the full feature matrix satisfies `config/data_contract.yaml`;
2. all required market features are present for eligible rows;
3. fundamental missingness and sector applicability are reported;
4. freshness, outlier, and exclusion flags are summarized;
5. tests pass without an unapproved data source.

## 6. Existing Implementation

### Provider and Feature Modules

- `src/universe.py`: S&P 500 loading, normalization, caching, sectors, and CIK mapping.
- `src/twelve_data.py`: authenticated adjusted daily client, batch support, parsing, and per-symbol cache.
- `src/fundamentals.py`: SEC Company Facts retrieval and normalized annual extraction.
- `src/http_client.py`: shared retry-aware HTTP session.
- `src/features.py`: market feature calculations.
- `src/unified_data.py`: provider-independent row assembly, derived proxies, flags, and schema audit.

### Validation Modules

- `src/market_coverage.py`: resumable market audit and 95% gate.
- `src/sec_coverage.py`: deterministic sector-stratified SEC audit.
- `src/data_feasibility.py`: legacy 22-security evidence; no new Nasdaq requests are permitted.
- `notebooks/01_data_feasibility.ipynb`: Phase 1 exploratory summary.

### Configuration

- `config/data_contract.yaml`: row grain, providers, fields, missingness, and preprocessing.
- `config/data_sources.yaml`: provider configuration.
- `config/universes.yaml`: universe definitions.
- `config/screening_modes.yaml`: provisional balanced, growth, value, and low-risk weights.

### Tests

Eleven tests cover provider parsing, market features, SEC extraction, coverage logic, the data contract, and unified row construction.

Latest result:

```text
11 passed in 0.63s
```

## 7. Machine-Readable Evidence

Long-term documentation is limited to `README.md`, `PROJECT_SPEC.md`, and this file. Validation artifacts remain machine-readable:

- `outputs/pre_model_validation/market_coverage_full_summary.json`;
- local ignored `outputs/pre_model_validation/market_coverage_full.csv`;
- `outputs/pre_model_validation/market_coverage_custom_summary.json`;
- `outputs/pre_model_validation/sec_coverage_summary.json`;
- `outputs/pre_model_validation/sec_field_coverage.csv`;
- `outputs/pre_model_validation/sec_sector_coverage.csv`;
- local ignored `outputs/pre_model_validation/sec_validation_sample.csv`;
- `outputs/data_feasibility/run_summary.json`;
- `outputs/data_feasibility/field_coverage.csv`;
- `outputs/data_feasibility/source_probe.csv`.

## 8. Repository and Git State

Repository: `equity-screening-agent`

Branch: `main`

Latest committed and pushed revision before the current documentation consolidation:

```text
de18b6b feat: establish pre-model data validation pipeline
```

Current local work includes:

- completed full-market and refreshed SEC validation summaries;
- Phase 1 completion updates;
- consolidation of nine Markdown files into three authoritative documents;
- removal of generated Markdown report output in favor of existing JSON/CSV evidence.

Before the next commit:

1. inspect `git status` and the full diff;
2. rerun all tests;
3. confirm `.env` is untracked;
4. confirm caches and security-level provider CSVs remain ignored;
5. commit documentation consolidation and Phase 1 completion together only if the diff is coherent.

## 9. Active Phase: Production Feature Pipeline

### Objective

Build a reproducible, resumable pipeline that creates the full model-ready feature matrix under `config/data_contract.yaml`.

### Required Work

1. Add `src/feature_pipeline.py`; keep orchestration out of notebooks.
2. Load the current universe and cached SPY and security histories.
3. Calculate every required market feature for each security.
4. Fetch and cache SEC Company Facts for the full eligible universe with fair-access pacing.
5. Normalize fundamentals and assemble each row through `build_unified_feature_row`.
6. Persist a versioned Parquet matrix and a compact CSV audit under `data/processed/`.
7. Produce JSON/CSV matrix-quality outputs covering schema validity, eligible count, field and sector missingness, freshness, flag counts, and exclusions.
8. Add focused unit tests and one cached end-to-end integration test.
9. Review the resulting schema and change `config/data_contract.yaml` from `validated_pending_feature_matrix` to a frozen v1 status only after the matrix passes.

### Pipeline Requirements

- Resume after interruption.
- Reuse exact-date caches unless explicit refresh is requested.
- Keep provider clients modular and provider JSON internal.
- Preserve source dates and quality flags in every row.
- Continue when an individual security fails, recording the error and exclusion reason.
- Never expose `.env` or raw credentials in logs.

### Known Open Cases

- Full-universe SEC extraction has not yet been run; only the 88-security stratified sample is validated.
- `ECHO` requires corporate-action reconciliation.
- `FDXF`, `HONA`, and `Q` need additional market history.
- Provisional screening weights are not yet analytically validated.
- Scoring, screening services, UI, MCP, agent, and report generation are not implemented.

## 10. Remaining Roadmap

### Phase 3: Factor Scoring

1. Implement sector winsorization and percentile transforms.
2. Build Momentum, Quality, Valuation, Risk, and Sector Strength components.
3. Apply configured mode weights and missing-aware renormalization.
4. Preserve metric-level contribution details and exclusion reasons.
5. Test ranking stability under missing data, small input changes, and sector edge cases.

### Phase 4: Screening and Explanations

1. Implement `screen_stocks` with universe, mode, sector, liquidity, and top-N filters.
2. Produce structured strengths, risks, warnings, and next research questions.
3. Add stock-detail, comparison, market-overview, and sector-summary services.

### Phase 5: Minimal Product Surface

1. Build the Stock Screener first.
2. Build Stock Detail second.
3. Show source names, data dates, fiscal periods, missing fields, and warnings.
4. Add market/sector views only after ranking outputs are stable.

### Phase 6: MCP

Expose tested application services as narrow MCP tools. Return normalized project schemas, not provider payloads.

### Phase 7: Agent and Research Briefs

Map natural-language intent to validated universes, modes, and filters. Ground every statement in MCP output and reject unsupported predictions or trading instructions.

### Final Academic and Portfolio Delivery

- Reproducible pipeline and cached demo snapshot.
- Explainable preference-aware screener.
- Streamlit demonstration.
- MCP tools and grounded agent interaction.
- Research paper covering the business problem, data, methodology, MCP design, limitations, and results.
- Screenshots and optional demo video.

## 11. Reproduction Commands

Setup:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Cross-sector market sample:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-13 --tickers AAPL MSFT JPM XOM JNJ PG CAT NEE LIN AMT PLD
```

Full market audit, served from completed local cache for this exact as-of date:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-13
```

Stratified SEC audit:

```bash
.venv/bin/python -m src.sec_coverage --as-of 2026-07-13 --per-sector 8
```

Tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
```

Do not add `--refresh` casually. Confirm credits, expected runtime, and the need for a new snapshot first.

## 12. Instructions for the Next GPT or Codex Session

Read in order:

1. `README.md`;
2. `PROJECT_SPEC.md`;
3. this file;
4. `config/data_contract.yaml`;
5. relevant source modules and tests.

Then inspect the actual worktree before editing. Preserve local caches and user changes. Do not expose `.env`. Do not replace the approved provider stack unless a documented requirement fails.

Immediate assignment:

> Complete Phase 2 by building and validating the resumable full-universe feature pipeline. Preserve provenance and quality flags, add proportionate tests, and do not begin factor scoring, MCP, Agent, Streamlit, or LLM work until the model-ready matrix passes its quality audit.

Use subagents only for independent, bounded parallel work such as contract review, test-gap analysis, or output-quality auditing. Keep pipeline integration and final verification in the main thread.
