"""Production orchestration for the Phase 2 feature matrix."""

from __future__ import annotations

import argparse
import json
import time
from hashlib import sha256
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence

import pandas as pd
import pyarrow

from src.fundamentals import (
    SecCompanyFactsClient,
    extract_sec_fundamentals,
)
from src.market_coverage import assess_price_frame
from src.matrix_quality import (
    ArtifactPaths,
    MatrixQuality,
    analyze_feature_matrix,
    write_quality_artifacts,
)
from src.twelve_data import TwelveDataClient, TwelveDataError
from src.unified_data import (
    DATA_CONTRACT,
    FIELD_SECTIONS,
    build_unified_feature_row,
)
from src.universe import UniverseDataError, load_sp500_universe


class CacheMode(str, Enum):
    """Network and cache behavior for provider reads."""

    CACHE_FIRST = "cache_first"
    CACHE_ONLY = "cache_only"
    REFRESH = "refresh"


@dataclass(frozen=True)
class FeaturePipelineConfig:
    """Runtime inputs for one reproducible feature-matrix build."""

    project_root: Path
    as_of: date
    universe_id: str = "sp500"
    tickers: Optional[Sequence[str]] = None
    cache_mode: CacheMode = CacheMode.CACHE_FIRST
    market_history_days: int = 400
    market_batch_size: int = 8
    market_rate_window_seconds: float = 62.0
    output_dir: Optional[Path] = None
    run_id: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root).resolve())
        object.__setattr__(self, "cache_mode", CacheMode(self.cache_mode))
        object.__setattr__(self, "universe_id", self.universe_id.strip().lower())
        if self.output_dir is not None:
            object.__setattr__(self, "output_dir", Path(self.output_dir).resolve())
        if self.tickers is not None:
            normalized = tuple(
                sorted(
                    {
                        str(ticker).strip().upper()
                        for ticker in self.tickers
                        if str(ticker).strip()
                    }
                )
            )
            object.__setattr__(self, "tickers", normalized)
        if self.universe_id not in {"sp500", "custom"}:
            raise ValueError(f"Unsupported universe: {self.universe_id}")
        if self.universe_id == "custom" and not self.tickers:
            raise ValueError("The custom universe requires at least one ticker")
        if self.market_history_days < 180:
            raise ValueError("market_history_days must be at least 180")
        if self.market_batch_size < 1:
            raise ValueError("market_batch_size must be positive")
        if self.run_id is not None and (
            not self.run_id
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for character in self.run_id
            )
        ):
            raise ValueError("run_id may contain only letters, numbers, '.', '_', and '-'")

    @property
    def market_start(self) -> date:
        return self.as_of - timedelta(days=self.market_history_days)

    @property
    def processed_dir(self) -> Path:
        return self.output_dir or self.project_root / "data/processed"

    @property
    def effective_run_id(self) -> str:
        if self.run_id:
            return self.run_id
        version = str(DATA_CONTRACT["contract"]["version"]).replace(".", "_")
        scope = self.universe_id
        if self.tickers:
            digest = sha256(",".join(self.tickers).encode("utf-8")).hexdigest()[:8]
            scope = f"{scope}_{digest}"
        return f"{self.as_of.isoformat()}_{scope}_v{version}"


@dataclass
class MarketLoadResult:
    frames: Dict[str, pd.DataFrame] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    network_batches: int = 0


@dataclass
class FundamentalLoadResult:
    values: Dict[str, Dict[str, object]] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    skipped: Dict[str, str] = field(default_factory=dict)


@dataclass
class FeaturePipelineBuild:
    matrix: pd.DataFrame
    universe: pd.DataFrame
    market: MarketLoadResult
    fundamentals: FundamentalLoadResult
    benchmark_error: Optional[str]


@dataclass
class FeaturePipelineResult:
    build: FeaturePipelineBuild
    quality: MatrixQuality
    artifacts: ArtifactPaths


UniverseLoader = Callable[..., pd.DataFrame]
SleepFunction = Callable[[float], None]
FundamentalExtractor = Callable[..., Dict[str, object]]


def _safe_error(exc: BaseException) -> str:
    message = str(exc).strip() or "No detail available"
    return f"{type(exc).__name__}: {message}"


