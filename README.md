# Equity Screening Agent

An explainable, preference-aware U.S. equity research screener built on latest-available daily market data and filing-based fundamentals. It is a research-support system, not a price predictor, trading bot, or financial adviser.

## Status

Phase 1 data feasibility validation is complete:

- 503/503 current S&P 500 securities were retrieved from Twelve Data.
- 499/503, or 99.20%, passed the market usability gate.
- SEC Company Facts retrieval and core extraction passed for a stratified 88-security, 11-sector sample.
- The automated suite had 47 passing tests at the Phase 2 freeze, 130 after the
  Phase 3 freeze, 165 after the Phase 4 screening service, 175 after the
  Phase 5 screener, and now has 214 after the completed Phase 5 product
  surface.

Phase 2 is complete. Data contract `1.0.0` is frozen with status `frozen_v1`. The accepted cache-only run is `2026-07-13_sp500_v1_0_0` for as-of date `2026-07-13`, stored locally under `data/processed/2026-07-13_sp500_v1_0_0/`. It retained all 503 securities, produced 499 eligible rows (99.20%), and excluded `ECHO`, `FDXF`, `HONA`, and `Q`. The run had zero provider errors, zero market network batches, and zero metric-period or stale-non-null violations.

Phase 3 is complete. Factor model `1.0.0` and screening modes `1.0.0` are
frozen with status `frozen_v1`. The accepted local run is
`2026-07-13_sp500_scores_v1_0_2`; its scored-matrix SHA-256 is
`32cb1036fc45f2eb73bbef15e7f4ad920e4585650b33722985565213f8f2ea81`.
Scoring contract `1.0.2` binds that artifact to its input snapshot,
configuration hashes, complete independent quality evidence, metric-sector
coverage, row counts, and ranking eligibility. The accepted loader re-runs the
quality gate from the frozen Phase 2 matrix instead of trusting stored summary
flags alone.
Phase 4 is complete. The deterministic `screen_stocks` service filters and
ranks only the verified accepted scoring run and returns structured evidence,
exclusions, and research questions without rescoring a filtered subset.
Phase 5 is complete. The operational Streamlit application in
`app/stock_screener.py` provides separate Stock Screener and Stock Detail
views over `screen_stocks` and `get_stock_detail`. The UI performs no loading,
filtering, scoring, ranking, or evidence derivation. Phase 6 MCP is next; the
agent and LLM-generated briefs have not been implemented.

The completed Phase 5 implementation is published on
`agent/phase-5-streamlit-screener` (implementation commit
`1bd93489a8a2be2d5166b829f7edfd376205310c`). No Phase 5 pull request has
been opened.

## Documentation

- [`PROJECT_SPEC.md`](PROJECT_SPEC.md): stable product requirements, architecture, analytical contracts, planned MCP tools, UI scope, and final success criteria.
- [`PROJECT_CONTEXT_AND_PROGRESS.md`](PROJECT_CONTEXT_AND_PROGRESS.md): current implementation state, complete validation evidence, data-quality policy, Git state, commands, and the next development tasks.

These are the only authoritative project Markdown documents. Machine-readable provider validation evidence is kept under `outputs/`; processed feature snapshots remain local under `data/processed/` and are ignored by Git.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Fill these local values in `.env`:

```text
TWELVE_DATA_API_KEY=...
SEC_USER_AGENT="equity-screening-agent/0.1 Your Name your-email@example.com"
```

`.env`, provider caches, and security-level provider exports are ignored by Git. Never print or commit their contents.

## Validation Commands

Cross-sector market sample:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-13 --tickers AAPL MSFT JPM XOM JNJ PG CAT NEE LIN AMT PLD
```

Full S&P 500 market audit, resumable from local cache:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-13
```

Stratified SEC audit:

```bash
.venv/bin/python -m src.sec_coverage --as-of 2026-07-13 --per-sector 8
```

