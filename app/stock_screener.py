"""Streamlit research workspace over the project's tested service boundaries."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import (
    ai_report,
    comparison,
    live_analysis,
    overview,
    scoring_contract,
    screening,
)


MODE_LABELS = {
    "balanced": "Balanced",
    "growth": "Growth",
    "value": "Value",
    "low_risk": "Low Risk",
}

UNIVERSE_LABELS = {
    "sp500": "Accepted S&P 500 snapshot",
    "custom": "Custom accepted-run tickers",
}

SECTOR_OPTIONS = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)

FACTOR_LABELS = {
    "momentum": "Momentum",
    "quality": "Quality",
    "valuation": "Valuation",
    "risk": "Risk (higher means lower measured risk)",
    "sector_strength": "Sector Strength",
}

DISCLAIMER = (
    "This output is generated for educational and research purposes only. "
    "It is not financial advice, investment advice, or a recommendation to "
    "buy or sell any security."
)


def build_screening_request(
    *,
    universe: str,
    custom_ticker_text: str,
    mode: str,
    sectors: Sequence[str],
    minimum_price: float | None,
    minimum_market_cap_proxy: float | None,
    minimum_average_volume_20d: float | None,
    top_n: int,
    minimum_factor_scores: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Map UI controls directly to ``screen_stocks`` arguments."""

    request: dict[str, object] = {
        "universe": universe,
        "custom_tickers": (
            custom_ticker_text.splitlines() if universe == "custom" else None
        ),
        "mode": mode,
        "sectors": list(sectors) if sectors else None,
        "minimum_price": minimum_price,
        "minimum_market_cap_proxy": minimum_market_cap_proxy,
        "minimum_average_volume_20d": minimum_average_volume_20d,
        "top_n": top_n,
    }
    if minimum_factor_scores:
        request["minimum_factor_scores"] = dict(minimum_factor_scores)
    return request


def execute_screening(request: Mapping[str, object]) -> dict[str, object]:
    """Call the deterministic screening service unchanged."""

    return screening.screen_stocks(**request)


def build_analysis_request(
    *,
    ticker: str,
    mode: str,
    refresh: bool,
) -> dict[str, object]:
    """Map the ticker form directly to the unified analysis service."""

    return {"ticker": ticker, "mode": mode, "refresh": refresh}


def execute_analysis(request: Mapping[str, object]) -> dict[str, object]:
    """Call the unified ticker analysis service unchanged."""

    return live_analysis.analyze_ticker(**request)


def execute_comparison(request: Mapping[str, object]) -> dict[str, object]:
    """Call the requested-order comparison service unchanged."""

    return comparison.compare_stocks(**request)


def execute_overview(request: Mapping[str, object]) -> dict[str, object]:
    """Call the accepted-run market overview service unchanged."""

    return overview.get_market_overview(**request)


def ranked_company_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """Project ranked service records without filtering or sorting them."""

    rows: list[dict[str, object]] = []
    for stock in result["stocks"]:  # type: ignore[index]
        factor_scores = stock["factor_scores"]
        data_dates = stock["data_dates"]
        strengths = stock["strengths"]
        risks = stock["risks"]
        rows.append(
            {
                "Rank": stock["rank"],
                "Ticker": stock["ticker"],
                "Company": stock["company_name"],
                "Sector": stock["sector"],
                "Industry": stock["industry"],
                "Selected mode score": stock["mode_score"],
                "Momentum": factor_scores["momentum"],
                "Quality": factor_scores["quality"],
                "Valuation": factor_scores["valuation"],
                "Risk (higher = lower measured risk)": factor_scores["risk"],
                "Sector Strength": factor_scores["sector_strength"],
                "Price (USD)": stock["price"],
                "Market-cap proxy (USD)": stock["market_cap_proxy"],
                "20-day average share volume": stock["average_volume_20d"],
                "Market data date": data_dates["price_data_end"],
                "Fundamental period end": data_dates["fundamental_period_end"],
                "Filing date": data_dates["fundamental_filed_date"],
                "Top strength": strengths[0]["summary"] if strengths else None,
                "Top risk": risks[0]["summary"] if risks else None,
                "Warnings": ", ".join(stock["warnings"]),
            }
        )
    return rows


