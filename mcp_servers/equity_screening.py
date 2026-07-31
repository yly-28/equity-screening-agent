"""Read-only MCP adapters for the equity research application services."""

from __future__ import annotations

from typing import Callable, Final, NoReturn, Optional

from mcp.server import MCPServer
from pydantic import StrictBool

from src.comparison import (
    ComparisonDataError,
    ComparisonValidationError,
    compare_stocks as compare_stocks_service,
)
from src.live_analysis import (
    LiveAnalysisDataError,
    LiveAnalysisNotFoundError,
    LiveAnalysisValidationError,
    analyze_ticker as analyze_ticker_service,
)
from src.overview import (
    OverviewDataError,
    OverviewValidationError,
    get_market_overview as get_market_overview_service,
)
from src.scoring_contract import ScoringContractError
from src.screening import (
    ScreeningDataError,
    ScreeningValidationError,
    screen_stocks as screen_stocks_service,
)
from src.stock_detail import (
    StockDetailDataError,
    StockDetailNotFoundError,
    StockDetailValidationError,
    get_stock_detail as get_stock_detail_service,
)


SERVER_VERSION = "0.2.0"


def _new_server(**kwargs: object) -> MCPServer:
    return MCPServer(
        name="equity-screening-agent",
        version=SERVER_VERSION,
        instructions=(
            "Read-only equity research tools. Accepted scores, eligibility, "
            "ordering, evidence, dates, and terminology come from existing "
            "application services. analyze_ticker permits provider access only "
            "when refresh=true; live quotes are display-only and never change "
            "factor scores or ranks. No tool trades or gives personalized advice."
        ),
        **kwargs,
    )


def _raise_tool_error(
    label: str,
    error: Exception,
    *,
    include_safe_detail: bool = False,
) -> NoReturn:
    """Raise a stable public MCP error without paths, secrets, or tracebacks."""

    message = label
    if include_safe_detail:
        detail = " ".join(str(error).split()).strip()
        if detail:
            message = f"{label}: {detail[:300]}"
    raise RuntimeError(message) from None


def screen_stocks(
    universe: str = "sp500",
    custom_tickers: Optional[list[str]] = None,
    mode: str = "balanced",
    sectors: Optional[list[str]] = None,
    minimum_price: Optional[float] = None,
    minimum_market_cap_proxy: Optional[float] = None,
    minimum_average_volume_20d: Optional[float] = None,
    minimum_factor_scores: Optional[dict[str, float]] = None,
    top_n: int = 20,
) -> dict[str, object]:
    """Filter and rank the verified accepted local scoring snapshot."""

    try:
        return screen_stocks_service(
            universe=universe,
            custom_tickers=custom_tickers,
            mode=mode,
            sectors=sectors,
            minimum_price=minimum_price,
            minimum_market_cap_proxy=minimum_market_cap_proxy,
            minimum_average_volume_20d=minimum_average_volume_20d,
            minimum_factor_scores=minimum_factor_scores,
            top_n=top_n,
        )
    except ScreeningValidationError as error:
        _raise_tool_error(
            "Invalid screen_stocks request", error, include_safe_detail=True
        )
    except ScreeningDataError as error:
        _raise_tool_error("Accepted screening data error", error)
    except ScoringContractError as error:
        _raise_tool_error("Accepted scoring run verification failed", error)


def get_stock_detail(
    ticker: str,
    mode: str = "balanced",
) -> dict[str, object]:
    """Return the complete accepted-snapshot evidence for one security."""

    try:
        return get_stock_detail_service(ticker=ticker, mode=mode)
    except StockDetailValidationError as error:
        _raise_tool_error(
            "Invalid get_stock_detail request", error, include_safe_detail=True
        )
    except StockDetailNotFoundError as error:
        _raise_tool_error(
            "Stock Detail ticker not found", error, include_safe_detail=True
        )
    except StockDetailDataError as error:
        _raise_tool_error("Accepted Stock Detail data error", error)
    except ScoringContractError as error:
        _raise_tool_error("Accepted scoring run verification failed", error)


def analyze_ticker(
    ticker: str,
    mode: str = "balanced",
    refresh: StrictBool = False,
) -> dict[str, object]:
    """Return a concise accepted report or clearly unscored live evidence."""

    try:
        return analyze_ticker_service(ticker=ticker, mode=mode, refresh=refresh)
    except LiveAnalysisValidationError as error:
        _raise_tool_error(
            "Invalid analyze_ticker request", error, include_safe_detail=True
        )
    except LiveAnalysisNotFoundError as error:
        _raise_tool_error(
            "Ticker analysis not found", error, include_safe_detail=True
        )
    except LiveAnalysisDataError as error:
        if str(error).startswith("online_refresh_required:"):
            raise RuntimeError(
                "Ticker analysis data error: online_refresh_required"
            ) from None
        _raise_tool_error("Ticker analysis data error", error)


def compare_stocks(
    tickers: list[str],
    mode: str = "balanced",
) -> dict[str, object]:
    """Compare two to five accepted-run securities in requested order."""

    try:
        return compare_stocks_service(tickers=tickers, mode=mode)
    except ComparisonValidationError as error:
        _raise_tool_error(
            "Invalid compare_stocks request", error, include_safe_detail=True
        )
    except ComparisonDataError as error:
        _raise_tool_error("Accepted comparison data error", error)
    except ScoringContractError as error:
        _raise_tool_error("Accepted scoring run verification failed", error)


def get_market_overview(
    mode: str = "balanced",
    sectors: Optional[list[str]] = None,
) -> dict[str, object]:
    """Summarize accepted market and sector evidence without live inference."""

    try:
        return get_market_overview_service(mode=mode, sectors=sectors)
    except OverviewValidationError as error:
        _raise_tool_error(
            "Invalid get_market_overview request", error, include_safe_detail=True
        )
    except OverviewDataError as error:
        _raise_tool_error("Accepted overview data error", error)
    except ScoringContractError as error:
        _raise_tool_error("Accepted scoring run verification failed", error)


TOOL_HANDLERS: Final[tuple[Callable[..., dict[str, object]], ...]] = (
    screen_stocks,
    get_stock_detail,
    analyze_ticker,
    compare_stocks,
    get_market_overview,
)


def register_tools(server: MCPServer) -> None:
    """Register the one canonical fixed-order tool set on an MCP server."""

    for handler in TOOL_HANDLERS:
        server.add_tool(handler, structured_output=True)


mcp = _new_server()
register_tools(mcp)


def main() -> None:
    """Run the local MCP server over standard input/output."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
