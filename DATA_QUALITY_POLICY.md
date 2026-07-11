# Data Quality Policy

## Approved Sources

- Universe: Wikipedia's current S&P 500 constituents table, cached with retrieval time.
- Daily market data: Twelve Data `/time_series`, authenticated with `TWELVE_DATA_API_KEY` and `adjust=all`.
- Filing fundamentals: SEC EDGAR Company Facts, accessed below the SEC fair-access threshold with an identifying `SEC_USER_AGENT`.

Nasdaq website JSON is not approved for new requests because Nasdaq's website terms prohibit automated capture. Yahoo Finance and Stooq are not runtime dependencies because they failed the feasibility probes.

## Freshness

- Daily prices are usable when the latest observation is no more than five calendar days old. This accommodates weekends and normal U.S. market holidays.
- Annual fundamentals are usable up to 550 days after the fiscal period end, but their period end and filing date must always be shown.
- Data older than these thresholds remains stored for diagnosis but is excluded from current rankings.

## Market Data Checks

A security is eligible for scoring only when it has:

- at least 180 daily observations in the validation window;
- no duplicate trading dates;
- no missing OHLCV rows;
- positive OHLC prices;
- no unexplained absolute daily return above 50%;
- an explicitly recorded adjustment mode.

Twelve Data requests use `adjust=all`. Provider metadata, request dates, and cache timestamps are retained.

## Fundamental Checks

- XBRL synonyms are merged by fiscal period so a stale tag cannot hide a newer equivalent tag.
- Ratios are calculated only from values with aligned period ends.
- ROE and liabilities-to-equity are invalid when stockholders' equity is zero or negative.
- Profit margins with absolute value above 100% are flagged for review and are never compared across sectors.
- Shares outstanding below 100,000, missing, or more than 550 days older than the latest fundamental period are invalid.
- Free cash flow is optional for Financials, Real Estate, and Utilities.

## Missing Values and Outliers

- Missing values remain null and are never converted to zero scores.
- A missing required market field excludes the security from ranking.
- Missing optional factor inputs cause component weights to be renormalized over applicable fields.
- Continuous scoring inputs are winsorized within sector at the 5th and 95th percentiles after validity rules are applied.
- Financials and Real Estate use sector-specific interpretation for margin, leverage, and cash-flow fields.

## Reproducibility and Bias

- Raw network responses are cached locally and excluded from Git.
- Generated reports record provider, retrieval time, market-data date, fiscal period, and filing date.
- The current S&P 500 list creates survivorship bias. The MVP is a current cross-sectional screener and must not be presented as a historical constituent backtest.
- Any future backtest must use point-in-time constituents and only filings available as of each historical date.

## Model Entry Gate

Factor-model development may start only when:

1. the documented market provider reaches at least 95% usable coverage across the current S&P 500;
2. SEC sector coverage has been measured and applicability rules are documented;
3. the data contract passes schema validation;
4. all data-quality tests pass;
5. no unapproved web-scraped source is required by the pipeline.
