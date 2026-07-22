from __future__ import annotations

from datetime import date

import pytest

from src.fundamentals import extract_sec_fundamentals


def _duration_entry(
    start: str,
    end: str,
    value: float,
    *,
    filed: str | None = None,
    accn: str | None = None,
    frame: str | None = None,
) -> dict:
    entry = {
        "start": start,
        "end": end,
        "val": value,
        "form": "10-K",
        "fp": "FY",
        "filed": filed or f"{int(end[:4]) + 1}-02-01",
    }
    if accn is not None:
        entry["accn"] = accn
    if frame is not None:
        entry["frame"] = frame
    return entry


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
    assert result["annual_revenue_period_end"] == "2024-12-31"
    assert result["annual_net_income_period_end"] == "2024-12-31"


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


def test_extract_sec_fundamentals_respects_filing_cutoff() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2023-01-01", "2023-12-31", 100.0),
                            _duration_entry("2024-01-01", "2024-12-31", 120.0),
                        ]
                    }
                }
            }
        }
    }

    result = extract_sec_fundamentals(payload, as_of=date(2025, 1, 15))

    assert result["annual_revenue"] == 100.0
    assert result["fundamental_period_end"] == "2023-12-31"
    assert result["fundamental_filed_date"] == "2024-02-01"


def test_revenue_selection_uses_including_assessed_tax_as_fallback() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2023-01-01", "2023-12-31", 200.0)
                        ]
                    }
                },
                "RevenueFromContractWithCustomerIncludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 100.0),
                            _duration_entry("2025-01-01", "2025-12-31", 120.0),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 24.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 120.0
    assert result["revenue_growth"] == pytest.approx(0.2)
    assert result["profit_margin"] == pytest.approx(0.2)
    assert result["revenue_source_tag"] == (
        "RevenueFromContractWithCustomerIncludingAssessedTax"
    )


def test_revenue_selection_prefers_broad_total_over_contract_component() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 90.0),
                            _duration_entry("2025-01-01", "2025-12-31", 100.0),
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 9.0),
                            _duration_entry("2025-01-01", "2025-12-31", 10.0),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 20.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 100.0
    assert result["profit_margin"] == pytest.approx(0.2)
    assert result["revenue_source_tag"] == "Revenues"


@pytest.mark.parametrize(
    ("broad_value", "expected_warning"),
    [
        (110.0, "revenue_source_review"),
        (90.0, "revenue_source_conflict"),
    ],
)
def test_revenue_selection_keeps_baseline_for_nonmaterial_or_lower_broad_value(
    broad_value: float,
    expected_warning: str,
) -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", broad_value)
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 100.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 100.0
    assert result["revenue_source_tag"] == (
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert result["revenue_basis_warning"] == expected_warning


def test_revenue_selection_builds_aligned_bank_net_revenue() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "InterestIncomeExpenseNet": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 50.0),
                            _duration_entry("2025-01-01", "2025-12-31", 60.0),
                        ]
                    }
                },
                "NoninterestIncome": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 20.0),
                            _duration_entry("2025-01-01", "2025-12-31", 20.0),
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 10.0)
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 16.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 80.0
    assert result["revenue_growth"] == pytest.approx(80.0 / 70.0 - 1)
    assert result["profit_margin"] == pytest.approx(0.2)
    assert result["revenue_source_tag"] == (
        "InterestIncomeExpenseNet+NoninterestIncome"
    )


def test_revenue_composite_rejects_mixed_accessions() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "InterestIncomeExpenseNet": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01",
                                "2025-12-31",
                                60.0,
                                accn="0001",
                                frame="CY2025",
                            )
                        ]
                    }
                },
                "NoninterestIncome": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01",
                                "2025-12-31",
                                20.0,
                                accn="0002",
                                frame="CY2025",
                            )
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 10.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 10.0
    assert result["revenue_source_tag"] == (
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )


