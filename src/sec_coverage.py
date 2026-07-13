"""Stratified SEC Company Facts coverage validation before factor modeling."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from src.fundamentals import (
    FundamentalDataError,
    SecCompanyFactsClient,
    extract_sec_fundamentals,
)
from src.universe import load_sp500_universe


ANCHOR_TICKERS = (
    "GOOGL",
    "META",
    "AMZN",
    "TSLA",
    "COST",
    "PG",
    "XOM",
    "CVX",
    "JPM",
    "BRK.B",
    "JNJ",
    "UNH",
    "CAT",
    "GE",
    "AAPL",
    "MSFT",
    "LIN",
    "SHW",
    "AMT",
    "PLD",
    "NEE",
    "DUK",
)

FUNDAMENTAL_FIELDS = (
    "annual_revenue",
    "annual_net_income",
    "stockholders_equity",
    "total_assets",
    "total_liabilities",
    "annual_operating_cash_flow",
    "annual_capex",
    "annual_free_cash_flow",
    "annual_diluted_eps",
    "shares_outstanding",
    "revenue_growth",
    "profit_margin",
    "roe",
    "liabilities_to_equity",
)


def select_stratified_sample(
    universe: pd.DataFrame,
    per_sector: int = 8,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Select deterministic sector samples while retaining validated anchors."""

    selected: List[pd.DataFrame] = []
    anchor_set = set(ANCHOR_TICKERS)
    for sector_index, (sector, group) in enumerate(
        universe.groupby("sector", sort=True)
    ):
        anchors = group[group["ticker"].isin(anchor_set)].sort_values("ticker")
        anchors = anchors.head(per_sector)
        remaining_count = per_sector - len(anchors)
        candidates = group[~group["ticker"].isin(anchors["ticker"])]
        if remaining_count > 0:
            sampled = candidates.sample(
                n=min(remaining_count, len(candidates)),
                random_state=random_seed + sector_index,
            )
            sector_sample = pd.concat([anchors, sampled], ignore_index=True)
        else:
            sector_sample = anchors
        selected.append(sector_sample)
    return (
        pd.concat(selected, ignore_index=True)
        .sort_values(["sector", "ticker"])
        .reset_index(drop=True)
    )


def _overall_coverage(rows: pd.DataFrame) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    total = len(rows)
    for field in FUNDAMENTAL_FIELDS:
        available = int(rows[field].notna().sum())
        missing_rate = 1 - available / total if total else 1.0
        status = "strong" if missing_rate <= 0.10 else "usable" if missing_rate <= 0.30 else "weak"
        records.append(
            {
                "field": field,
                "available_count": available,
                "sample_count": total,
                "missing_rate": missing_rate,
                "status": status,
            }
        )
    return pd.DataFrame(records)


def _sector_coverage(rows: pd.DataFrame) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    for sector, group in rows.groupby("sector", sort=True):
        for field in FUNDAMENTAL_FIELDS:
            available = int(group[field].notna().sum())
            total = int(len(group))
            records.append(
                {
                    "sector": sector,
                    "field": field,
                    "available_count": available,
                    "sample_count": total,
                    "missing_rate": 1 - available / total if total else 1.0,
                }
            )
    return pd.DataFrame(records)


def run_sec_coverage(
    project_root: Optional[Path] = None,
    as_of: Optional[date] = None,
    per_sector: int = 8,
    refresh: bool = False,
) -> Dict[str, object]:
    """Run a deterministic, cached SEC coverage audit across every GICS sector."""

    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    run_date = as_of or date.today()
    universe = load_sp500_universe(root / "data/raw/sp500_universe.csv")
    sample = select_stratified_sample(universe, per_sector=per_sector)
    sec = SecCompanyFactsClient(root / "data/cache/sec", pause_seconds=0.20)

    records: List[Dict[str, object]] = []
    for row in sample.itertuples(index=False):
        record: Dict[str, object] = {
            "ticker": row.ticker,
            "company_name": row.company_name,
            "sector": row.sector,
            "industry": row.industry,
            "cik": row.cik,
            "sec_fetch_ok": False,
            "core_extraction_ok": False,
            "fundamental_error": None,
        }
        try:
            payload = sec.company_facts(str(row.cik), refresh=refresh)
            record["sec_fetch_ok"] = True
            fundamentals = extract_sec_fundamentals(payload)
            record.update(fundamentals)
            record["core_extraction_ok"] = all(
                fundamentals.get(field) is not None
                for field in (
                    "annual_revenue",
                    "annual_net_income",
                    "stockholders_equity",
                    "total_assets",
                )
            )
        except FundamentalDataError as exc:
            record["fundamental_error"] = str(exc)
        records.append(record)

    results = pd.DataFrame(records).sort_values(["sector", "ticker"]).reset_index(drop=True)
    for field in FUNDAMENTAL_FIELDS:
        if field not in results:
            results[field] = pd.NA
    results["fundamental_age_days"] = (
        pd.Timestamp(run_date)
        - pd.to_datetime(results["fundamental_period_end"], errors="coerce")
    ).dt.days
    overall = _overall_coverage(results)
    sector = _sector_coverage(results)

    summary: Dict[str, object] = {
        "run_timestamp_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "as_of": run_date.isoformat(),
        "sample_count": int(len(results)),
        "sector_count": int(results["sector"].nunique()),
        "per_sector": per_sector,
        "sec_fetch_success_count": int(results["sec_fetch_ok"].sum()),
        "core_success_count": int(results["core_extraction_ok"].sum()),
        "median_fundamental_age_days": int(results["fundamental_age_days"].median()),
        "max_fundamental_age_days": int(results["fundamental_age_days"].max()),
    }

    output_dir = root / "outputs/pre_model_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_dir / "sec_validation_sample.csv", index=False)
    overall.to_csv(output_dir / "sec_field_coverage.csv", index=False)
    sector.to_csv(output_dir / "sec_sector_coverage.csv", index=False)
    summary_path = output_dir / "sec_coverage_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return {
        "results": results,
        "overall_coverage": overall,
        "sector_coverage": sector,
        "summary": summary,
        "summary_path": summary_path,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--per-sector", type=int, default=8)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_sec_coverage(
        as_of=args.as_of,
        per_sector=args.per_sector,
        refresh=args.refresh,
    )
    print(json.dumps(result["summary"], indent=2))
    print(f"Summary: {result['summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