Do not add `--refresh` without confirming API allowance, runtime, and the need for a new as-of snapshot.

## Feature Pipeline

Run a deterministic subset entirely from exact-date local caches:

```bash
.venv/bin/python -m src.feature_pipeline \
  --as-of 2026-07-13 \
  --tickers AAPL MSFT JPM \
  --cache-only
```

The accepted Phase 2 artifact is:

```text
data/processed/2026-07-13_sp500_v1_0_0/
```

Reproduce the accepted snapshot entirely from exact-date local caches without overwriting that directory:

```bash
.venv/bin/python -m src.feature_pipeline \
  --as-of 2026-07-13 \
  --cache-only \
  --run-id phase2_reproduction_2026-07-13
```

For a future full-universe snapshot with cache-first provider access:

```bash
.venv/bin/python -m src.feature_pipeline \
  --as-of YYYY-MM-DD \
  --run-id YYYY-MM-DD_sp500_candidate
```

Cache-first runs may make provider requests when an exact-date cache is absent. Confirm user authorization, provider allowance, and a valid `SEC_USER_AGENT` before using that mode for a new snapshot. Do not add `--refresh` casually.

Once an accepted run directory exists under a frozen contract, the pipeline
refuses to overwrite it. Reproductions and future candidates must use a
different explicit `--run-id`.

`--cache-only` forbids network access and records cache misses as ineligible rows. `--refresh` is explicit and mutually exclusive with cache-only mode. A successful run returns exit code `0`; a persisted matrix that fails the quality gate returns `1`; setup or persistence failure returns `2`.

Each run is written under `data/processed/<run_id>/` with:

- `feature_matrix.parquet`, preserving native list-valued quality fields;
- `feature_audit.csv` for compact row review;
- `matrix_quality.json` and `run_metadata.json`;
- field and sector missingness, freshness, flag, and exclusion CSVs;
- `quality_report.md`.

Processed matrices and provider caches remain local and ignored by Git.

## Phase 3 Scoring (Frozen v1)

The accepted Phase 3 artifact is:

```text
data/processed/2026-07-13_sp500_scores_v1_0_2/
```

Reproduce frozen v1 under a different run ID:

```bash
.venv/bin/python -m src.scoring \
  --input-run data/processed/2026-07-13_sp500_v1_0_0 \
  --run-id phase3_reproduction_contract_v1_0_2
```

The command makes no provider or network requests. It fits sector transforms
only on the 499 eligible rows, retains all 503 input rows, and keeps every score
null for the four ineligible rows. Before scoring, it verifies the accepted run
ID, contract version, passed feature-quality report, and frozen matrix SHA-256.
Metric and factor weights are renormalized over available and applicable
inputs; row-level effective weights and ranking eligibility are persisted for
audit. The independent gate also verifies that every original Phase 2 column
is preserved unchanged in the scored matrix. The accepted run and every
existing run directory are immutable: the
CLI refuses overwrite and creates each artifact bundle through a whole-run
staging transaction. Exit code `0` means artifacts were persisted and the
scoring gate passed, `1` means artifacts were persisted but the gate failed,
and `2` means input, configuration, or persistence failed.

Each scoring run writes under `data/processed/<run_id>/`:

- `scored_matrix.parquet` and `scoring_audit.csv`;
- `metric_sector_coverage.csv`, `factor_coverage.csv`, and
  `score_distributions.csv`;
- `scoring_quality.json`, `run_metadata.json`, and `quality_report.md`.

Frozen v1 removed duplicate 3-month momentum exposure, replaced absolute free
cash flow with exact-period free-cash-flow margin, removed share volume from
Risk until true average dollar volume exists, reduced Growth's Sector Strength
weight from 20% to 10%, and requires Valuation evidence for Value ranking.
Diagnostic mode scores remain available for all 499 eligible rows; ranking
eligibility is 499 for Balanced, Growth, and Low Risk, and 435 for Value.

