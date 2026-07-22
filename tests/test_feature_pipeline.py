from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.feature_pipeline import (
    CacheMode,
    FeaturePipelineConfig,
    build_feature_matrix,
    load_market_histories,
    load_sec_fundamentals,
    resolve_universe,
    run_feature_pipeline,
)
from src.twelve_data import TwelveDataError


def _universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "BBB",
                "company_name": "Beta Corp",
                "sector": "Industrials",
                "industry": "Testing",
                "cik": "0000000002",
                "yahoo_ticker": "BBB",
                "universe": "sp500",
            },
            {
                "ticker": "AAA",
                "company_name": "Alpha Corp",
                "sector": "Technology",
                "industry": "Testing",
                "cik": "0000000001",
                "yahoo_ticker": "AAA",
                "universe": "sp500",
            },
            {
                "ticker": "CCC",
                "company_name": "Gamma Corp",
                "sector": "Health Care",
                "industry": "Testing",
                "cik": "0000000003",
                "yahoo_ticker": "CCC",
                "universe": "sp500",
            },
        ]
    )


def _prices(end: str = "2026-07-10") -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=250)
    close = np.linspace(100.0, 120.0, len(dates))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000.0,
            "price_is_adjusted": True,
        }
    )


class FakeMarketClient:
    def __init__(self, frames, cached=None, errors=None):
        self.frames = frames
        self.cached = set(cached if cached is not None else frames)
        self.errors = errors or {}
        self.historical_calls = []
        self.batch_calls = []

    def is_cached(self, ticker, start, end, adjustment="all"):
        return ticker in self.cached

    def historical(self, ticker, start, end, adjustment="all", refresh=False):
        self.historical_calls.append(ticker)
        if ticker in self.errors:
            raise TwelveDataError(self.errors[ticker])
        return self.frames[ticker].copy()

    def historical_cached(self, ticker, start, end, adjustment="all"):
        return self.historical(
            ticker,
            start,
            end,
            adjustment=adjustment,
            refresh=False,
        )

    def historical_batch(
        self, tickers, start, end, adjustment="all", refresh=False
    ):
        self.batch_calls.append(list(tickers))
        frames = {
            ticker: self.frames[ticker].copy()
            for ticker in tickers
            if ticker in self.frames and ticker not in self.errors
        }
        errors = {
            ticker: self.errors[ticker]
            for ticker in tickers
            if ticker in self.errors
        }
        return frames, errors


class FakeSecClient:
    def __init__(self):
        self.calls = []

    def is_cached(self, cik):
        return True

    def company_facts(self, cik, refresh=False):
        self.calls.append(cik)
        if cik == "0000000002":
            raise RuntimeError("issuer unavailable")
        return {"cik": cik}

    def company_facts_cached(self, cik):
        return self.company_facts(cik, refresh=False)


def _fundamentals(payload, as_of=None):
    return {
        "fundamental_period_end": "2025-12-31",
        "fundamental_filed_date": "2026-02-01",
        "annual_revenue": 100_000_000.0,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income": 10_000_000.0,
        "annual_net_income_period_end": "2025-12-31",
        "revenue_growth": 0.1,
        "profit_margin": 0.1,
        "profit_margin_raw": 0.1,
        "profit_margin_period_end": "2025-12-31",
        "roe": 0.2,
        "roe_period_end": "2025-12-31",
        "liabilities_to_equity": 1.0,
        "leverage_period_end": "2025-12-31",
        "annual_free_cash_flow": 8_000_000.0,
        "free_cash_flow_period_end": "2025-12-31",
        "shares_outstanding": 1_000_000.0,
        "shares_outstanding_period_end": "2026-01-31",
    }


def test_resolve_universe_deduplicates_and_sorts_custom_tickers(tmp_path) -> None:
    cache_path = tmp_path / "data/raw/sp500_universe.csv"
    cache_path.parent.mkdir(parents=True)
    cache_path.touch()
    config = FeaturePipelineConfig(
        project_root=tmp_path,
        as_of=date(2026, 7, 11),
        universe_id="custom",
        tickers=["bbb", "AAA", "BBB"],
        cache_mode=CacheMode.CACHE_ONLY,
    )

    result = resolve_universe(config, loader=lambda *args, **kwargs: _universe())

    assert result["ticker"].tolist() == ["AAA", "BBB"]


