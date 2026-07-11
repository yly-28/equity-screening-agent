"""Resumable full-universe market-data coverage validation."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from src.twelve_data import TwelveDataApiKeyError, TwelveDataClient, TwelveDataError
from src.universe import load_sp500_universe


@dataclass
class MarketCoverageResult:
    coverage: pd.DataFrame
    summary: Dict[str, object]
    output_path: Path


def assess_price_frame(
    ticker: str,
    frame: pd.DataFrame,
    as_of: date,
) -> Dict[str, object]:
    """Calculate source-independent quality checks for one daily price frame."""

    ordered = frame.sort_values("date").copy()
    returns = ordered["close"].pct_change(fill_method=None)
    latest_date = ordered["date"].max().date()
    duplicate_dates = int(ordered["date"].duplicated().sum())
    missing_ohlcv = int(
        ordered[["open", "high", "low", "close", "volume"]].isna().any(axis=1).sum()
    )
    nonpositive_prices = int(
        (ordered[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
    )
    extreme_moves = int((returns.abs() > 0.50).sum())
    age_days = (as_of - latest_date).days
    usable = (
        len(ordered) >= 180
        and age_days <= 5
        and duplicate_dates == 0
        and missing_ohlcv == 0
        and nonpositive_prices == 0
        and extreme_moves == 0
    )
    return {
        "ticker": ticker,
        "market_data_ok": True,
        "usable_for_model": usable,
        "history_rows": int(len(ordered)),
        "price_data_start": ordered["date"].min().date().isoformat(),
        "price_data_end": latest_date.isoformat(),
        "market_data_age_days": age_days,
        "duplicate_date_count": duplicate_dates,
        "missing_ohlcv_row_count": missing_ohlcv,
        "nonpositive_price_row_count": nonpositive_prices,
        "extreme_daily_move_count": extreme_moves,
        "latest_close": float(ordered["close"].iloc[-1]),
        "price_is_adjusted": bool(ordered["price_is_adjusted"].all()),
        "market_error": None,
    }


def run_market_coverage(
    project_root: Optional[Path] = None,
    as_of: Optional[date] = None,
    tickers: Optional[Sequence[str]] = None,
    refresh: bool = False,
    batch_size: int = 8,
    rate_window_seconds: int = 62,
    demo: bool = False,
) -> MarketCoverageResult:
    """Validate all requested symbols while respecting Twelve Data credit limits."""

    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    run_date = as_of or date.today()
    start = run_date - timedelta(days=400)
    universe = load_sp500_universe(root / "data/raw/sp500_universe.csv")

    if demo:
        requested = ["AAPL"]
    elif tickers is not None:
        requested = list(dict.fromkeys(tickers))
    else:
        requested = universe["ticker"].tolist()

    client = TwelveDataClient(root / "data/cache/twelve_data")
    if not demo and not client.api_key:
        raise TwelveDataApiKeyError(
            "Full market coverage requires TWELVE_DATA_API_KEY. "
            "The runner is ready and will resume from cache after the key is configured."
        )

    symbols_to_fetch = requested if demo else ["SPY", *requested]
    frames: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, str] = {}
    batches = [
        symbols_to_fetch[index : index + batch_size]
        for index in range(0, len(symbols_to_fetch), batch_size)
    ]
    for batch_index, batch in enumerate(batches):
        cached_count = sum(
            client.is_cached(ticker, start, run_date, "all") for ticker in batch
        )
        requires_network = refresh or cached_count < len(batch)
        batch_frames: Dict[str, pd.DataFrame] = {}
        batch_errors: Dict[str, str] = {}
        for attempt in range(1, 4):
            try:
                batch_frames, batch_errors = client.historical_batch(
                    batch,
                    start=start,
                    end=run_date,
                    adjustment="all",
                    refresh=refresh,
                )
                break
            except TwelveDataError as exc:
                if attempt == 3:
                    batch_errors = {ticker: str(exc) for ticker in batch}
                    break
                print(
                    f"Batch {batch_index + 1}/{len(batches)} attempt {attempt} "
                    f"failed: {exc}. Retrying after rate window.",
                    flush=True,
                )
                time.sleep(rate_window_seconds)
        frames.update(batch_frames)
        errors.update(batch_errors)
        print(
            f"Batch {batch_index + 1}/{len(batches)}: "
            f"cached={cached_count}, success={len(batch_frames)}, "
            f"errors={len(batch_errors)}",
            flush=True,
        )
        if requires_network and batch_index < len(batches) - 1:
            time.sleep(rate_window_seconds)

    universe_lookup = universe.set_index("ticker", drop=False)
    records: List[Dict[str, object]] = []
    for ticker in requested:
        base: Dict[str, object] = {"ticker": ticker}
        if ticker in universe_lookup.index:
            row = universe_lookup.loc[ticker]
            base.update(
                {
                    "company_name": row["company_name"],
                    "sector": row["sector"],
                    "industry": row["industry"],
                }
            )
        if ticker in frames:
            base.update(assess_price_frame(ticker, frames[ticker], run_date))
        else:
            base.update(
                {
                    "market_data_ok": False,
                    "usable_for_model": False,
                    "market_error": errors.get(ticker, "No cached or returned data"),
                }
            )
        records.append(base)

    coverage = pd.DataFrame(records).sort_values("ticker").reset_index(drop=True)
    summary: Dict[str, object] = {
        "run_timestamp_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "scope": "demo" if demo else "full" if tickers is None else "custom",
        "provider": "twelve_data",
        "adjustment": "all",
        "as_of": run_date.isoformat(),
        "requested_count": int(len(coverage)),
        "success_count": int(coverage["market_data_ok"].fillna(False).sum()),
        "usable_count": int(coverage["usable_for_model"].fillna(False).sum()),
        "success_rate": float(coverage["market_data_ok"].fillna(False).mean()),
        "usable_rate": float(coverage["usable_for_model"].fillna(False).mean()),
        "exit_criterion_met": bool(
            coverage["usable_for_model"].fillna(False).mean() >= 0.95
        ),
    }

    output_dir = root / "outputs/pre_model_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "demo" if demo else "full" if tickers is None else "custom"
    output_path = output_dir / f"market_coverage_{suffix}.csv"
    coverage.to_csv(output_path, index=False)
    (output_dir / f"market_coverage_{suffix}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return MarketCoverageResult(coverage, summary, output_path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Validate AAPL with demo key")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--rate-window-seconds", type=int, default=62)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = run_market_coverage(
            as_of=args.as_of,
            tickers=args.tickers,
            refresh=args.refresh,
            batch_size=args.batch_size,
            rate_window_seconds=args.rate_window_seconds,
            demo=args.demo,
        )
    except TwelveDataApiKeyError as exc:
        print(f"Blocked: {exc}")
        return 2
    print(json.dumps(result.summary, indent=2))
    print(f"Coverage: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
