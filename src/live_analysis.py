"""Unified accepted-snapshot and live evidence for one ticker.

Live quotes are display-only. Securities outside the accepted scoring snapshot
receive identity and quote evidence, but never a sector-relative score or rank.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Optional

from src.research_report import DISCLAIMER, get_research_report
from src.security_identity import (
    SecTickerResolver,
    SecurityIdentityError,
    SecurityIdentityNotFoundError,
)
from src.stock_detail import StockDetailNotFoundError
from src.twelve_data import TwelveDataClient, TwelveDataError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.0.0"
SUPPORTED_MODES = ("balanced", "growth", "value", "low_risk")
FACTOR_NAMES = ("momentum", "quality", "valuation", "risk", "sector_strength")
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,19}$")


class LiveAnalysisValidationError(ValueError):
    """Raised when a live-analysis request is invalid."""


class LiveAnalysisNotFoundError(LookupError):
    """Raised when neither accepted data nor SEC identity can resolve a ticker."""


class LiveAnalysisDataError(RuntimeError):
    """Raised when a service response violates the live-analysis boundary."""


AcceptedReportLoader = Callable[..., dict[str, object]]


def _normalize_ticker(value: object) -> str:
    if not isinstance(value, str):
        raise LiveAnalysisValidationError("ticker must be a string")
    ticker = value.strip().upper()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise LiveAnalysisValidationError(
            "ticker must contain only letters, numbers, '.', or '-'"
        )
    return ticker


def _normalize_mode(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveAnalysisValidationError("mode must be a non-empty string")
    mode = value.strip().lower()
    if mode not in SUPPORTED_MODES:
        raise LiveAnalysisValidationError(
            "Unsupported mode: "
            f"{value!r}. Supported values: {', '.join(SUPPORTED_MODES)}"
        )
    return mode


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LiveAnalysisDataError(f"{label} must be a mapping")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise LiveAnalysisDataError(f"{label} must be a list of strings")
    return list(value)


def _provider_error(exc: BaseException) -> str:
    error_name = type(exc).__name__
    if isinstance(
        exc,
        (TwelveDataError, SecurityIdentityError, SecurityIdentityNotFoundError),
    ):
        detail = " ".join(str(exc).split()).strip() or "operation failed"
        for variable_name in (
            "TWELVE_DATA_API_KEY",
            "OPENAI_API_KEY",
            "EQUITY_MCP_TOKEN",
        ):
            secret = os.getenv(variable_name)
            if secret:
                detail = detail.replace(secret, "[redacted]")
        detail = detail.replace(str(PROJECT_ROOT), "[project]")
        detail = detail.replace(str(Path.home()), "[home]")
        detail = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[redacted]", detail)
        detail = re.sub(
            r"(?i)(apikey|api_key|token)=([^&\s]+)",
            r"\1=[redacted]",
            detail,
        )
        detail = re.sub(
            r"(?<![:/])/(?:[^/\s]+/)+[^\s,;]+",
            "[path]",
            detail,
        )
        detail = detail.replace("Traceback", "[redacted]")
        return f"{error_name}: {detail[:300]}"
    return f"{error_name}: operation failed"


def _default_market_client() -> TwelveDataClient:
    return TwelveDataClient(PROJECT_ROOT / "data/cache/twelve_data")


def _default_identity_resolver() -> SecTickerResolver:
    return SecTickerResolver(PROJECT_ROOT / "data/cache/sec/identity")


def _validated_quote(value: object, ticker: str) -> dict[str, object]:
    quote = dict(_mapping(value, "live quote"))
    if quote.get("ticker") != ticker:
        raise LiveAnalysisDataError(
            f"live quote ticker does not match requested ticker {ticker}"
        )
    if quote.get("scoring_use") != "display_only_not_used_for_factor_scoring":
        raise LiveAnalysisDataError(
            "live quote must be marked display-only and excluded from scoring"
        )
    return deepcopy(quote)


def _validated_profile(value: object, ticker: str) -> dict[str, object]:
    profile = dict(_mapping(value, "company profile"))
    if profile.get("ticker") != ticker:
        raise LiveAnalysisDataError(
            f"company profile ticker does not match requested ticker {ticker}"
        )
    if profile.get("sector") is not None or profile.get("industry") is not None:
        raise LiveAnalysisDataError(
            "provider profile may not supply unverified project GICS values"
        )
    return deepcopy(profile)


def _validated_identity(value: object, ticker: str) -> dict[str, object]:
    identity = dict(_mapping(value, "SEC identity"))
    if identity.get("ticker") != ticker:
        raise LiveAnalysisDataError(
            f"SEC identity ticker does not match requested ticker {ticker}"
        )
    for field_name in ("company_name", "cik"):
        field_value = identity.get(field_name)
        if not isinstance(field_value, str) or not field_value:
            raise LiveAnalysisDataError(
                f"SEC identity is missing normalized {field_name}"
            )
    if identity.get("sector") is not None or identity.get("industry") is not None:
        raise LiveAnalysisDataError(
            "SEC identity may not infer project GICS sector or industry"
        )
    _string_list(identity.get("warnings", []), "SEC identity warnings")
    return deepcopy(identity)


def _outside_report(
    ticker: str,
    mode: str,
    identity: Mapping[str, object],
    quote: Optional[Mapping[str, object]],
    profile: Optional[Mapping[str, object]],
    provider_errors: Mapping[str, str],
) -> dict[str, object]:
    basis_codes = [
        "ticker_not_in_accepted_scoring_run",
        "project_gics_sector_unavailable",
        "sector_relative_scoring_not_performed",
    ]
    if quote is None:
        basis_codes.append("latest_quote_unavailable")
    if profile is None:
        basis_codes.append("company_profile_unavailable")
    warnings = _string_list(identity.get("warnings", []), "SEC identity warnings")
    if profile is not None:
        warnings.extend(
            _string_list(profile.get("warnings", []), "company profile warnings")
        )
    warnings.extend(f"provider_error:{name}" for name in provider_errors)
    warnings.extend(
        f"online_refresh_required:{name}"
        for name, message in provider_errors.items()
        if message.startswith("online_refresh_required:")
    )
    warnings = list(dict.fromkeys(str(item) for item in warnings))

    return {
        "service": "live_research_report",
        "schema_version": SCHEMA_VERSION,
        "accepted_run_id": None,
        "scoring_contract_version": None,
        "factor_model_version": None,
        "screening_modes_version": None,
        "as_of_date": None,
        "ticker": ticker,
        "mode": mode,
        "identity": deepcopy(dict(identity)),
        "research_posture": {
            "classification": "insufficient_evidence",
            "label": "Insufficient evidence",
            "selected_mode_score": None,
            "eligible_for_ranking": False,
            "basis_codes": basis_codes,
            "meaning": (
                "Provider identity and quote evidence only; this is not a buy, "
                "sell, hold, or suitability recommendation, and no accepted "
                "factor score or rank is available."
            ),
        },
        "summary": (
            f"{ticker} is outside the accepted scoring snapshot. Available "
            "provider evidence is shown, but no sector-relative factor score "
            "or rank is produced without a trusted project GICS classification."
        ),
        "factor_scores": {factor_name: None for factor_name in FACTOR_NAMES},
        "strengths": [],
        "risks": [
            {
                "code": "outside_accepted_scoring_run",
                "summary": "No verified accepted scoring row is available.",
            },
            {
                "code": "project_gics_classification_unavailable",
                "summary": (
                    "A trusted project GICS classification is unavailable, so "
                    "sector-relative scoring is not performed."
                ),
            },
        ],
        "quality": {
            "eligible_for_scoring": False,
            "missing_inputs": ["accepted_scoring_row", "project_gics_sector"],
            "warnings": warnings,
            "stale_fundamental_metrics": [],
            "base_exclusion_reasons": [
                "ticker_not_in_accepted_scoring_run",
                "project_gics_sector_unavailable",
            ],
        },
        "data_dates": {
            "quote_datetime": quote.get("provider_datetime") if quote else None,
            "quote_fetched_at_utc": quote.get("fetched_at_utc") if quote else None,
            "identity_fetched_at_utc": identity.get("fetched_at_utc"),
            "profile_fetched_at_utc": (
                profile.get("fetched_at_utc") if profile else None
            ),
        },
        "next_research_questions": [
            "Can an approved source provide an exact project GICS classification?",
            "Can the company be included in a validated current reference snapshot?",
            "What filing-based fundamentals are available and sufficiently current?",
        ],
        "terminology": {
            "live_quote": "Display-only provider evidence; not used for scoring.",
            "score": "Unavailable because sector-relative scoring was not performed.",
            "rank": "Unavailable because the ticker is outside the accepted run.",
        },
        "disclaimer": DISCLAIMER,
    }


def _accepted_response(
    ticker: str,
    mode: str,
    report: Mapping[str, object],
    refresh: bool,
    cache_only: bool,
    market_client: Optional[object],
) -> dict[str, object]:
    normalized_report = deepcopy(dict(report))
    if normalized_report.get("ticker") != ticker:
        raise LiveAnalysisDataError(
            f"accepted report ticker does not match requested ticker {ticker}"
        )
    if normalized_report.get("mode") != mode:
        raise LiveAnalysisDataError(
            f"accepted report mode does not match requested mode {mode}"
        )
    identity = deepcopy(dict(_mapping(normalized_report.get("identity"), "identity")))
    posture = _mapping(normalized_report.get("research_posture"), "research posture")
    selected_mode_score = posture.get("selected_mode_score")
    score_available = selected_mode_score is not None
    unavailable_reasons = (
        []
        if score_available
        else _string_list(
            posture.get("basis_codes", []),
            "research posture basis_codes",
        )
    )
    quote: Optional[dict[str, object]] = None
    provider_errors: dict[str, str] = {}
    warnings: list[str] = []

    if refresh:
        client = market_client or _default_market_client()
        try:
            quote = _validated_quote(
                client.latest_quote(  # type: ignore[attr-defined]
                    ticker,
                    refresh=True,
                    cache_only=cache_only,
                ),
                ticker,
            )
        except Exception as exc:
            provider_errors["quote"] = _provider_error(exc)
            warnings.append("live_quote_unavailable")

    return {
        "service": "analyze_ticker",
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker,
        "mode": mode,
        "data_scope": "accepted_snapshot",
        "analysis_status": "accepted_evidence",
        "accepted_run_id": normalized_report.get("accepted_run_id"),
        "as_of_date": normalized_report.get("as_of_date"),
        "identity": identity,
        "live_quote": quote,
        "provider_profile": None,
        "scoring": {
            "available": score_available,
            "source": "accepted_scoring_run",
            "selected_mode_score": selected_mode_score,
            "eligible_for_ranking": posture.get("eligible_for_ranking") is True,
            "rank": None,
            "unavailable_reasons": unavailable_reasons,
        },
        "report": normalized_report,
        "provider_errors": provider_errors,
        "warnings": warnings,
        "limitations": [
            "live_quote_display_only_not_used_for_factor_scoring",
            "refresh_does_not_rescore_or_rerank_accepted_evidence",
            "no_trading_or_personalized_investment_recommendation",
        ],
        "disclaimer": normalized_report.get("disclaimer", DISCLAIMER),
    }


def analyze_ticker(
    ticker: str,
    mode: str = "balanced",
    refresh: bool = False,
    *,
    cache_only: bool = False,
    market_client: Optional[object] = None,
    identity_resolver: Optional[object] = None,
    accepted_report_loader: Optional[AcceptedReportLoader] = None,
) -> dict[str, object]:
    """Return accepted evidence or a clearly unscored live-evidence report.

    ``refresh`` can update provider caches and add a display-only quote. It
    never changes accepted factors, scores, weights, eligibility, or ordering.
    With ``refresh=False``, provider clients are forced to cache-only mode and
    cannot make an implicit network request after a cache miss.
    """

    symbol = _normalize_ticker(ticker)
    normalized_mode = _normalize_mode(mode)
    if not isinstance(refresh, bool) or not isinstance(cache_only, bool):
        raise LiveAnalysisValidationError("refresh and cache_only must be boolean")
    if refresh and cache_only:
        raise LiveAnalysisValidationError(
            "refresh and cache_only are mutually exclusive"
        )

    report_loader = accepted_report_loader or get_research_report
    try:
        accepted_report = report_loader(ticker=symbol, mode=normalized_mode)
    except StockDetailNotFoundError:
        accepted_report = None
    except Exception as exc:
        raise LiveAnalysisDataError(
            "Accepted report could not be loaded: " + _provider_error(exc)
        ) from None

    if accepted_report is not None:
        return _accepted_response(
            symbol,
            normalized_mode,
            _mapping(accepted_report, "accepted report"),
            refresh,
            cache_only,
            market_client,
        )

    resolver = identity_resolver or _default_identity_resolver()
    provider_cache_only = not refresh
    try:
        identity = _validated_identity(
            resolver.resolve(  # type: ignore[attr-defined]
                symbol,
                refresh=refresh,
                cache_only=provider_cache_only,
            ),
            symbol,
        )
    except SecurityIdentityNotFoundError:
        raise LiveAnalysisNotFoundError(
            f"Ticker {symbol} is absent from both accepted and SEC identity data"
        ) from None
    except Exception as exc:
        prefix = ""
        if not refresh:
            prefix = "online_refresh_required: cached "
        raise LiveAnalysisDataError(
            prefix + "SEC identity could not be resolved: " + _provider_error(exc)
        ) from None

    client = market_client or _default_market_client()
    quote: Optional[dict[str, object]] = None
    profile: Optional[dict[str, object]] = None
    provider_errors: dict[str, str] = {}
    try:
        quote = _validated_quote(
            client.latest_quote(  # type: ignore[attr-defined]
                symbol,
                refresh=refresh,
                cache_only=provider_cache_only,
            ),
            symbol,
        )
    except Exception as exc:
        prefix = "online_refresh_required: " if not refresh else ""
        provider_errors["quote"] = prefix + _provider_error(exc)
    try:
        profile = _validated_profile(
            client.company_profile(  # type: ignore[attr-defined]
                symbol,
                refresh=refresh,
                cache_only=provider_cache_only,
            ),
            symbol,
        )
    except Exception as exc:
        prefix = "online_refresh_required: " if not refresh else ""
        provider_errors["profile"] = prefix + _provider_error(exc)

    report = _outside_report(
        symbol,
        normalized_mode,
        identity,
        quote,
        profile,
        provider_errors,
    )
    return {
        "service": "analyze_ticker",
        "schema_version": SCHEMA_VERSION,
        "ticker": symbol,
        "mode": normalized_mode,
        "data_scope": "live_unscored",
        "analysis_status": "insufficient_evidence",
        "accepted_run_id": None,
        "as_of_date": None,
        "identity": identity,
        "live_quote": quote,
        "provider_profile": profile,
        "scoring": {
            "available": False,
            "source": None,
            "selected_mode_score": None,
            "eligible_for_ranking": False,
            "rank": None,
            "unavailable_reasons": [
                "ticker_not_in_accepted_scoring_run",
                "project_gics_sector_unavailable",
                "sector_relative_scoring_not_performed",
            ],
        },
        "report": report,
        "provider_errors": provider_errors,
        "warnings": report["quality"]["warnings"],  # type: ignore[index]
        "limitations": [
            "provider_sector_and_industry_are_not_project_gics",
            "no_sector_relative_factor_scoring_or_rank",
            "live_quote_display_only_not_used_for_factor_scoring",
            "no_trading_or_personalized_investment_recommendation",
        ],
        "disclaimer": DISCLAIMER,
    }