def test_revenue_selection_combines_lease_and_contract_income() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "OperatingLeaseLeaseIncome": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 90.0),
                            _duration_entry("2025-01-01", "2025-12-31", 100.0),
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 9.0),
                            _duration_entry("2025-01-01", "2025-12-31", 10.0),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 22.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 110.0
    assert result["profit_margin"] == pytest.approx(0.2)
    assert result["revenue_source_tag"] == (
        "OperatingLeaseLeaseIncome+ContractRevenue"
    )


def test_equity_warning_matches_final_ratio_validity() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 20.0)
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            _instant_entry("2024-12-31", -10.0),
                            _instant_entry("2025-12-31", 50.0),
                        ]
                    }
                },
                "Liabilities": {
                    "units": {"USD": [_instant_entry("2024-12-31", 110.0)]}
                },
                "Assets": {
                    "units": {"USD": [_instant_entry("2025-12-31", 150.0)]}
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["roe"] == pytest.approx(0.4)
    assert result["liabilities_to_equity"] == pytest.approx(2.0)
    assert result["equity_quality_warning"] is None


def test_regulated_operating_revenue_uses_current_same_basis_history() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "RegulatedAndUnregulatedOperatingRevenue": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2024-01-01", "2024-12-31", 12_457_000_000.0
                            ),
                            _duration_entry(
                                "2025-01-01", "2025-12-31", 15_814_000_000.0
                            ),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01", "2025-12-31", 1_462_000_000.0
                            )
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 15_814_000_000.0
    assert result["annual_revenue_period_end"] == "2025-12-31"
    assert result["revenue_growth"] == pytest.approx(
        15_814_000_000.0 / 12_457_000_000.0 - 1
    )
    assert result["profit_margin"] == pytest.approx(
        1_462_000_000.0 / 15_814_000_000.0
    )
    assert result["revenue_source_tag"] == (
        "RegulatedAndUnregulatedOperatingRevenue"
    )


def test_regulated_operating_revenue_does_not_override_canonical_total() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 200.0),
                            _duration_entry("2025-01-01", "2025-12-31", 220.0),
                        ]
                    }
                },
                "RegulatedAndUnregulatedOperatingRevenue": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 125.0),
                            _duration_entry("2025-01-01", "2025-12-31", 158.0),
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 220.0
    assert result["revenue_growth"] == pytest.approx(0.1)
    assert result["revenue_source_tag"] == "Revenues"


def test_regulated_total_wins_over_including_tax_with_review_warning() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "RegulatedAndUnregulatedOperatingRevenue": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 100.0),
                            _duration_entry("2025-01-01", "2025-12-31", 110.0),
                        ]
                    }
                },
                "RevenueFromContractWithCustomerIncludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 91.0),
                            _duration_entry("2025-01-01", "2025-12-31", 100.0),
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 110.0
    assert result["annual_revenue_period_end"] == "2025-12-31"
    assert result["revenue_growth"] == pytest.approx(0.1)
    assert result["revenue_source_tag"] == (
        "RegulatedAndUnregulatedOperatingRevenue"
    )
    assert result["revenue_basis_warning"] == "revenue_source_review"


@pytest.mark.parametrize(
    ("regulated_value", "including_tax_value", "expected_warning"),
    [
        (105.0, 100.0, None),
        (120.0, 100.0, "broad_total_material_override"),
        (90.0, 100.0, "revenue_source_conflict"),
    ],
)
def test_regulated_total_vs_including_tax_warning_thresholds(
    regulated_value: float,
    including_tax_value: float,
    expected_warning: str | None,
) -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "RegulatedAndUnregulatedOperatingRevenue": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01", "2025-12-31", regulated_value
                            )
                        ]
                    }
                },
                "RevenueFromContractWithCustomerIncludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01", "2025-12-31", including_tax_value
                            )
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == regulated_value
    assert result["revenue_source_tag"] == (
        "RegulatedAndUnregulatedOperatingRevenue"
    )
    assert result["revenue_basis_warning"] == expected_warning


