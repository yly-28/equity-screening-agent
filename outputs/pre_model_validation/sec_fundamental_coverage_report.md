# SEC Fundamental Coverage Report

Generated: 2026-07-11T07:12:05+00:00<br>
Sample: 88 current S&P 500 securities, 8 per sector

## Result

- SEC retrieval success: 88/88
- Core extraction success: 88/88
- Median fundamental age: 192 days
- Oldest fundamental age: 379 days

## Overall Field Coverage

| field | available_count | sample_count | missing_rate | status |
| --- | --- | --- | --- | --- |
| annual_revenue | 88 | 88 | 0.0% | strong |
| annual_net_income | 88 | 88 | 0.0% | strong |
| stockholders_equity | 88 | 88 | 0.0% | strong |
| total_assets | 88 | 88 | 0.0% | strong |
| total_liabilities | 88 | 88 | 0.0% | strong |
| annual_operating_cash_flow | 88 | 88 | 0.0% | strong |
| annual_capex | 80 | 88 | 9.1% | strong |
| annual_free_cash_flow | 80 | 88 | 9.1% | strong |
| annual_diluted_eps | 87 | 88 | 1.1% | strong |
| shares_outstanding | 77 | 88 | 12.5% | usable |
| revenue_growth | 88 | 88 | 0.0% | strong |
| profit_margin | 88 | 88 | 0.0% | strong |
| roe | 86 | 88 | 2.3% | strong |
| liabilities_to_equity | 86 | 88 | 2.3% | strong |

## Material Sector Gaps

The table lists sector/field combinations with at least 25% missing values.

| sector | field | available_count | sample_count | missing_rate |
| --- | --- | --- | --- | --- |
| Financials | annual_capex | 6 | 8 | 25.0% |
| Real Estate | annual_capex | 5 | 8 | 37.5% |
| Financials | annual_free_cash_flow | 6 | 8 | 25.0% |
| Real Estate | annual_free_cash_flow | 5 | 8 | 37.5% |
| Communication Services | shares_outstanding | 2 | 8 | 75.0% |
| Financials | shares_outstanding | 6 | 8 | 25.0% |

## Model Input Decisions

- Revenue growth, profit margin, ROE, and liabilities-to-equity may enter the general quality layer only if their final coverage remains strong.
- Free cash flow is optional. It must not penalize financials, REITs, or utilities when unavailable or economically inappropriate.
- Missing values remain null; factor weights are renormalized over applicable fields.
- Every derived ratio carries its fiscal period end and source tag for auditability.
- Financials and real estate require sector-specific interpretation even when a numeric value exists.
- The current-universe sample is suitable for a cross-sectional screener, not a survivorship-bias-free historical backtest.
