import numpy as np
import pandas as pd

from src.features import compute_market_features


def test_compute_market_features_with_matching_benchmark() -> None:
    dates = pd.bdate_range("2025-01-02", periods=180)
    close = 100 * np.power(1.001, np.arange(len(dates)))
    prices = pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "volume": np.linspace(1_000_000, 1_200_000, len(dates)),
        }
    )

    features = compute_market_features(prices, prices)

    assert features["history_rows"] == 180
    assert features["return_1m"] > 0
    assert features["max_drawdown_1y"] == 0
    assert abs(features["beta_1y"] - 1.0) < 1e-10
    assert abs(features["relative_strength_3m"]) < 1e-12
    assert features["extreme_daily_move_count"] == 0
