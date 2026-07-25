# Equity Screening Agent: Context, Progress, and Data Policy

Last updated: 2026-07-22 (Asia/Shanghai)

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
| Data contract and quality rules | Contract `1.0.0`, status `frozen_v1` | Passed and frozen |
| Accepted feature matrix | 503 rows; 499 eligible, or 99.20% | Passed |
| Automated tests | 47/47 at Phase 2; 130/130 at Phase 3; 165/165 after Phase 4 | Passed |

**Phase 2, the full feature-matrix pipeline and contract freeze, is complete.** The accepted run is `2026-07-13_sp500_v1_0_0` for as-of date `2026-07-13`, stored locally under `data/processed/2026-07-13_sp500_v1_0_0/`.

**Phase 3, the deterministic scoring kernel and method-contract freeze, is
complete.** Factor model `1.0.0` and screening modes `1.0.0` have status
`frozen_v1`. Accepted run `2026-07-13_sp500_scores_v1_0_2` is bound by scoring
contract `1.0.2`; its scored-matrix SHA-256 is
`32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81`.

**Phase 4, deterministic screening and structured explanations, is complete.**
The public `screen_stocks` service reads only the verified accepted scoring run,
preserves stored scores and weights, returns explicit exclusion evidence, and
has 35 focused tests.

The active phase is **Phase 5: minimal product surface**. The next implementation
is a minimal Streamlit Stock Screener over the stable application service.
MCP, the AI agent, and LLM-generated briefs remain later work.

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
| `ECHO` | Verified event-driven 70.2% daily move on 2025-08-26 | Contract v1 conservatively retains the greater-than-50% exclusion rule |

The three genuine short-history cases should be reevaluated automatically on each new snapshot. `ECHO` remains excluded in contract v1 even though its jump was verified as a real event, preserving the frozen and deliberately conservative market-quality rule.

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
- Stale raw values may remain available for diagnosis, but every scoring metric is checked against its own period and stale values are nullified before current ranking.

### Market Eligibility

A security is eligible only when it has:

- at least 180 daily observations in the validation window;
- no duplicate trading dates;
- no missing OHLCV rows;
- positive OHLC prices;
- no absolute daily return above 50%; verified event-driven moves remain
  conservatively excluded under contract v1;
- a confirmed adjusted-price mode;
- all required market features.

### Fundamental Validity

- Merge XBRL synonyms by fiscal period so a stale tag cannot hide a newer equivalent.
- Calculate ratios only from values aligned to the same fiscal period.
- Require every non-null fundamental scoring value to have a metric-specific period no more than 550 days old.
- Set ROE and liabilities-to-equity to null when equity is zero or negative.
- Preserve raw profit margin for audit, but set the scoring margin to null when its absolute value exceeds 100%.
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
- `src/feature_pipeline.py`: deterministic Phase 2 orchestration, cache modes, provider failure isolation, CLI, and run metadata.
- `src/matrix_quality.py`: contract validation, quality summaries, acceptance gates, and atomic artifact persistence.
- `src/scoring.py`: versioned sector transforms, factor and mode aggregation,
  accepted-input enforcement, ranking-evidence fields, and the Phase 3 CLI.
- `src/scoring_quality.py`: scoring row accounting, score/weight/arithmetic and
  coverage gates, independent metric/Sector Strength/component/ranking/
  provenance recomputation, full Phase 2 input projection, native numeric-
  evidence dtype enforcement, audit tables, and whole-run atomic artifacts.
- `src/scoring_contract.py`: fail-closed loading of the frozen accepted scoring
  artifact by identity, hashes, configuration, independently recomputed quality,
  native score dtypes, provenance, row counts, and mode-ranking state.
- `src/screening.py`: deterministic Phase 4 application service for universe
  resolution, input validation, stored mode eligibility, filters, ranking,
  explicit exclusions, and JSON-ready evidence projection.
- `src/explanations.py`: deterministic, non-LLM strengths, risks, reason
  evidence, and next-research-question helpers over stored factor scores.

### Validation Modules