The accepted run has zero hard failures across row accounting, transform
recomputation, Sector Strength recomputation, score range, effective weights,
aggregate arithmetic, component counts, ranking eligibility, coverage
ownership and values, native numeric evidence types, provenance, and
ineligible-score gates. Quality is
unavailable only for `PSKY`; Valuation is unavailable for 64 eligible rows.
Communication Services annual PE is scored at the exact 10-observation
minimum. The accepted scored Parquet and all four review tables matched a
second v1 run byte-for-byte.

Downstream code should load the accepted artifact through
`src.scoring_contract.load_accepted_scoring_run`, which fails closed on an
identity, hash, configuration, quality, provenance, row-count, or ranking-state
mismatch. The v1 freeze establishes deterministic methodology; it does not
claim predictive or future-return validation from a single cross-section.

## Phase 4 Screening Service

The public application service is:

```python
from src.screening import screen_stocks

result = screen_stocks(
    universe="sp500",
    custom_tickers=None,
    mode="balanced",
    sectors=None,
    minimum_price=None,
    minimum_market_cap_proxy=None,
    minimum_average_volume_20d=None,
    top_n=20,
)
```

It supports `sp500` and custom subsets of tickers already present in the
accepted snapshot. Unknown custom tickers are returned separately. The service
applies the selected mode's stored ranking-eligibility flag first, then the
requested filters, then deterministic sorting by stored mode score descending
and ticker ascending, and finally `top_n`. It never opens an arbitrary Parquet
path or recomputes scores, transforms, or weights.

Each returned stock includes identity, sector and industry, the selected mode
and stored score, all five factor scores, effective factor weights, market and
fundamental dates, missing inputs, warnings, strengths, risks, reason codes, and
next research questions. Every known candidate ticker not returned has an
explicit stage and reason, including mode eligibility, requested filters, or
`outside_top_n`.
`average_volume_20d` is labeled as 20-day average share volume, not dollar
liquidity.

## Phase 5 Streamlit Product Surface (Complete)

Install the pinned dependencies, keep the accepted Phase 2 and Phase 3
artifacts in their frozen local paths, and launch from the repository root:

```bash
.venv/bin/streamlit run app/stock_screener.py
```

The sidebar switches between two deterministic views. The Stock Screener form
maps directly to:

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

The Screener view calls `src.screening.screen_stocks` once per submitted form.
It does
not open Parquet, call providers, normalize tickers, validate or filter rows,
recompute scores or weights, or change result order. It displays the accepted
run and as-of date, active filters, ranked identities, selected-mode and factor
scores, effective weights, sources and dates, missing inputs, warnings,
strengths, risks, reason codes, research questions, unknown custom tickers,
and every explicit exclusion. Validation, accepted-data, and scoring-contract
errors are shown without a user-facing traceback.

`market_cap_proxy` is visibly labeled as a proxy, `average_volume_20d` is
20-day average share volume, and a higher Risk score means lower measured
risk. `.streamlit/config.toml` disables Streamlit usage telemetry, so the
local app remains network-independent.

Operational limitations:

- The ignored accepted Phase 2 and Phase 3 artifacts must exist and pass their
  frozen contracts.
- Each submission independently verifies the accepted bundle and takes about
  3.3 seconds on the current machine; the UI deliberately adds no cache.
- Custom tickers are limited to securities already present in the accepted
  S&P 500 snapshot. The app never fetches or scores an unknown ticker.
- Large `top_n` values create correspondingly large detail and exclusion
  tables.
- `streamlit==1.50.0` is pinned because the current environment is Python
  3.9.6. Raise the Python floor and upgrade Streamlit before any broader
  deployment; this deliverable is local-only.
- Comparison, market summary, MCP, agent, LLM, and research-brief work remain
  unimplemented. The next assignment is the minimal Phase 6 MCP adapter over
  the completed deterministic services.

The verified headless server smoke command is:

```bash
.venv/bin/streamlit run app/stock_screener.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8765 \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false
```

