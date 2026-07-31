"""Requested-order comparisons over accepted Stock Detail responses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy

from src.screening import SUPPORTED_MODES
from src.stock_detail import (
    StockDetailDataError,
    StockDetailNotFoundError,
    StockDetailValidationError,
    get_stock_detail as get_stock_detail_service,
)


SCHEMA_VERSION = "1.0.0"
MIN_TICKERS = 2
MAX_TICKERS = 5


class ComparisonValidationError(ValueError):
    """Raised when a comparison request is invalid."""


class ComparisonDataError(RuntimeError):
    """Raised when detail responses do not share one accepted snapshot."""


def _normalize_mode(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ComparisonValidationError("mode must be a non-empty string")
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_MODES:
        raise ComparisonValidationError(
            "Unsupported mode: "
            f"{value!r}. Supported values: {', '.join(SUPPORTED_MODES)}"
        )
    return normalized


def _normalize_tickers(value: object) -> list[str]:
    if isinstance(value, (str, bytes)):
        raise ComparisonValidationError(
            "tickers must be an iterable of 2 to 5 ticker strings"
        )
    try:
        requested = list(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise ComparisonValidationError(
            "tickers must be an iterable of 2 to 5 ticker strings"
        ) from error

    if not MIN_TICKERS <= len(requested) <= MAX_TICKERS:
        raise ComparisonValidationError("tickers must contain 2 to 5 values")

    normalized: list[str] = []
    for ticker in requested:
        if not isinstance(ticker, str) or not ticker.strip():
            raise ComparisonValidationError(
                "tickers must contain only non-empty strings"
            )
        normalized.append(ticker.strip().upper())
    if len(set(normalized)) != len(normalized):
        raise ComparisonValidationError("tickers must be unique")
    return normalized


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ComparisonDataError(f"Stock Detail {label} must be a mapping")
    return value


def _project_detail(
    detail: Mapping[str, object],
    request_position: int,
) -> dict[str, object]:
    identity = _mapping(detail.get("identity"), "identity")
    selected_mode = _mapping(detail.get("selected_mode"), "selected_mode")
    quality = _mapping(detail.get("quality"), "quality")
    return {
        "request_position": request_position,
        "status": "available",
        "ticker": detail.get("ticker"),
        "identity": deepcopy(dict(identity)),
        "selected_mode": deepcopy(dict(selected_mode)),
        "factor_scores": deepcopy(
            dict(_mapping(detail.get("factor_scores"), "factor_scores"))
        ),
        "market_snapshot": deepcopy(
            dict(_mapping(detail.get("market_snapshot"), "market_snapshot"))
        ),
        "strengths": deepcopy(list(detail.get("strengths", []))[:3]),
        "risks": deepcopy(list(detail.get("risks", []))[:3]),
        "quality": {
            "eligible_for_scoring": quality.get("eligible_for_scoring"),
            "missing_inputs": deepcopy(list(quality.get("missing_inputs", []))),
            "warnings": deepcopy(list(quality.get("warnings", []))),
            "base_exclusion_reasons": deepcopy(
                list(quality.get("base_exclusion_reasons", []))
            ),
        },
        "data_dates": deepcopy(
            dict(_mapping(detail.get("data_dates"), "data_dates"))
        ),
    }


def compare_stocks(
    tickers: Iterable[str],
    mode: str = "balanced",
) -> dict[str, object]:
    """Compare two to five accepted-snapshot securities in requested order.

    Every available item is a projection of ``get_stock_detail``. The service
    never rescales scores, reranks securities, or fetches an unknown ticker.
    """

    normalized_tickers = _normalize_tickers(tickers)
    normalized_mode = _normalize_mode(mode)
    items: list[dict[str, object]] = []
    unknown_tickers: list[str] = []
    snapshot: dict[str, object] | None = None
    snapshot_fields = (
        "accepted_run_id",
        "scoring_contract_version",
        "factor_model_version",
        "screening_modes_version",
        "input_feature_run_id",
        "input_contract_version",
        "as_of_date",
    )

    for position, ticker in enumerate(normalized_tickers, start=1):
        try:
            detail = get_stock_detail_service(
                ticker=ticker,
                mode=normalized_mode,
            )
        except StockDetailNotFoundError as error:
            unknown_tickers.append(ticker)
            items.append(
                {
                    "request_position": position,
                    "status": "unknown",
                    "ticker": ticker,
                    "reason_code": "ticker_not_in_accepted_snapshot",
                    "message": str(error),
                }
            )
            continue
        except (StockDetailDataError, StockDetailValidationError):
            raise ComparisonDataError(
                f"Stock Detail evidence could not be loaded for {ticker}"
            ) from None

        if not isinstance(detail, Mapping):
            raise ComparisonDataError("Stock Detail result must be a mapping")
        detail_mode = detail.get("mode")
        if detail_mode != normalized_mode:
            raise ComparisonDataError(
                f"Stock Detail returned inconsistent mode for {ticker}"
            )
        current_snapshot = {
            field_name: detail.get(field_name) for field_name in snapshot_fields
        }
        if snapshot is None:
            snapshot = current_snapshot
        elif current_snapshot != snapshot:
            raise ComparisonDataError(
                "Stock Detail responses do not share one accepted snapshot"
            )
        items.append(_project_detail(detail, position))

    available_count = sum(item["status"] == "available" for item in items)
    snapshot = snapshot or {field_name: None for field_name in snapshot_fields}
    return {
        "service": "compare_stocks",
        "schema_version": SCHEMA_VERSION,
        **snapshot,
        "mode": normalized_mode,
        "requested_tickers": normalized_tickers,
        "requested_count": len(normalized_tickers),
        "available_count": available_count,
        "unknown_count": len(unknown_tickers),
        "comparison_available": available_count >= 2,
        "unknown_tickers": unknown_tickers,
        "items": items,
        "ordering": "requested_ticker_order",
        "score_treatment": "stored_values_preserved_without_reranking",
    }