- `src/market_coverage.py`: resumable market audit and 95% gate.
- `src/sec_coverage.py`: deterministic sector-stratified SEC audit.
- `src/data_feasibility.py`: legacy 22-security evidence; no new Nasdaq requests are permitted.
- `notebooks/01_data_feasibility.ipynb`: Phase 1 exploratory summary.

### Configuration

- `config/data_contract.yaml`: row grain, providers, fields, missingness, and preprocessing.
- `config/data_sources.yaml`: provider configuration.
- `config/universes.yaml`: universe definitions.
- `config/screening_modes.yaml`: frozen v1 balanced, growth, value, and low-risk
  weights plus ranking-evidence requirements.
- `config/factor_model.yaml`: frozen v1 metric membership, directions,
  derivations, applicability, preprocessing, and Sector Strength semantics.
- `config/scoring_contract.yaml`: frozen accepted scoring-run identity, hashes,
  versions, row counts, and ranking-eligibility counts.

### Tests

One hundred sixty-five tests cover the Phase 1/2 provider and feature pipeline,
the Phase 3 scoring and acceptance contracts, and the Phase 4 screening
service. The 35 screening tests cover normal ranking, all numeric and sector
filters, Value ranking eligibility, deterministic ties, missing filter values,
custom ticker normalization, unknown tickers, clear invalid-input errors,
eligibility-before-filter ordering, stored-score preservation, row-order
invariance, explicit top-N exclusions, and network/direct-Parquet independence.

Latest result:

```text
165 passed
```

## 7. Machine-Readable Evidence

Long-term documentation is limited to `README.md`, `PROJECT_SPEC.md`, and this file. Validation artifacts remain machine-readable:

- local ignored `data/processed/2026-07-13_sp500_v1_0_0/`, the accepted Phase 2 feature snapshot and quality bundle;
- local ignored `data/processed/phase3a_candidate_v0_2_0/`, the reviewed Phase
  3 candidate scores and quality bundle;
- local ignored `data/processed/2026-07-13_sp500_scores_v1_0_2/`, the accepted
  frozen v1 scoring artifact;

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

GitHub remote: `https://github.com/yly-28/equity-screening-agent.git`

Published Phase 2/3 baseline:

```text
eddf33d feat: complete phase 2 and phase 3 pipelines
```

Commit `eddf33d` was pushed to `origin/main` on 2026-07-22. It contains the
complete Phase 2 feature pipeline, Phase 3 scoring and quality layers, frozen
contracts, documentation, and the 130-test suite. The accepted Phase 2 and
Phase 3 processed runs are intentionally ignored local artifacts and are not in
Git.

The Phase 4 publication branch `agent/complete-phase-4-screening` adds the
completed screening service, deterministic explanation helpers, and 35 focused
tests, bringing the suite to 165 passing tests. It is published through a draft
pull request and is not part of `main` until that pull request is merged.

Every new session must still run `git status -sb` and `git log -1 --oneline`
before editing because this handoff file itself or later work may be newer than
the published baseline. Never reset or discard local work casually. `.env`, raw
provider payloads, local caches, processed matrices, and security-level provider
exports must remain untracked unless an explicit redistribution and version-
control decision is made.

## 9. Completed Phase 3 Scoring Kernel

### Phase 2 Accepted Snapshot

Phase 2 delivered the reproducible, resumable full-universe feature pipeline and froze data contract `1.0.0` with status `frozen_v1`.

| Item | Accepted evidence |
| --- | --- |
| Run ID | `2026-07-13_sp500_v1_0_0` |
| As-of date | `2026-07-13` |
| Local artifact | `data/processed/2026-07-13_sp500_v1_0_0/` |
| Accepted matrix SHA-256 | `1c716d9ab7b553eb363321be6d326682b0dd5ff8fc6446e376e416c79ef2a1ef` |
| Row accounting | 503 requested and 503 persisted |
| Eligibility | 499/503, or 99.20% |
| Exclusions | `ECHO`, `FDXF`, `HONA`, and `Q` |
| Provider execution | Cache-only; zero provider errors and zero market network batches |
| Metric freshness | Zero metric-period violations and zero stale non-null violations |
| Automated verification | 47 tests passed |
| Phase 2 status | Complete |

