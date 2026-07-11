import pandas as pd

from src.sec_coverage import select_stratified_sample


def test_select_stratified_sample_keeps_equal_sector_counts() -> None:
    rows = []
    for sector in ("A", "B"):
        for index in range(10):
            rows.append(
                {
                    "ticker": f"{sector}{index}",
                    "company_name": f"Company {sector}{index}",
                    "sector": sector,
                    "industry": "Test",
                    "cik": str(index).zfill(10),
                    "yahoo_ticker": f"{sector}{index}",
                    "universe": "sp500",
                }
            )
    universe = pd.DataFrame(rows)

    sample = select_stratified_sample(universe, per_sector=4)

    assert sample.groupby("sector").size().to_dict() == {"A": 4, "B": 4}
    assert sample["ticker"].is_unique