def test_common_stockholder_net_income_is_current_same_basis_fallback() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01", "2025-12-31", 26_917_000_000.0
                            )
                        ]
                    }
                },
                "ProfitLoss": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2015-01-01", "2015-12-31", 2_551_000_000.0
                            )
                        ]
                    }
                },
                "NetIncomeLossAvailableToCommonStockholdersBasic": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2024-01-01", "2024-12-31", 5_882_000_000.0
                            ),
                            _duration_entry(
                                "2025-01-01", "2025-12-31", 5_404_000_000.0
                            ),
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_net_income"] == 5_404_000_000.0
    assert result["annual_net_income_period_end"] == "2025-12-31"
    assert result["profit_margin"] == pytest.approx(
        5_404_000_000.0 / 26_917_000_000.0
    )
    assert result["net_income_source_tag"] == (
        "NetIncomeLossAvailableToCommonStockholdersBasic"
    )


@pytest.mark.parametrize("canonical_tag", ["NetIncomeLoss", "ProfitLoss"])
def test_common_stockholder_net_income_does_not_override_canonical_tag(
    canonical_tag: str,
) -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 100.0)
                        ]
                    }
                },
                canonical_tag: {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 30.0)
                        ]
                    }
                },
                "NetIncomeLossAvailableToCommonStockholdersBasic": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 999.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_net_income"] == 30.0
    assert result["profit_margin"] == pytest.approx(0.3)
    assert result["net_income_source_tag"] == canonical_tag


def test_operating_lease_income_is_guarded_current_period_fallback() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2019-01-01", "2019-12-31", 2_700.0)
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _duration_entry("2019-01-01", "2019-12-31", 10.0)
                        ]
                    }
                },
                "OperatingLeaseLeaseIncome": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2024-01-01", "2024-12-31", 2_980_108_000.0
                            ),
                            _duration_entry(
                                "2025-01-01", "2025-12-31", 3_093_959_000.0
                            ),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01", "2025-12-31", 1_120_089_000.0
                            )
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 3_093_959_000.0
    assert result["annual_revenue_period_end"] == "2025-12-31"
    assert result["revenue_growth"] == pytest.approx(
        3_093_959_000.0 / 2_980_108_000.0 - 1
    )
    assert result["profit_margin"] == pytest.approx(
        1_120_089_000.0 / 3_093_959_000.0
    )
    assert result["revenue_source_tag"] == "OperatingLeaseLeaseIncome"
    assert result["revenue_basis_warning"] == "operating_lease_income_only"


def test_operating_lease_income_does_not_override_canonical_total() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 200.0),
                            _duration_entry("2025-01-01", "2025-12-31", 220.0),
                        ]
                    }
                },
                "OperatingLeaseLeaseIncome": {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 180.0),
                            _duration_entry("2025-01-01", "2025-12-31", 190.0),
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] == 220.0
    assert result["revenue_growth"] == pytest.approx(0.1)
    assert result["revenue_source_tag"] == "Revenues"


@pytest.mark.parametrize(
    "component_tag",
    [
        "ContractWithCustomerLiabilityRevenueRecognized",
        "ContractWithCustomerPerformanceObligationSatisfiedInPreviousPeriod",
    ],
)
def test_revenue_components_are_not_treated_as_total_revenue(
    component_tag: str,
) -> None:
    payload = {
        "facts": {
            "us-gaap": {
                component_tag: {
                    "units": {
                        "USD": [
                            _duration_entry("2024-01-01", "2024-12-31", 100.0),
                            _duration_entry("2025-01-01", "2025-12-31", 134.0),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry("2025-01-01", "2025-12-31", 20.0)
                        ]
                    }
                },
            }
        }
    }

    result = extract_sec_fundamentals(payload)

    assert result["annual_revenue"] is None
    assert result["annual_revenue_period_end"] is None
    assert result["revenue_growth"] is None
    assert result["profit_margin"] is None
    assert result["revenue_source_tag"] is None
