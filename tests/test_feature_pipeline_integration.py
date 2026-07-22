import json
from datetime import date

import numpy as np
import pandas as pd

import src.feature_pipeline as feature_pipeline
from src.feature_pipeline import main
from src.fundamentals import SecCompanyFactsClient
from src.twelve_data import TwelveDataClient


def _market_payload() -> dict:
    dates = pd.bdate_range(end="2026-07-10", periods=250)
    close = np.linspace(100.0, 120.0, len(dates))
    values = []
    for timestamp, price in zip(dates, close):
        values.append(
            {
                "datetime": timestamp.strftime("%Y-%m-%d"),
                "open": str(price),
                "high": str(price + 1),
                "low": str(price - 1),
                "close": str(price),
                "volume": "1000000",
            }
        )
    return {"status": "ok", "values": values}


def _duration_entry(start: str, end: str, value: float, filed: str) -> dict:
    return {
        "start": start,
        "end": end,
        "val": value,
        "form": "10-K",
        "fp": "FY",
        "filed": filed,
    }


def _instant_entry(end: str, value: float, filed: str) -> dict:
    return {
        "end": end,
        "val": value,
        "form": "10-K",
        "fp": "FY",
        "filed": filed,
    }


def _sec_payload() -> dict:
    filed = "2026-02-01"
    return {
        "entityName": "Alpha Corp",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2025-12-31",
                                "val": 1_000_000.0,
                                "form": "10-K",
                                "filed": filed,
                            }
                        ]
                    }
                }
            },
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2024-01-01",
                                "2024-12-31",
                                90_000_000.0,
                                "2025-02-01",
                            ),
                            _duration_entry(
                                "2025-01-01",
                                "2025-12-31",
                                100_000_000.0,
                                filed,
                            ),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01",
                                "2025-12-31",
                                10_000_000.0,
                                filed,
                            )
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [_instant_entry("2025-12-31", 50_000_000.0, filed)]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [_instant_entry("2025-12-31", 40_000_000.0, filed)]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01",
                                "2025-12-31",
                                12_000_000.0,
                                filed,
                            )
                        ]
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            _duration_entry(
                                "2025-01-01",
                                "2025-12-31",
                                2_000_000.0,
                                filed,
                            )
                        ]
                    }
                },
            },
        },
    }


def test_cli_runs_end_to_end_from_caches_without_network(
    tmp_path, monkeypatch, capsys
) -> None:
    universe_path = tmp_path / "data/raw/sp500_universe.csv"
    universe_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "company_name": "Alpha Corp",
                "sector": "Industrials",
                "industry": "Testing",
                "cik": "0000000001",
                "yahoo_ticker": "AAA",
                "universe": "sp500",
            }
        ]
    ).to_csv(universe_path, index=False)

    run_date = date(2026, 7, 11)
    start_date = date(2025, 6, 6)
    market_client = TwelveDataClient(
        tmp_path / "data/cache/twelve_data",
        api_key="not-used",
    )
    for ticker in ("SPY", "AAA"):
        market_client._write_cached_payload(
            ticker,
            start_date,
            run_date,
            "all",
            _market_payload(),
        )
    sec_client = SecCompanyFactsClient(tmp_path / "data/cache/sec")
    sec_cache = sec_client.cache_dir / "CIK0000000001.json"
    sec_cache.parent.mkdir(parents=True)
    sec_cache.write_text(json.dumps(_sec_payload()), encoding="utf-8")

    def fail_network(*args, **kwargs):
        raise AssertionError("network access is forbidden in this integration test")

    market_client.session.get = fail_network
    sec_client.session.get = fail_network
    monkeypatch.setattr(
        feature_pipeline,
        "TwelveDataClient",
        lambda cache_dir: market_client,
    )
    monkeypatch.setattr(
        feature_pipeline,
        "SecCompanyFactsClient",
        lambda cache_dir: sec_client,
    )

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "--as-of",
            run_date.isoformat(),
            "--tickers",
            "AAA",
            "--cache-only",
            "--run-id",
            "cached_integration",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["acceptance_passed"] is True
    run_dir = tmp_path / "data/processed/cached_integration"
    matrix = pd.read_parquet(run_dir / "feature_matrix.parquet")
    assert matrix["ticker"].tolist() == ["AAA"]
    assert matrix["eligible_for_scoring"].tolist() == [True]
    assert (run_dir / "matrix_quality.json").exists()
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    quality = json.loads((run_dir / "matrix_quality.json").read_text())
    assert metadata["contract_version"] == "1.0.0"
    assert metadata["contract_status"] == "frozen_v1"
    assert quality["run"] == metadata