Its local `/_stcore/health` endpoint returned `ok`. A network-blocked AppTest
submission against the real accepted run also rendered Value results for
`ALL` and `ESS`, reported `UNKNOWN` separately, and showed explicit
mode-eligibility exclusions for `ECHO` and `PSKY`.

### Stock Detail

The dedicated application service is:

```python
from src.stock_detail import get_stock_detail

result = get_stock_detail(ticker="ALL", mode="value")
```

It accepts only a ticker and one of the four frozen screening modes. It
normalizes and validates those inputs, loads the accepted scoring bundle once
through `load_accepted_scoring_run`, and projects one exact accepted row. It
does not accept a run path or arbitrary as-of date, call `screen_stocks`,
create a one-ticker rank, access provider caches, or recompute any feature,
factor, score, transform, weight, or sector statistic.

The Stock Detail view shows:

- accepted run, as-of date, contract versions, identity, sector, and industry;
- the selected mode's stored diagnostic score, ranking eligibility, reasons,
  available factors, and effective factor weights;
- latest price, market-cap proxy, 20-day average share volume, verified history
  coverage, and the complete stored market-feature snapshot;
- fundamentals with units, contract-backed metric periods, the snapshot-wide
  latest filing date, source tags, warnings, validated profit margin, and
  audit-only raw margin;
- all five stored factor scores plus every metric's raw value, scoring input,
  winsorized value, stored score, availability, unavailable reason, and
  effective metric weight;
- stored Sector Strength context, quality evidence, missing inputs, warnings,
  base and mode exclusions, strengths, risks, reason codes, and next research
  questions.

Known but mode-ineligible securities remain inspectable. For example, `PSKY`
under Value mode retains its diagnostic Value score while separately reporting
`missing_required_factor:valuation`. Base-ineligible securities such as `ECHO`
retain identity, market evidence, missing inputs, warnings, and exclusion
reasons instead of being reduced to a sparse screening exclusion.

The frozen accepted artifact contains a one-row feature snapshot per security,
not daily OHLCV rows. Stock Detail therefore displays verified history
start/end dates, row count, latest price, returns, volatility, drawdown, moving
average gaps, relative strength, and beta, and explicitly states that a price
chart is unavailable. Reading the unverified provider cache to manufacture a
chart would violate the accepted boundary. The artifact also contains no
stored global rank, so the detail service does not invent one.

The accepted-run smoke rendered `ALL` in Value mode, verified `PSKY`'s
diagnostic Value score and ranking exclusion separately, and verified `ECHO`'s
base ineligibility and quality evidence. Unknown tickers fail clearly and are
never fetched.

## Tests

Run the deterministic Streamlit boundary tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_stock_screener_app.py
```

Latest targeted result: `10 passed`.

Run the Stock Detail service tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_stock_detail.py
```

Latest targeted result: `30 passed`.

Run the Stock Detail UI-boundary tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_stock_detail_app.py
```

Latest targeted result: `9 passed`.

Run the complete Phase 4/5 application boundary:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_screening.py tests/test_stock_detail.py \
  tests/test_stock_screener_app.py tests/test_stock_detail_app.py
```

Latest focused result: `84 passed` (`35` screening-service, `30` Stock Detail
service, `10` screener UI, and `9` Stock Detail UI tests).

Run the complete repository suite:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
```

Latest full result: `214 passed`.

## Approved Data Boundary

- Universe: Wikipedia current S&P 500 table.
- Daily adjusted OHLCV and SPY benchmark: Twelve Data `/time_series` with `adjust=all`.
- Annual fundamentals: SEC EDGAR Company Facts.
- Local CSV, Parquet, and JSON: reproducibility and rate-limit protection.

Nasdaq website capture is prohibited for this project. Yahoo Finance and Stooq are not runtime dependencies. Forward PE, analyst estimates, targets, news, and sentiment are deferred until a documented and reliable source is approved.
