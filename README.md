# Equity Screening Agent

An explainable, preference-aware U.S. equity research screener built on latest-available daily market data and filing-based fundamentals. It is a research-support system, not a price predictor, trading bot, or financial adviser.

## Status

Phase 1 data feasibility validation is complete:

- 503/503 current S&P 500 securities were retrieved from Twelve Data.
- 499/503, or 99.20%, passed the market usability gate.
- SEC Company Facts retrieval and core extraction passed for a stratified 88-security, 11-sector sample.
- The automated suite had 47 passing tests at the Phase 2 freeze and now has
  130 passing tests after the Phase 3 freeze and acceptance-contract hardening.

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
The active phase is Phase 4, screening and structured explanations. Streamlit,
MCP, the agent, and LLM-generated briefs remain later work.

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

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
```

## Approved Data Boundary

- Universe: Wikipedia current S&P 500 table.
- Daily adjusted OHLCV and SPY benchmark: Twelve Data `/time_series` with `adjust=all`.
- Annual fundamentals: SEC EDGAR Company Facts.
- Local CSV, Parquet, and JSON: reproducibility and rate-limit protection.

Nasdaq website capture is prohibited for this project. Yahoo Finance and Stooq are not runtime dependencies. Forward PE, analyst estimates, targets, news, and sentiment are deferred until a documented and reliable source is approved.
