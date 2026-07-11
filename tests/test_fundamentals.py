import pytest

from src.fundamentals import extract_sec_fundamentals


def _duration_entry(start: str, end: str, value: float) -> dict:
    return {
        "start": start,
        "end": end,
        "val": value,
        "form": "10-K",
        "fp": "FY",
        "filed": f"{int(end[:4]) + 1}-02-01",
    }


def _instant_entry(end: str, value: float) -> dict:
    return {
        "end": end,
        "val": value,
        "form": "10-K",
        "fp": "FY",
        "filed": f"{int(end[:4]) + 1}-02-01",
    }


def test_extract_sec_fundamentals_uses_aligned_annual_periods() -> None:
    payload = {
        "entityName": "Example Corp",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2025-01-31",
                                "val": 1_000_000.0,
                                "form": "10-Q",
                                "filed": "2025-02-15",
                            }
                        ]
                    }
                }
            },
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2022-01-01", "2022-12-31", 90.0)
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2023-01-01", "2023-12-31", 100.0),
                            _duration_entry("2024-01-01", "2024-12-31", 110.0),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [_duration_entry("2024-01-01", "2024-12-31", 22.0)]
                    }
                },
                "StockholdersEquity": {
                    "units": {"USD": [_instant_entry("2024-12-31", 55.0)]}
                },
                "Liabilities": {
                    "units": {"USD": [_instant_entry("2024-12-31", 44.0)]}
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [_duration_entry("2024-01-01", "2024-12-31", 30.0)]
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [_duration_entry("2020-01-01", "2020-12-31", 3.0)]
                    }
                },
                "PaymentsToAcquireProductiveAssets": {
                    "units": {
                        "USD": [_duration_entry("2024-01-01", "2024-12-31", 8.0)]
                    }
                },
            }
        },
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 110.0
    assert result["revenue_growth"] == pytest.approx(0.1)
    assert result["profit_margin"] == pytest.approx(0.2)
    assert result["roe"] == pytest.approx(0.4)
    assert result["liabilities_to_equity"] == pytest.approx(0.8)
    assert result["annual_free_cash_flow"] == 22.0
    assert result["capex_source_tag"] == "PaymentsToAcquireProductiveAssets"
    assert result["shares_outstanding"] == 1_000_000.0
    assert result["shares_outstanding_period_end"] == "2025-01-31"
    assert result["fundamental_period_end"] == "2024-12-31"


def test_nonpositive_equity_invalidates_roe_and_leverage() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [_duration_entry("2024-01-01", "2024-12-31", 100.0)]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [_duration_entry("2024-01-01", "2024-12-31", 20.0)]
                    }
                },
                "StockholdersEquity": {
                    "units": {"USD": [_instant_entry("2024-12-31", -10.0)]}
                },
                "Liabilities": {
                    "units": {"USD": [_instant_entry("2024-12-31", 110.0)]}
                },
                "Assets": {
                    "units": {"USD": [_instant_entry("2024-12-31", 100.0)]}
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["roe"] is None
    assert result["liabilities_to_equity"] is None
    assert result["equity_quality_warning"] == "nonpositive_stockholders_equity"