Metric-specific freshness enforcement nullified 59 stale values across 51 securities before acceptance:

| Metric | Nullified values |
| --- | ---: |
| Annual free cash flow | 43 |
| Liabilities-to-equity | 8 |
| Annual revenue | 2 |
| Revenue growth | 2 |
| Profit margin | 2 |
| Annual net income | 1 |
| ROE | 1 |

Required fundamental value gaps among eligible rows are limited and explicitly flagged. `APA`, `LHX`, and `PSKY` account for the three missing revenue and revenue-growth values; `PSKY` accounts for the one missing annual-net-income value; and profit margin is unavailable for those three plus `MRNA`, whose raw margin is retained for audit but excluded from scoring.

Optional eligible-row missingness accepted under the frozen contract is:

| Field | Missing | Rate |
| --- | ---: | ---: |
| Annual free cash flow | 86 | 17.23% |
| Shares outstanding and market-cap proxy | 40 | 8.02% |
| Annual PE proxy | 64 | 12.83% |
| ROE | 32 | 6.41% |
| Liabilities-to-equity | 39 | 7.82% |

Revenue-basis review remains visible through quality flags: 25 broad-total material overrides, 11 source-review warnings, three source conflicts, and one lease-only basis. Every sector-metric combination has at least 10 valid observations after nullification. Communication Services annual PE is the boundary case at exactly 10 observations and must be reevaluated on every new snapshot.

### Accepted Exclusions

| Ticker | Accepted handling |
| --- | --- |
| `ECHO` | The greater-than-50% move was verified as a real event-driven price jump, but contract v1 conservatively retains the fixed threshold and excludes the row. |
| `FDXF` | Genuine short trading history; fewer than 180 required observations. |
| `HONA` | Genuine short trading history; fewer than 180 required observations. |
| `Q` | Genuine short trading history; fewer than 180 required observations. |

### Phase 3 Objective

Implement a deterministic scoring kernel over the frozen feature matrix. It must:

1. define versioned metric membership, direction, applicability, and within-factor weights;
2. apply sector 5th/95th-percentile winsorization and 0-100 rank-percentile transforms only when a sector has at least 10 valid observations;
3. build Momentum, Quality, Valuation, Risk, and Sector Strength scores;
4. apply the balanced, growth, value, and low-risk mode weights from `config/screening_modes.yaml`;
5. renormalize over available and economically applicable metrics and factors without treating missing values as zero;
6. preserve raw values, transformed scores, effective weights, component availability, provenance, quality flags, and exclusion reasons;
7. persist deterministic scoring artifacts and add unit, contract, edge-case, and network-disabled integration tests.

Phase 3 does not include the public `screen_stocks` service, structured ranking
explanations, Streamlit, MCP, the agent, or LLM-generated briefs.

### Phase 3 Review and Accepted Evidence

Candidate `0.1.0` was not frozen unchanged. Full-snapshot quantitative review
found duplicate 3-month Momentum exposure, an absolute-FCF size signal, a
share-volume price-level bias, excessive Growth sector concentration, and
Value rankings without valuation evidence. Candidate `0.2.0` corrected these
before promotion to frozen `1.0.0`:

- Momentum retains 3-month total return and reserves `relative_strength_3m`
  for Sector Strength, eliminating a 499/499 exact score duplicate.
- Quality uses exact-period free-cash-flow margin instead of absolute FCF. It
  has 327/361 coverage in applicable sectors; `RL` is correctly unavailable
  because its FCF and revenue periods differ.
- Risk removes share volume. Liquidity stays a Phase 4 filter until a later
  data contract can supply true mean daily dollar volume.
- Growth shifts 10 percentage points from Sector Strength to Momentum and
  Quality. Its Top-50 expanded from six sectors to ten, with at most 12 names
  from one sector.
- Value retains a diagnostic score but requires a Valuation factor for ranking;
  435/499 eligible rows satisfy that evidence gate and its Top-50 contains zero
  rows without Valuation.

Accepted run `2026-07-13_sp500_scores_v1_0_2` consumed the frozen Phase 2
snapshot locally and produced 503 scored rows:

