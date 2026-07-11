# Pre-Model Data Readiness Report

Assessment date: 2026-07-11

## Overall Status

**Conditionally ready. One external gate remains: full S&P 500 market coverage with a personal Twelve Data API key.**

Do not start factor-score implementation until that run reaches at least 95% usable market coverage.

## Gate Status

| Gate | Status | Evidence |
| --- | --- | --- |
| Universe schema and CIK mapping | Passed | 503 securities across 11 GICS sectors |
| Approved market provider selected | Passed | Twelve Data documented API; Nasdaq website capture disabled |
| Market adapter/parser | Passed | Official AAPL demo: 274 adjusted daily rows through 2026-07-10 |
| Full-universe market coverage | Pending API key | Resumable runner implemented; `TWELVE_DATA_API_KEY` not configured |
| SEC cross-sector retrieval | Passed | 88/88 requests succeeded, eight securities per sector |
| SEC core extraction | Passed | 88/88 core records extracted |
| Fundamental field coverage | Passed with applicability rules | FCF 80/88; shares outstanding 77/88; other core fields strong |
| Numeric validity rules | Passed | Negative equity invalidates ROE/leverage; extreme margins and stale shares flagged |
| Data contract | Passed | `config/data_contract.yaml` frozen pending market coverage |
| Data quality policy | Passed | Freshness, missingness, outlier, sector and bias rules documented |
| Unified feature builder | Passed | Provider-independent merge, valuation proxies, flags and eligibility tested |
| Automated tests | Passed | Parser, feature, XBRL, coverage and contract tests |

## SEC Findings That Affect the Model

- Revenue, net income, assets, operating cash flow, growth, and profit margin were available for all 88 sampled securities.
- FCF was available for 80/88. Missingness was concentrated in Financials and Real Estate, so FCF is an optional sector-applicable input.
- Two companies had negative stockholders' equity. Their ROE and liabilities-to-equity are set to null rather than scored.
- Three profit margins exceeded 100% in Financials or Real Estate and are flagged for sector-specific review.
- Usable shares outstanding covered 77/88 after rejecting stale, missing, or implausible values. Market cap and annual PE remain optional proxies.
- Median annual-fundamental age was 192 days; the oldest was 379 days. Fiscal period and filing date are mandatory output fields.

## Remaining Command

Create the ignored local environment file and add your personal key:

```bash
cp .env.example .env
```

Run the full, rate-limited audit:

```bash
.venv/bin/python -m src.market_coverage --as-of 2026-07-11
```

The runner uses eight symbol credits per rate window, caches each response, and resumes after interruption. When `market_coverage_full_summary.json` reports `usable_rate >= 0.95`, Phase 1 is complete and factor-model development may begin.