def resolve_universe(
    config: FeaturePipelineConfig,
    loader: UniverseLoader = load_sp500_universe,
) -> pd.DataFrame:
    """Resolve a deterministic current-S&P-500 universe or subset."""

    cache_path = config.project_root / "data/raw/sp500_universe.csv"
    if config.cache_mode == CacheMode.CACHE_ONLY and not cache_path.exists():
        raise UniverseDataError(f"Universe cache miss: {cache_path}")
    universe = loader(
        cache_path,
        refresh=config.cache_mode == CacheMode.REFRESH,
        cache_only=config.cache_mode == CacheMode.CACHE_ONLY,
    ).copy()
    universe["ticker"] = universe["ticker"].astype(str).str.strip().str.upper()
    universe = universe.drop_duplicates("ticker", keep="first")

    if config.tickers:
        requested = list(config.tickers)
        known = set(universe["ticker"])
        unknown = sorted(set(requested) - known)
        if unknown:
            raise UniverseDataError(
                "Custom tickers are not present in the current S&P 500 cache: "
                + ", ".join(unknown)
            )
        universe = universe[universe["ticker"].isin(requested)]

    return universe.sort_values("ticker").reset_index(drop=True)


def _network_required(
    client: TwelveDataClient,
    symbols: Sequence[str],
    start: date,
    end: date,
    mode: CacheMode,
) -> bool:
    return mode == CacheMode.REFRESH or any(
        not client.is_cached(symbol, start, end, "all") for symbol in symbols
    )


def _load_market_symbol(
    client: TwelveDataClient,
    symbol: str,
    start: date,
    end: date,
    refresh: bool,
) -> pd.DataFrame:
    frame = client.historical(
        symbol,
        start=start,
        end=end,
        adjustment="all",
        refresh=refresh,
    )
    dated = frame.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated[dated["date"].dt.date <= end]
    if dated.empty:
        raise TwelveDataError(f"No market rows on or before {end} for {symbol}")
    return dated.sort_values("date").reset_index(drop=True)


