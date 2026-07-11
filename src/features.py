"""Market feature engineering used by feasibility checks and later screening."""

from __future__ import annotations

from math import sqrt
from typing import Dict, Optional

import numpy as np
import pandas as pd


def _trailing_return(close: pd.Series, periods: int) -> float:
    if len(close) <= periods:
        return float("nan")
    return float(close.iloc[-1] / close.iloc[-periods - 1] - 1)


def compute_market_features(
    prices: pd.DataFrame,
    benchmark_prices: Optional[pd.DataFrame] = None,
) -> Dict[str, object]:
    """Calculate a compact set of features from ascending daily OHLCV data."""

    required = {"date", "close", "volume"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price frame is missing required columns: {sorted(missing)}")

    clean = prices.copy().sort_values("date")
    clean = clean.dropna(subset=["date", "close"])
    close = clean["close"].astype(float)
    volume = clean["volume"].astype(float)
    daily_returns = close.pct_change(fill_method=None)

    rolling_peak = close.cummax()
    drawdown = close / rolling_peak - 1
    volatility_20d = daily_returns.tail(20).std(ddof=1) * sqrt(252)
    volatility_60d = daily_returns.tail(60).std(ddof=1) * sqrt(252)
    ma20 = close.tail(20).mean()
    ma50 = close.tail(50).mean()
    volume_20 = volume.tail(20).mean()
    volume_60 = volume.tail(60).mean()

    beta_1y = float("nan")
    relative_strength_3m = float("nan")
    if benchmark_prices is not None and not benchmark_prices.empty:
        benchmark = benchmark_prices[["date", "close"]].copy()
        benchmark = benchmark.rename(columns={"close": "benchmark_close"})
        merged = clean[["date", "close"]].merge(benchmark, on="date", how="inner")
        if len(merged) > 63:
            stock_return_3m = _trailing_return(merged["close"], 63)
            benchmark_return_3m = _trailing_return(merged["benchmark_close"], 63)
            relative_strength_3m = stock_return_3m - benchmark_return_3m
        return_frame = merged[["close", "benchmark_close"]].pct_change(
            fill_method=None
        ).dropna()
        if len(return_frame) >= 60:
            benchmark_variance = return_frame["benchmark_close"].var(ddof=1)
            if benchmark_variance > 0:
                beta_1y = (
                    return_frame["close"].cov(return_frame["benchmark_close"])
                    / benchmark_variance
                )

    return {
        "price_data_start": clean["date"].iloc[0].date().isoformat(),
        "price_data_end": clean["date"].iloc[-1].date().isoformat(),
        "history_rows": int(len(clean)),
        "price": float(close.iloc[-1]),
        "return_1d": _trailing_return(close, 1),
        "return_1m": _trailing_return(close, 21),
        "return_3m": _trailing_return(close, 63),
        "return_6m": _trailing_return(close, 126),
        "volatility_20d": float(volatility_20d),
        "volatility_60d": float(volatility_60d),
        "max_drawdown_1y": float(drawdown.min()),
        "ma20_gap": float(close.iloc[-1] / ma20 - 1),
        "ma50_gap": float(close.iloc[-1] / ma50 - 1),
        "average_volume_20d": float(volume_20),
        "volume_trend": float(volume_20 / volume_60 - 1)
        if volume_60 and not np.isnan(volume_60)
        else float("nan"),
        "relative_strength_3m": float(relative_strength_3m),
        "beta_1y": float(beta_1y),
        "extreme_daily_move_count": int((daily_returns.abs() > 0.50).sum()),
        "unadjusted_price_warning": True,
    }