def test_cache_only_market_loading_never_requests_missing_symbol() -> None:
    client = FakeMarketClient(
        {"SPY": _prices(), "AAA": _prices()},
        cached={"SPY", "AAA"},
    )

    result = load_market_histories(
        client,
        ["SPY", "AAA", "MISS", "SPY"],
        start=date(2025, 6, 6),
        end=date(2026, 7, 11),
        mode=CacheMode.CACHE_ONLY,
    )

    assert client.historical_calls == ["SPY", "AAA"]
    assert client.batch_calls == []
    assert result.errors["MISS"].startswith("cache_miss")
    assert set(result.frames) == {"SPY", "AAA"}


def test_batch_failure_falls_back_to_isolated_symbol_requests() -> None:
    class BatchFailureClient(FakeMarketClient):
        def historical_batch(
            self, tickers, start, end, adjustment="all", refresh=False
        ):
            self.batch_calls.append(list(tickers))
            raise TwelveDataError("batch unavailable")

    client = BatchFailureClient(
        {"SPY": _prices(), "AAA": _prices()},
        errors={"BBB": "symbol unavailable"},
    )

    result = load_market_histories(
        client,
        ["SPY", "AAA", "BBB"],
        start=date(2025, 6, 6),
        end=date(2026, 7, 11),
        mode=CacheMode.CACHE_FIRST,
        sleep_fn=lambda _: None,
    )

    assert set(result.frames) == {"SPY", "AAA"}
    assert result.errors["BBB"].endswith("symbol unavailable")
    assert client.historical_calls == ["SPY", "AAA", "BBB"]


def test_sec_loading_fetches_shared_cik_once() -> None:
    universe = _universe().iloc[:2].copy()
    universe["cik"] = "0000000001"
    client = FakeSecClient()

    result = load_sec_fundamentals(
        client,
        universe,
        tickers=["AAA", "BBB"],
        as_of=date(2026, 7, 11),
        mode=CacheMode.CACHE_FIRST,
        extractor=_fundamentals,
    )

    assert client.calls == ["0000000001"]
    assert set(result.values) == {"AAA", "BBB"}


def test_build_feature_matrix_isolates_market_and_sec_failures(tmp_path) -> None:
    universe_cache = tmp_path / "data/raw/sp500_universe.csv"
    universe_cache.parent.mkdir(parents=True)
    universe_cache.touch()
    market_client = FakeMarketClient(
        {"SPY": _prices(), "AAA": _prices(), "BBB": _prices()},
        errors={"CCC": "symbol unavailable"},
    )
    sec_client = FakeSecClient()
    config = FeaturePipelineConfig(
        project_root=tmp_path,
        as_of=date(2026, 7, 11),
        cache_mode=CacheMode.CACHE_FIRST,
    )

    build = build_feature_matrix(
        config,
        universe_loader=lambda *args, **kwargs: _universe(),
        market_client=market_client,
        sec_client=sec_client,
        fundamental_extractor=_fundamentals,
        sleep_fn=lambda _: None,
    )

    matrix = build.matrix.set_index("ticker")
    assert build.universe["ticker"].tolist() == ["AAA", "BBB", "CCC"]
    assert market_client.batch_calls == [["SPY", "AAA", "BBB", "CCC"]]
    assert market_client.batch_calls[0].count("SPY") == 1
    assert matrix.loc["AAA", "eligible_for_scoring"]
    assert not matrix.loc["BBB", "eligible_for_scoring"]
    assert matrix.loc["BBB", "fundamental_error"].endswith("issuer unavailable")
    assert "fundamental_data_error" in matrix.loc["BBB", "exclusion_reasons"]
    assert not matrix.loc["CCC", "eligible_for_scoring"]
    assert matrix.loc["CCC", "market_error"] == "symbol unavailable"
    assert "market_data_error" in matrix.loc["CCC", "exclusion_reasons"]


def test_frozen_accepted_run_cannot_be_overwritten(tmp_path) -> None:
    config = FeaturePipelineConfig(
        project_root=tmp_path,
        as_of=date(2026, 7, 13),
        cache_mode=CacheMode.CACHE_ONLY,
    )
    accepted_run_dir = config.processed_dir / config.effective_run_id
    accepted_run_dir.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="frozen accepted run"):
        run_feature_pipeline(
            config,
            universe_loader=lambda *args, **kwargs: pytest.fail(
                "accepted-run protection must execute before any provider load"
            ),
        )