def _load_cached_market_symbol(
    client: TwelveDataClient,
    symbol: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    frame = client.historical_cached(
        symbol,
        start=start,
        end=end,
        adjustment="all",
    )
    dated = frame.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated[dated["date"].dt.date <= end]
    if dated.empty:
        raise TwelveDataError(f"No cached market rows on or before {end} for {symbol}")
    return dated.sort_values("date").reset_index(drop=True)


def load_market_histories(
    client: TwelveDataClient,
    symbols: Sequence[str],
    start: date,
    end: date,
    mode: CacheMode,
    batch_size: int = 8,
    rate_window_seconds: float = 62.0,
    sleep_fn: SleepFunction = time.sleep,
) -> MarketLoadResult:
    """Load exact-date market histories with batch and symbol failure isolation."""

    requested = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    result = MarketLoadResult()

    if mode == CacheMode.CACHE_ONLY:
        for symbol in requested:
            if not client.is_cached(symbol, start, end, "all"):
                result.errors[symbol] = "cache_miss: exact-date market cache not found"
                continue
            try:
                result.frames[symbol] = _load_cached_market_symbol(
                    client, symbol, start, end
                )
            except Exception as exc:
                result.errors[symbol] = _safe_error(exc)
        return result

    batches = [
        requested[index : index + batch_size]
        for index in range(0, len(requested), batch_size)
    ]
    for batch_index, batch in enumerate(batches):
        requires_network = _network_required(client, batch, start, end, mode)
        if requires_network:
            result.network_batches += 1
        try:
            frames, errors = client.historical_batch(
                batch,
                start=start,
                end=end,
                adjustment="all",
                refresh=mode == CacheMode.REFRESH,
            )
            for symbol, frame in frames.items():
                dated = frame.copy()
                dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
                dated = dated[dated["date"].dt.date <= end]
                if dated.empty:
                    result.errors[symbol] = (
                        f"No market rows on or before {end} for {symbol}"
                    )
                else:
                    result.frames[symbol] = dated.sort_values("date").reset_index(
                        drop=True
                    )
            result.errors.update(errors)
        except Exception:
            for symbol in batch:
                try:
                    result.frames[symbol] = _load_market_symbol(
                        client,
                        symbol,
                        start,
                        end,
                        refresh=mode == CacheMode.REFRESH
                        or not client.is_cached(symbol, start, end, "all"),
                    )
                except Exception as exc:
                    result.errors[symbol] = _safe_error(exc)
        for symbol in batch:
            if symbol not in result.frames and symbol not in result.errors:
                result.errors[symbol] = "No market data returned"
        if requires_network and batch_index < len(batches) - 1:
            sleep_fn(rate_window_seconds)
    return result


def _eligible_market_tickers(
    universe: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    as_of: date,
) -> set[str]:
    eligible: set[str] = set()
    for ticker in universe["ticker"]:
        frame = frames.get(ticker)
        if frame is None:
            continue
        try:
            audit = assess_price_frame(ticker, frame, as_of)
        except Exception:
            continue
        adjusted = bool(
            frame.get("price_is_adjusted", pd.Series([False])).fillna(False).all()
        )
        if bool(audit["usable_for_model"]) and adjusted:
            eligible.add(ticker)
    return eligible


def load_sec_fundamentals(
    client: SecCompanyFactsClient,
    universe: pd.DataFrame,
    tickers: Sequence[str],
    as_of: date,
    mode: CacheMode,
    extractor: FundamentalExtractor = extract_sec_fundamentals,
) -> FundamentalLoadResult:
    """Load normalized SEC data once per CIK and isolate issuer failures."""

    requested = set(tickers)
    result = FundamentalLoadResult()
    cik_to_tickers: Dict[str, list[str]] = {}
    for row in universe.itertuples(index=False):
        if row.ticker not in requested:
            result.skipped[row.ticker] = "market_ineligible"
            continue
        cik = str(row.cik).zfill(10)
        cik_to_tickers.setdefault(cik, []).append(row.ticker)

    for cik, cik_tickers in cik_to_tickers.items():
        if mode == CacheMode.CACHE_ONLY and not client.is_cached(cik):
            for ticker in cik_tickers:
                result.errors[ticker] = "cache_miss: SEC Company Facts cache not found"
            continue
        try:
            if mode == CacheMode.CACHE_ONLY:
                payload = client.company_facts_cached(cik)
            else:
                payload = client.company_facts(
                    cik,
                    refresh=mode == CacheMode.REFRESH,
                )
            values = extractor(payload, as_of=as_of)
            for ticker in cik_tickers:
                result.values[ticker] = dict(values)
        except Exception as exc:
            error = _safe_error(exc)
            for ticker in cik_tickers:
                result.errors[ticker] = error
    return result


def _contract_columns() -> list[str]:
    columns: list[str] = []
    for section_name in FIELD_SECTIONS:
        columns.extend(DATA_CONTRACT.get(section_name, {}).keys())
    return list(dict.fromkeys(columns))


def _base_unavailable_row(
    identity: Mapping[str, object],
    fundamentals: Mapping[str, object],
    as_of: date,
) -> Dict[str, object]:
    row = {column: None for column in _contract_columns()}
    row.update(dict(identity))
    row.update(dict(fundamentals))
    row.update(
        {
            "as_of_date": as_of.isoformat(),
            "market_data_source": "twelve_data",
            "fundamental_data_source": "sec_companyfacts",
            "data_quality_flags": [],
            "missing_fields": [],
            "exclusion_reasons": [],
            "stale_fundamental_metrics": [],
            "eligible_for_scoring": False,
        }
    )
    period_end = pd.to_datetime(row.get("fundamental_period_end"), errors="coerce")
    row["fundamental_age_days"] = (
        (pd.Timestamp(as_of) - period_end).days
        if not pd.isna(period_end)
        else None
    )
    return row


def _append_issue(
    row: Dict[str, object],
    flag: str,
    exclusion: bool = False,
) -> None:
    flags = list(row.get("data_quality_flags") or [])
    if flag not in flags:
        flags.append(flag)
    row["data_quality_flags"] = flags
    if exclusion:
        reasons = list(row.get("exclusion_reasons") or [])
        if flag not in reasons:
            reasons.append(flag)
        row["exclusion_reasons"] = reasons
        row["eligible_for_scoring"] = False


def build_feature_rows(
    universe: pd.DataFrame,
    market: MarketLoadResult,
    fundamentals: FundamentalLoadResult,
    as_of: date,
) -> pd.DataFrame:
    """Assemble one deterministic row for every requested security."""

    benchmark = market.frames.get("SPY")
    benchmark_error = market.errors.get("SPY")
    records: list[Dict[str, object]] = []
    identity_fields = ("ticker", "company_name", "sector", "industry", "cik")

    for universe_row in universe.itertuples(index=False):
        identity = {
            field_name: getattr(universe_row, field_name)
            for field_name in identity_fields
        }
        ticker = str(identity["ticker"])
        fundamental_values = fundamentals.values.get(ticker, {})
        market_error = market.errors.get(ticker)
        fundamental_error = fundamentals.errors.get(ticker)
        prices = market.frames.get(ticker)

        if prices is None:
            row = _base_unavailable_row(identity, fundamental_values, as_of)
            row["market_error"] = market_error or "Market data unavailable"
            _append_issue(row, "market_data_error", exclusion=True)
        else:
            try:
                row = build_unified_feature_row(
                    identity,
                    prices,
                    fundamental_values,
                    as_of,
                    benchmark_prices=benchmark,
                )
            except Exception as exc:
                row = _base_unavailable_row(identity, fundamental_values, as_of)
                row["market_error"] = _safe_error(exc)
                _append_issue(row, "feature_assembly_error", exclusion=True)

        if benchmark_error:
            _append_issue(row, "benchmark_data_error")
        if fundamental_error:
            row["fundamental_error"] = fundamental_error
            _append_issue(row, "fundamental_data_error", exclusion=True)
        elif ticker in fundamentals.skipped:
            row["data_quality_flags"] = [
                flag
                for flag in row.get("data_quality_flags", [])
                if flag != "stale_fundamentals"
            ]
            row["exclusion_reasons"] = [
                reason
                for reason in row.get("exclusion_reasons", [])
                if reason != "stale_fundamentals"
            ]
            _append_issue(row, "fundamentals_skipped_market_ineligible")

        row["missing_fields"] = [
            column
            for column in _contract_columns()
            if column not in {
                "data_quality_flags",
                "missing_fields",
                "exclusion_reasons",
                "stale_fundamental_metrics",
                "eligible_for_scoring",
                "market_error",
                "fundamental_error",
            }
            and (row.get(column) is None or pd.isna(row.get(column)))
        ]
        records.append(row)

    matrix = pd.DataFrame(records)
    for column in _contract_columns():
        if column not in matrix:
            matrix[column] = None
    contract_columns = _contract_columns()
    extra_columns = sorted(set(matrix.columns) - set(contract_columns))
    return matrix[contract_columns + extra_columns].sort_values(
        ["as_of_date", "ticker"]
    ).reset_index(drop=True)


def build_feature_matrix(
    config: FeaturePipelineConfig,
    universe_loader: UniverseLoader = load_sp500_universe,
    market_client: Optional[TwelveDataClient] = None,
    sec_client: Optional[SecCompanyFactsClient] = None,
    fundamental_extractor: FundamentalExtractor = extract_sec_fundamentals,
    sleep_fn: SleepFunction = time.sleep,
) -> FeaturePipelineBuild:
    """Build the complete in-memory matrix without persisting run artifacts."""

    universe = resolve_universe(config, loader=universe_loader)
    market_client = market_client or TwelveDataClient(
        config.project_root / "data/cache/twelve_data"
    )
    sec_client = sec_client or SecCompanyFactsClient(
        config.project_root / "data/cache/sec"
    )
    symbols = ["SPY", *universe["ticker"].tolist()]
    market = load_market_histories(
        market_client,
        symbols,
        start=config.market_start,
        end=config.as_of,
        mode=config.cache_mode,
        batch_size=config.market_batch_size,
        rate_window_seconds=config.market_rate_window_seconds,
        sleep_fn=sleep_fn,
    )
    eligible_tickers = _eligible_market_tickers(
        universe,
        market.frames,
        config.as_of,
    )
    fundamentals = load_sec_fundamentals(
        sec_client,
        universe,
        sorted(eligible_tickers),
        as_of=config.as_of,
        mode=config.cache_mode,
        extractor=fundamental_extractor,
    )
    matrix = build_feature_rows(universe, market, fundamentals, config.as_of)
    return FeaturePipelineBuild(
        matrix=matrix,
        universe=universe,
        market=market,
        fundamentals=fundamentals,
        benchmark_error=market.errors.get("SPY"),
    )


def _run_metadata(
    config: FeaturePipelineConfig,
    build: FeaturePipelineBuild,
    started_at: datetime,
    completed_at: datetime,
) -> Dict[str, object]:
    return {
        "run_id": config.effective_run_id,
        "started_at_utc": started_at.replace(microsecond=0).isoformat(),
        "completed_at_utc": completed_at.replace(microsecond=0).isoformat(),
        "as_of_date": config.as_of.isoformat(),
        "market_start_date": config.market_start.isoformat(),
        "universe_id": config.universe_id,
        "requested_tickers": list(config.tickers) if config.tickers else None,
        "cache_mode": config.cache_mode.value,
        "contract_version": str(DATA_CONTRACT["contract"]["version"]),
        "contract_status": str(DATA_CONTRACT["contract"]["status"]),
        "providers": dict(DATA_CONTRACT["providers"]),
        "requested_count": int(len(build.universe)),
        "market_frame_count": int(
            len(set(build.market.frames) - {"SPY"})
        ),
        "market_error_count": int(
            len(set(build.market.errors) - {"SPY"})
        ),
        "fundamental_success_count": int(len(build.fundamentals.values)),
        "fundamental_error_count": int(len(build.fundamentals.errors)),
        "fundamental_skipped_count": int(len(build.fundamentals.skipped)),
        "benchmark_error": build.benchmark_error,
        "network_market_batch_count": int(build.market.network_batches),
        "runtime_versions": {
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
        },
    }


def run_feature_pipeline(
    config: FeaturePipelineConfig,
    universe_loader: UniverseLoader = load_sp500_universe,
    market_client: Optional[TwelveDataClient] = None,
    sec_client: Optional[SecCompanyFactsClient] = None,
    fundamental_extractor: FundamentalExtractor = extract_sec_fundamentals,
    sleep_fn: SleepFunction = time.sleep,
) -> FeaturePipelineResult:
    """Build, validate, and atomically persist one feature-matrix run."""

    contract_header = DATA_CONTRACT["contract"]
    accepted_run_id = str(contract_header.get("accepted_run_id") or "")
    accepted_run_dir = config.processed_dir / config.effective_run_id
    if (
        contract_header.get("status") == "frozen_v1"
        and accepted_run_id
        and config.effective_run_id == accepted_run_id
        and accepted_run_dir.exists()
    ):
        raise FileExistsError(
            "The frozen accepted run already exists and cannot be overwritten: "
            f"{accepted_run_dir}. Use an explicit, different --run-id."
        )

    started_at = datetime.now(timezone.utc)
    build = build_feature_matrix(
        config,
        universe_loader=universe_loader,
        market_client=market_client,
        sec_client=sec_client,
        fundamental_extractor=fundamental_extractor,
        sleep_fn=sleep_fn,
    )
    completed_at = datetime.now(timezone.utc)
    metadata = _run_metadata(config, build, started_at, completed_at)
    quality = analyze_feature_matrix(build.matrix, build.universe, metadata)
    artifacts = write_quality_artifacts(
        build.matrix,
        quality,
        config.processed_dir,
        config.effective_run_id,
    )
    return FeaturePipelineResult(
        build=build,
        quality=quality,
        artifacts=artifacts,
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--universe", choices=("sp500", "custom"), default="sp500")
    parser.add_argument("--tickers", nargs="+")
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--cache-only",
        action="store_true",
        help="Forbid network requests and record exact-date cache misses",
    )
    cache_group.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh universe and provider caches explicitly",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--market-history-days", type=int, default=400)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--rate-window-seconds", type=float, default=62.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    mode = CacheMode.CACHE_FIRST
    if args.cache_only:
        mode = CacheMode.CACHE_ONLY
    elif args.refresh:
        mode = CacheMode.REFRESH

    try:
        config = FeaturePipelineConfig(
            project_root=args.project_root,
            as_of=args.as_of,
            universe_id=args.universe,
            tickers=args.tickers,
            cache_mode=mode,
            market_history_days=args.market_history_days,
            market_batch_size=args.batch_size,
            market_rate_window_seconds=args.rate_window_seconds,
            output_dir=args.output_dir,
            run_id=args.run_id,
        )
        result = run_feature_pipeline(config)
    except Exception as exc:
        print(f"Pipeline failed: {_safe_error(exc)}")
        return 2

    acceptance = result.quality.summary["acceptance"]
    eligibility = result.quality.summary["eligibility"]
    print(
        json.dumps(
            {
                "run_id": config.effective_run_id,
                "acceptance_passed": acceptance["passed"],
                "hard_failures": acceptance["hard_failures"],
                "warnings": acceptance["warnings"],
                "eligible_count": eligibility["eligible_count"],
                "ineligible_count": eligibility["ineligible_count"],
                "run_directory": str(result.artifacts.run_dir),
            },
            indent=2,
        )
    )
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
