# Market Data Provider Decision

Decision date: 2026-07-11

## Decision

Use Twelve Data's documented `/time_series` API as the primary daily market-data provider. Do not issue new automated requests to Nasdaq website endpoints.

## Evidence

- Nasdaq's [Legal page](https://www.nasdaq.com/legal) prohibits automated or manual processes used to capture data from the service. The initial 22-symbol Nasdaq result is retained only as historical feasibility evidence and is not an approved production source.
- Twelve Data's [Basic plan](https://twelvedata.com/pricing) currently provides 8 API credits per minute and 800 credits per day. A current S&P 500 plus SPY validation needs approximately 504 symbol credits, which fits within the daily allowance.
- Twelve Data documents [batch time-series requests](https://support.twelvedata.com/en/articles/5203360-batch-api-requests); each symbol still consumes one credit.
- Twelve Data documents daily price [adjustment behavior](https://support.twelvedata.com/en/articles/5179064-are-the-prices-adjusted). The project requests `adjust=all` and records this in provenance.
- The free account is suitable for latest-available daily research data, not a real-time product.

## Validation Status

The official demo endpoint returned 274 AAPL daily observations for the 400-day validation window through 2026-07-10. Parsing, ordering, OHLCV completeness, adjusted-price metadata, and the market quality gate all passed.

The full 503-security coverage run is implemented and resumable, but it requires a personal `TWELVE_DATA_API_KEY`. At the free 8-credit-per-minute limit, a clean full refresh requires roughly 63 rate windows. Cached tickers are skipped on reruns.

## Security and Usage Rules

- Store the API key only in `TWELVE_DATA_API_KEY`; never commit it.
- Cache responses locally and avoid repeated downloads.
- Do not redistribute raw provider data.
- Recheck plan limits before a full refresh because provider policies may change.
