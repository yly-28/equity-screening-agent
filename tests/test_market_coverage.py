import numpy as np
import pandas as pd

from src.market_coverage import assess_price_frame


def test_assess_price_frame_accepts_clean_one_year_history() -> None:
    dates = pd.bdate_range(end="2026-07-10", periods=250)
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": np.linspace(100, 120, len(dates)),
            "high": np.linspace(101, 121, len(dates)),
            "low": np.linspace(99, 119, len(dates)),
            "close": np.linspace(100, 120, len(dates)),
            "volume": 1_000_000,
            "price_is_adjusted": True,
        }
    )

    result = assess_price_frame("TEST", frame, pd.Timestamp("2026-07-11").date())

    assert result["market_data_ok"] is True
    assert result["usable_for_model"] is True
    assert result["history_rows"] == 250
    assert result["market_data_age_days"] == 1