def exclusion_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """Project service exclusions in their existing order."""

    return [
        {
            "Ticker": item["ticker"],
            "Company": item["company_name"],
            "Sector": item["sector"],
            "Selected mode score": item["mode_score"],
            "Stage": item["stage"],
            "Exclusion reasons": ", ".join(item["reasons"]),
        }
        for item in result["exclusions"]  # type: ignore[index]
    ]


def comparison_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """Project comparison items in requested order without reranking."""

    rows: list[dict[str, object]] = []
    for item in result["items"]:  # type: ignore[index]
        if item["status"] != "available":
            rows.append(
                {
                    "Position": item["request_position"],
                    "Ticker": item["ticker"],
                    "Status": "Unknown",
                    "Company": None,
                    "Selected mode score": None,
                    "Ranking eligible": None,
                    "Momentum": None,
                    "Quality": None,
                    "Valuation": None,
                    "Risk (higher = lower measured risk)": None,
                    "Sector Strength": None,
                    "Price (USD)": None,
                    "Market data date": None,
                    "Fundamental filing date": None,
                    "Note": item["reason_code"],
                }
            )
            continue
        identity = item["identity"]
        selected_mode = item["selected_mode"]
        factors = item["factor_scores"]
        snapshot = item["market_snapshot"]
        data_dates = item["data_dates"]
        strengths = item["strengths"]
        risks = item["risks"]
        rows.append(
            {
                "Position": item["request_position"],
                "Ticker": item["ticker"],
                "Status": "Available",
                "Company": identity["company_name"],
                "Selected mode score": selected_mode["score"],
                "Ranking eligible": selected_mode["eligible_for_ranking"],
                "Momentum": factors["momentum"],
                "Quality": factors["quality"],
                "Valuation": factors["valuation"],
                "Risk (higher = lower measured risk)": factors["risk"],
                "Sector Strength": factors["sector_strength"],
                "Price (USD)": snapshot["price"],
                "Market data date": data_dates["price_data_end"],
                "Fundamental filing date": data_dates[
                    "fundamental_filed_date"
                ],
                "Note": (
                    strengths[0]["summary"]
                    if strengths
                    else (risks[0]["summary"] if risks else None)
                ),
            }
        )
    return rows


def _format_number(
    value: object,
    *,
    currency: bool = False,
    suffix: str = "",
) -> str:
    if value is None:
        return "Unavailable"
    prefix = "$" if currency else ""
    return f"{prefix}{float(value):,.2f}{suffix}"


def _mode_label(mode: object) -> str:
    return MODE_LABELS.get(str(mode), str(mode))


def _render_disclaimer() -> None:
    st.divider()
    st.caption(DISCLAIMER)


def _render_evidence_items(
    title: str,
    items: Sequence[Mapping[str, object]],
) -> None:
    st.markdown(f"**{title}**")
    if not items:
        st.caption("None reported.")
        return
    for item in items:
        score = item.get("score")
        score_text = "" if score is None else f" ({float(score):.2f})"
        st.markdown(f"- {item['summary']}{score_text}")