| Check | Accepted evidence |
| --- | --- |
| Model/config | Factor model `1.0.0`; screening modes `1.0.0`; both `frozen_v1` |
| Accepted scored SHA-256 | `32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81` |
| Eligible/ineligible | 499/4; all ineligible metric, factor, and mode scores are null |
| Diagnostic mode completeness | All 499 eligible rows have all four mode scores |
| Ranking eligibility | Balanced 499, Growth 499, Value 435, Low Risk 499 |
| Sector coverage | Zero insufficient applicable sector-metric combinations; Communication Services PE is 10/22 |
| Factor availability | Momentum 499, Quality 498, Valuation 435, Risk 499, Sector Strength 499 |
| Independent quality gates | Zero transform, Sector Strength, component, input-projection, numeric-evidence dtype, ranking, provenance, or coverage violations |
| Determinism | Scored Parquet and all four review tables matched a second v1 run byte-for-byte |
| Tests | 130 passed |

The only accepted scoring warning is eligible factor missingness. `PSKY` has no
Quality or Valuation factor, but diagnostic mode scores disclose and use
renormalized Momentum, Risk, and Sector Strength weights; it is not eligible
for Value ranking. `MRNA`'s audit-only raw margin does not enter scoring.

### Remaining Limitations After the Freeze

- Communication Services annual PE has exactly the minimum 10 valid
  observations and must be reevaluated on each new snapshot.
- Sector Strength has only 11 sector-level ranks; raw sector medians and member
  counts remain mandatory alongside the score.
- This is a one-snapshot method-contract validation, not a backtest or evidence
  of future-return prediction. A new methodology requires a new version rather
  than mutating frozen v1.
- The public custom-universe workflow is intentionally limited to ticker
  subsets already present in the accepted S&P 500 snapshot. Unknown tickers are
  reported separately; the service does not fetch or score new securities.
- Screening is bound to the fixed accepted as-of date and has no arbitrary
  as-of or run-path input. The local accepted Phase 2 and Phase 3 artifacts must
  exist and pass verification or the service fails closed.
- An active numeric filter excludes a row whose corresponding value is missing;
  it never treats missing as zero. In particular, market-cap-proxy gaps can
  reduce a filtered result set.
- Every known candidate ticker not returned carries an explicit exclusion
  record, including `outside_top_n`. This is audit-friendly but can make
  full-universe response payloads large; UI/MCP adapters may later need summary
  or pagination.
- The accepted loader independently revalidates the full frozen scoring bundle
  on each service call. This preserves the fail-closed boundary but has no
  cross-call performance cache yet.
- Structured strengths, risks, and research questions are deterministic rules
  over stored evidence. High/low factor evidence currently uses fixed 70/30
  score thresholds; it is not causal analysis or LLM-authored investment advice.
- The screening service is implemented; UI, MCP, agent, comparison, stock
  detail, market summaries, and report generation are not yet implemented.

## 10. Remaining Roadmap

### Phase 3: Scoring Kernel (Complete)

1. Completed: sector winsorization and percentile transforms.
2. Completed: Momentum, Quality, Valuation, Risk, and Sector Strength components.
3. Completed: configured mode weights and two-level missing-aware renormalization.
4. Completed: metric inputs, transformed values, components, effective weights,
   reasons, provenance, and exclusions in deterministic artifacts.
5. Completed: quantitative distribution/preference review, model revision,
   frozen v1 configs, accepted scoring contract, and byte-exact determinism.

### Phase 4: Screening and Explanations (Complete)

Phase 4 delivered the tested `screen_stocks` application service in
`src/screening.py` and isolated deterministic explanation helpers in
`src/explanations.py`. Its public inputs are:

```text
universe
custom_tickers
mode
sectors
minimum_price
minimum_market_cap_proxy
minimum_average_volume_20d
top_n
```

The completed service:

1. loads only through `src.scoring_contract.load_accepted_scoring_run` and has
   no arbitrary run-directory or Parquet input;
2. applies stored mode-ranking eligibility first, requested filters second,
   stored mode-score/ticker ordering third, and `top_n` last;
3. never recomputes transforms, factor scores, mode scores, or effective
   weights on a filtered subset;