def render_analysis_result(
    result: Mapping[str, object],
    rendered_ai: Mapping[str, object] | None = None,
) -> None:
    """Render the narrow unified analysis schema without adding conclusions."""

    identity = result["identity"]  # type: ignore[index]
    scoring = result["scoring"]  # type: ignore[index]
    report = result["report"]  # type: ignore[index]
    posture = report["research_posture"]
    company_name = identity.get("company_name") or result["ticker"]
    st.subheader(f"{result['ticker']} — {company_name}")
    classification = (
        f"{identity.get('sector') or 'Sector unavailable'} · "
        f"{identity.get('industry') or 'Industry unavailable'}"
    )
    st.caption(classification)

    columns = st.columns(4)
    columns[0].metric("Evidence scope", result["data_scope"])
    columns[1].metric("Mode", _mode_label(result["mode"]))
    columns[2].metric(
        "Selected mode score",
        _format_number(scoring["selected_mode_score"]),
    )
    columns[3].metric(
        "Ranking eligibility",
        "Eligible" if scoring["eligible_for_ranking"] else "Not eligible",
    )

    quote = result.get("live_quote")
    if quote:
        quote_columns = st.columns(4)
        quote_columns[0].metric(
            "Latest provider price",
            _format_number(quote.get("price"), currency=True),
        )
        quote_columns[1].metric("Change", _format_number(quote.get("change")))
        quote_columns[2].metric(
            "Percent change",
            _format_number(quote.get("percent_change"), suffix="%"),
        )
        quote_columns[3].metric(
            "Quote time",
            quote.get("provider_datetime") or quote.get("fetched_at_utc"),
        )
        st.caption(
            "The refreshed quote is display-only and is never used to change "
            "factor scores, eligibility, or ranking."
        )

    if result["data_scope"] == "live_unscored":
        st.warning(
            "This ticker is outside the accepted scoring run. Identity and "
            "provider evidence may be shown, but factor scores and rank remain "
            "unavailable without trusted project GICS classification."
        )
        profile = result.get("provider_profile")
        if profile:
            st.caption(
                "Provider taxonomy (not project GICS): "
                f"{profile.get('provider_sector') or 'Unavailable'} · "
                f"{profile.get('provider_industry') or 'Unavailable'}"
            )

    if rendered_ai is None:
        st.markdown(f"### {posture['label']} research fit")
        st.write(report["summary"])
    else:
        renderer = rendered_ai["renderer"]  # type: ignore[index]
        st.markdown("### AI-arranged concise report")
        st.markdown(f"**{rendered_ai['headline']}**")
        st.write(rendered_ai["analysis"])
        if renderer["status"] == "deterministic_fallback":
            st.info(
                "AI rendering was not used; deterministic evidence order was "
                f"returned ({renderer['fallback_reason']})."
            )
        else:
            st.caption(
                f"OpenAI model {renderer['model']} selected only the order of "
                "existing evidence sentences; it could not add facts or advice."
            )
    st.caption(posture["meaning"])

    factor_scores = report["factor_scores"]
    st.dataframe(
        [
            {"Factor": label, "Score": factor_scores.get(name)}
            for name, label in FACTOR_LABELS.items()
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "A higher Risk score means lower measured risk. Null means the accepted "
        "evidence is unavailable; the UI does not impute it."
    )

    strength_column, risk_column = st.columns(2)
    with strength_column:
        _render_evidence_items("Strengths", report["strengths"])
    with risk_column:
        _render_evidence_items("Risks / limitations", report["risks"])

    warnings = list(result.get("warnings", []))
    if warnings:
        st.warning("Warnings: " + "; ".join(str(item) for item in warnings))
    provider_errors = result.get("provider_errors", {})
    if provider_errors:
        for name, message in provider_errors.items():
            st.warning(f"{name}: {message}")

    with st.expander("Dates, quality, and next research questions"):
        st.dataframe(
            [
                {"Date field": name, "Value": value}
                for name, value in report["data_dates"].items()
            ],
            hide_index=True,
            width="stretch",
        )
        quality = report["quality"]
        st.write(
            "Eligible for scoring: "
            + ("Yes" if quality["eligible_for_scoring"] else "No")
        )
        for question in report["next_research_questions"]:
            st.markdown(f"- {question}")


def _render_analyze_view() -> None:
    st.title("Analyze a Ticker")
    st.write(
        "Enter one ticker for a concise evidence-backed report. Accepted-run "
        "securities keep their frozen factor scores; explicit online refresh "
        "adds a display-only latest quote."
    )
    with st.form("ticker_analysis_controls", enter_to_submit=False):
        ticker = st.text_input("Ticker", placeholder="AAPL", key="analysis_ticker")
        mode = st.selectbox(
            "Research mode",
            options=live_analysis.SUPPORTED_MODES,
            format_func=lambda value: MODE_LABELS[value],
            key="analysis_mode",
        )
        refresh = st.checkbox(
            "Refresh identity / latest quote online",
            value=False,
            help=(
                "This is the only control that permits provider network calls. "
                "It never refreshes or changes factor scores."
            ),
            key="analysis_refresh",
        )
        use_ai = st.checkbox(
            "Use OpenAI to arrange the concise accepted-evidence report",
            value=False,
            help=(
                "Optional. The model may only select existing evidence sentence "
                "order and cannot add facts, targets, or buy/sell advice."
            ),
            key="analysis_use_ai",
        )
        submitted = st.form_submit_button(
            "Analyze ticker",
            type="primary",
            key="run_analysis",
            width="stretch",
        )

    if not submitted:
        st.info(
            "Local accepted evidence is the default. Enable online refresh only "
            "when you want a current provider quote or a ticker outside the run."
        )
        _render_disclaimer()
        return

    request = build_analysis_request(ticker=ticker, mode=mode, refresh=refresh)
    try:
        with st.spinner("Loading verified evidence..."):
            result = execute_analysis(request)
    except (
        live_analysis.LiveAnalysisValidationError,
        live_analysis.LiveAnalysisNotFoundError,
        live_analysis.LiveAnalysisDataError,
    ) as error:
        st.error(f"Ticker analysis failed: {error}")
        _render_disclaimer()
        return

    rendered_ai = None
    if use_ai:
        if result["data_scope"] != "accepted_snapshot":
            st.info(
                "AI rendering is skipped because this ticker has no accepted "
                "scoring report to ground it."
            )
        else:
            try:
                with st.spinner("Arranging existing evidence..."):
                    rendered_ai = ai_report.render_ai_research_report(
                        result["report"]
                    )
            except ai_report.AIReportValidationError as error:
                st.error(f"AI report source validation failed: {error}")
    render_analysis_result(result, rendered_ai)
    _render_disclaimer()


def _render_screening_result(result: Mapping[str, object]) -> None:
    metadata = st.columns(4)
    metadata[0].metric("Accepted run ID", result["accepted_run_id"])
    metadata[1].metric("As-of date", result["as_of_date"])
    metadata[2].metric("Returned", result["returned_count"])
    metadata[3].metric("Excluded", result["excluded_count"])
    stocks = result["stocks"]  # type: ignore[index]
    if stocks:
        st.dataframe(ranked_company_rows(result), hide_index=True, width="stretch")
    else:
        st.info("No ranked companies matched the requested filters.")
    st.caption(
        "Rows remain in the deterministic service order. The UI does not "
        "rescore or rerank them."
    )
    unknown = result["unknown_tickers"]  # type: ignore[index]
    if unknown:
        st.warning(
            "Not present in the accepted snapshot: " + ", ".join(unknown)
        )
        st.dataframe(
            [{"Unknown custom ticker": ticker} for ticker in unknown],
            hide_index=True,
            width="stretch",
        )
    exclusions = exclusion_rows(result)
    if exclusions:
        with st.expander("Exclusions and reason codes"):
            st.dataframe(exclusions, hide_index=True, width="stretch")


def _render_screener_view() -> None:
    st.title("Screen Stocks")
    st.write(
        "Filter the verified accepted snapshot by mode, sector, liquidity "
        "proxies, and stored factor scores."
    )
    with st.form("stock_screener_controls", enter_to_submit=False):
        first_column, second_column = st.columns(2)
        with first_column:
            universe = st.selectbox(
                "Universe",
                options=screening.SUPPORTED_UNIVERSES,
                format_func=lambda value: UNIVERSE_LABELS[value],
                key="universe",
            )
            custom_ticker_text = st.text_area(
                "Custom accepted-run tickers (one per line)",
                placeholder="AAPL\nMSFT\nBRK.B",
                key="custom_tickers",
            )
            mode = st.selectbox(
                "Screening mode",
                options=screening.SUPPORTED_MODES,
                format_func=lambda value: MODE_LABELS[value],
                key="mode",
            )
            sectors = st.multiselect(
                "Sectors",
                options=SECTOR_OPTIONS,
                key="sectors",
            )
            top_n = st.number_input(
                "Top N", min_value=1, value=20, step=1, key="top_n"
            )
        with second_column:
            minimum_price = st.number_input(
                "Minimum price (USD)",
                min_value=0.0,
                value=None,
                placeholder="No minimum",
                key="minimum_price",
            )
            minimum_market_cap_proxy = st.number_input(
                "Minimum market-cap proxy (USD)",
                min_value=0.0,
                value=None,
                placeholder="No minimum",
                help="A proxy, not authoritative market capitalization.",
                key="minimum_market_cap_proxy",
            )
            minimum_average_volume_20d = st.number_input(
                "Minimum 20-day average share volume",
                min_value=0.0,
                value=None,
                placeholder="No minimum",
                help="Average daily share volume, not dollar liquidity.",
                key="minimum_average_volume_20d",
            )
            minimum_factor_scores: dict[str, float] = {}
            for factor_name, factor_label in FACTOR_LABELS.items():
                value = st.number_input(
                    f"Minimum {factor_label}",
                    min_value=0.0,
                    max_value=100.0,
                    value=None,
                    placeholder="No minimum",
                    key=f"minimum_factor_{factor_name}",
                )
                if value is not None:
                    minimum_factor_scores[factor_name] = value
        submitted = st.form_submit_button(
            "Run screen", type="primary", key="run_screen", width="stretch"
        )

    if not submitted:
        st.info("Set any optional filters, then run the deterministic screen.")
        _render_disclaimer()
        return
    request = build_screening_request(
        universe=universe,
        custom_ticker_text=custom_ticker_text,
        mode=mode,
        sectors=sectors,
        minimum_price=minimum_price,
        minimum_market_cap_proxy=minimum_market_cap_proxy,
        minimum_average_volume_20d=minimum_average_volume_20d,
        minimum_factor_scores=minimum_factor_scores,
        top_n=top_n,
    )
    try:
        with st.spinner("Verifying and screening the accepted run..."):
            result = execute_screening(request)
    except screening.ScreeningValidationError as error:
        st.error(f"Invalid screening request: {error}")
    except screening.ScreeningDataError as error:
        st.error(f"Accepted screening data error: {error}")
    except scoring_contract.ScoringContractError as error:
        st.error(f"Accepted scoring run could not be verified: {error}")
    else:
        _render_screening_result(result)
    _render_disclaimer()


def _render_comparison_view() -> None:
    st.title("Compare Stocks")
    st.write(
        "Compare two to five accepted-run tickers in the exact order entered. "
        "Stored scores are neither rescaled nor reranked."
    )
    with st.form("comparison_controls", enter_to_submit=False):
        ticker_text = st.text_area(
            "Tickers (one per line)",
            placeholder="AAPL\nMSFT",
            key="comparison_tickers",
        )
        mode = st.selectbox(
            "Comparison mode",
            options=screening.SUPPORTED_MODES,
            format_func=lambda value: MODE_LABELS[value],
            key="comparison_mode",
        )
        submitted = st.form_submit_button(
            "Compare", type="primary", key="run_comparison", width="stretch"
        )
    if not submitted:
        st.info("Enter two to five accepted-run tickers.")
        _render_disclaimer()
        return
    request = {"tickers": ticker_text.splitlines(), "mode": mode}
    try:
        with st.spinner("Loading requested-order evidence..."):
            result = execute_comparison(request)
    except comparison.ComparisonValidationError as error:
        st.error(f"Invalid comparison request: {error}")
    except comparison.ComparisonDataError as error:
        st.error(f"Accepted comparison data error: {error}")
    except scoring_contract.ScoringContractError as error:
        st.error(f"Accepted scoring run could not be verified: {error}")
    else:
        snapshot_parts = []
        if result.get("accepted_run_id") is not None:
            snapshot_parts.append(f"Accepted run {result['accepted_run_id']}")
        if result.get("as_of_date") is not None:
            snapshot_parts.append(f"as of {result['as_of_date']}")
        snapshot_parts.append(_mode_label(result["mode"]))
        st.caption(" · ".join(snapshot_parts))
        st.dataframe(comparison_rows(result), hide_index=True, width="stretch")
        if not result["comparison_available"]:
            st.info(
                "A comparison requires at least two available accepted-run "
                "securities. Unknown rows remain visible in requested order."
            )
        if result["unknown_tickers"]:
            st.warning(
                "Unknown accepted-run tickers: "
                + ", ".join(result["unknown_tickers"])
            )
    _render_disclaimer()


def _overview_metric_rows(scope: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for field_name, summary in scope["metrics"].items():  # type: ignore[index]
        rows.append(
            {
                "Metric": field_name,
                "Median": summary["median"],
                "Coverage": summary["coverage_ratio"],
                "Positive ratio": summary.get("positive_ratio"),
            }
        )
    return rows


def _render_overview_view() -> None:
    st.title("Market / Sector Overview")
    st.write(
        "Summarize the accepted daily snapshot using equal-security medians and "
        "return breadth. This is not a live or capitalization-weighted index."
    )
    with st.form("overview_controls", enter_to_submit=False):
        mode = st.selectbox(
            "Overview mode",
            options=screening.SUPPORTED_MODES,
            format_func=lambda value: MODE_LABELS[value],
            key="overview_mode",
        )
        sectors = st.multiselect(
            "Limit to sectors",
            options=SECTOR_OPTIONS,
            key="overview_sectors",
        )
        submitted = st.form_submit_button(
            "Build overview", type="primary", key="run_overview", width="stretch"
        )
    if not submitted:
        st.info("Leave sectors empty for the full accepted market snapshot.")
        _render_disclaimer()
        return
    request = {"mode": mode, "sectors": sectors or None}
    try:
        with st.spinner("Aggregating accepted evidence..."):
            result = execute_overview(request)
    except overview.OverviewValidationError as error:
        st.error(f"Invalid overview request: {error}")
    except overview.OverviewDataError as error:
        st.error(f"Accepted overview data error: {error}")
    except scoring_contract.ScoringContractError as error:
        st.error(f"Accepted scoring run could not be verified: {error}")
    else:
        header = st.columns(4)
        header[0].metric("Accepted run ID", result["accepted_run_id"])
        header[1].metric("As-of date", result["as_of_date"])
        header[2].metric("Securities", result["market"]["security_count"])
        header[3].metric("Sectors", result["sector_count"])
        price_dates = result["data_dates"]["price_data_end"]
        filing_dates = result["data_dates"]["fundamental_filed_date"]
        st.caption(
            "Market data through "
            f"{price_dates['latest'] or 'Unavailable'} "
            f"({price_dates['available_count']}/"
            f"{result['market']['security_count']} securities); "
            "fundamental filings through "
            f"{filing_dates['latest'] or 'Unavailable'} "
            f"({filing_dates['available_count']}/"
            f"{result['market']['security_count']} securities)."
        )
        st.dataframe(
            _overview_metric_rows(result["market"]),
            hide_index=True,
            width="stretch",
        )
        sector_rows = [
            {
                "Sector": item["sector"],
                "Securities": item["security_count"],
                "Mode eligible": item["mode_eligible_count"],
                "Mode score median": item["metrics"][f"{result['mode']}_score"][
                    "median"
                ],
                "1-month return median": item["metrics"]["return_1m"]["median"],
                "1-month positive ratio": item["metrics"]["return_1m"][
                    "positive_ratio"
                ],
            }
            for item in result["sectors"]
        ]
        st.dataframe(sector_rows, hide_index=True, width="stretch")
        st.caption(
            "Equal-security cross-sectional summary. A higher Risk score means "
            "lower measured risk."
        )
    _render_disclaimer()


def main() -> None:
    st.set_page_config(
        page_title="Equity Research Screener",
        page_icon="📊",
        layout="wide",
    )
    view = st.sidebar.radio(
        "Research task",
        options=(
            "Analyze Ticker",
            "Screen Stocks",
            "Compare Stocks",
            "Market / Sector",
        ),
        key="view",
    )
    st.sidebar.caption(
        "Read-only research. Provider calls require explicit refresh; an "
        "OpenAI call requires its separate checkbox. No trading or personalized "
        "recommendations."
    )
    if view == "Analyze Ticker":
        _render_analyze_view()
    elif view == "Screen Stocks":
        _render_screener_view()
    elif view == "Compare Stocks":
        _render_comparison_view()
    else:
        _render_overview_view()


if __name__ == "__main__":
    main()