4. normalizes custom tickers, reports unknown tickers separately, and validates
   universes, modes, sectors, thresholds, and `top_n` clearly;
5. excludes missing active numeric-filter fields instead of treating them as
   zero;
6. returns rank, identity, sector/industry, five factor scores, effective
   weights, data dates and sources, missing inputs, warnings, strengths, risks,
   reason codes, and next research questions;
7. records explicit per-candidate-ticker reasons for mode ineligibility,
   requested-filter failures, and `outside_top_n`;
8. labels `average_volume_20d` as 20-day average share volume rather than dollar
   liquidity; and
9. is JSON-serializable, row-order invariant, and network-independent outside
   the accepted loader boundary.

Accepted-run review reproduced Balanced leaders `ALL`, `KLAC`, and `PGR`, and
Value leaders `ACGL`, `ALL`, and `MO`. A stored Value tie was resolved
deterministically as `D` rank 84 and `ES` rank 85. Thirty-five focused tests and
the full 165-test suite pass.

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

Reproduce the accepted Phase 2 snapshot entirely from exact-date caches without overwriting the accepted run directory:

```bash
.venv/bin/python -m src.feature_pipeline \
  --as-of 2026-07-13 \
  --cache-only \
  --run-id phase2_reproduction_2026-07-13
```

Reproduce frozen Phase 3 scoring under a new run ID without overwriting the
accepted scoring directory:

```bash
.venv/bin/python -m src.scoring \
  --input-run data/processed/2026-07-13_sp500_v1_0_0 \
  --run-id phase3_reproduction_contract_v1_0_2
```

Tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
```

Do not add `--refresh` casually. Confirm credits, expected runtime, and the need for a new snapshot first.

## 12. Instructions for the Next GPT or Codex Session

Read in order:

1. this file;
2. `README.md`;
3. `PROJECT_SPEC.md`;
4. `config/data_contract.yaml`;
5. `config/factor_model.yaml`, `config/screening_modes.yaml`, and
   `config/scoring_contract.yaml`;
6. `src/scoring_contract.py`, `src/screening.py`, `src/explanations.py`, and
   relevant tests.

Start with these checks:

```bash
git status -sb
git log -1 --oneline
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

The published baseline remains commit `eddf33d` on `main` with 130 Phase 1-3
tests. The current Phase 4 worktree should report `165 passed`. On this machine,
the accepted local run should be
`data/processed/2026-07-13_sp500_scores_v1_0_2/`. If it is absent, do not weaken
the loader or point it at an arbitrary candidate; restore or reproduce the
accepted artifacts according to the frozen contracts.

Then inspect the actual worktree before editing. Preserve local caches and user
changes. Do not expose `.env`. Do not replace the approved provider stack unless
a documented requirement fails.

Do not reimplement Phase 2 or Phase 3: their pipelines, quality layers, frozen
contracts, accepted artifacts, CLIs, and tests are committed in `eddf33d` and
the accepted processed artifacts remain local and ignored.

Immediate assignment:

> Build the minimal Streamlit Stock Screener over the completed
> `src.screening.screen_stocks` service. Keep all analytical logic in the tested
> service, show data dates, missing inputs, warnings, and proxy/share-volume
> labels accurately, and do not bypass the accepted-run loader. Stop before MCP,
> agent, LLM, comparison, or market-summary work.

Phase 5 sequence:

1. Add the minimal Streamlit dependency and one operational screener page.
2. Map controls directly to the eight `screen_stocks` inputs.
3. Render ranked stocks, factor evidence, dates, warnings, and exclusions
   without reimplementing filtering or scoring in the UI.
4. Add lightweight UI-boundary tests and rerun the full suite.
5. Build Stock Detail only after the screener is stable; MCP and the agent/LLM
   remain later phases.

Suggested prompt for a fresh window:

> Read `PROJECT_CONTEXT_AND_PROGRESS.md` completely, preserve the completed
> Phase 4 worktree, verify the 165-test result, then build the smallest useful
> Streamlit Stock Screener by calling `screen_stocks` directly. Keep analytics
> out of the UI and stop before MCP, agent, LLM, comparison, or market-summary
> work.
