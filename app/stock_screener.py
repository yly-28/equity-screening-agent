"""Minimal Streamlit Stock Screener over the Phase 4 application service."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import scoring_contract, screening, stock_detail


MODE_LABELS = {
    "balanced": "Balanced",
    "growth": "Growth",
    "value": "Value",
    "low_risk": "Low Risk",
}

UNIVERSE_LABELS = {
    "sp500": "Current S&P 500 snapshot",
    "custom": "Custom ticker subset",
}

# The accepted snapshot uses the 11 canonical GICS sector names. The service
# remains the authority that validates every submitted value.
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

DATE_LABELS = {
    "as_of_date": "Screening as-of date",
    "price_data_end": "Market price date",
    "fundamental_period_end": "Latest fundamental period end",
    "fundamental_filed_date": "Latest fundamental filing date",
    "annual_revenue_period_end": "Annual revenue period end",
    "annual_net_income_period_end": "Annual net income period end",
    "profit_margin_period_end": "Profit margin period end",
    "roe_period_end": "ROE period end",
    "leverage_period_end": "Liabilities-to-equity period end",
    "free_cash_flow_period_end": "Free-cash-flow period end",
    "shares_outstanding_period_end": "Shares-outstanding period end",
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
) -> dict[str, object]:
    """Map the eight UI controls directly to ``screen_stocks`` arguments."""

    custom_tickers = (
        custom_ticker_text.splitlines() if universe == "custom" else None
    )
    return {
        "universe": universe,
        "custom_tickers": custom_tickers,
        "mode": mode,
        "sectors": list(sectors) if sectors else None,
        "minimum_price": minimum_price,
        "minimum_market_cap_proxy": minimum_market_cap_proxy,
        "minimum_average_volume_20d": minimum_average_volume_20d,
        "top_n": top_n,
    }


def execute_screening(request: Mapping[str, object]) -> dict[str, object]:
    """Call the Phase 4 service without adding analytical behavior."""

    return screening.screen_stocks(**request)


def build_stock_detail_request(
    *,
    ticker: str,
    mode: str,
) -> dict[str, object]:
    """Map the Stock Detail controls directly to the dedicated service."""

    return {"ticker": ticker, "mode": mode}


def execute_stock_detail(
    request: Mapping[str, object],
) -> dict[str, object]:
    """Call the Stock Detail service without adding analytical behavior."""

    return stock_detail.get_stock_detail(**request)


def ranked_company_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """Project ranked service records for display without filtering or sorting."""

    rows: list[dict[str, object]] = []
    for stock_value in result["stocks"]:  # type: ignore[index]
        stock = stock_value  # type: ignore[assignment]
        factor_scores = stock["factor_scores"]
        data_dates = stock["data_dates"]
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
                "Fundamental period end": data_dates[
                    "fundamental_period_end"
                ],
                "Filing date": data_dates["fundamental_filed_date"],
            }
        )
    return rows


def exclusion_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """Project explicit service exclusions in their existing order."""

    rows: list[dict[str, object]] = []
    for exclusion_value in result["exclusions"]:  # type: ignore[index]
        exclusion = exclusion_value  # type: ignore[assignment]
        rows.append(
            {
                "Ticker": exclusion["ticker"],
                "Company": exclusion["company_name"],
                "Sector": exclusion["sector"],
                "Selected mode score": exclusion["mode_score"],
                "Stage": exclusion["stage"],
                "Exclusion reasons": ", ".join(exclusion["reasons"]),
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
    numeric = float(value)
    prefix = "$" if currency else ""
    return f"{prefix}{numeric:,.2f}{suffix}"


def _format_mode(mode: object) -> str:
    return MODE_LABELS.get(str(mode), str(mode))


def _format_active_filters(result: Mapping[str, object]) -> str:
    filters = result["filters"]  # type: ignore[index]
    sectors = filters["sectors"]
    sector_text = ", ".join(sectors) if sectors else "All sectors"
    minimum_price = filters["minimum_price"]
    minimum_market_cap = filters["minimum_market_cap_proxy"]
    minimum_volume = filters["minimum_average_volume_20d"]
    return "\n".join(
        (
            f"- **Sectors:** {sector_text}",
            "- **Minimum price:** "
            + (
                _format_number(minimum_price, currency=True)
                if minimum_price is not None
                else "None"
            ),
            "- **Minimum market-cap proxy:** "
            + (
                _format_number(minimum_market_cap, currency=True)
                if minimum_market_cap is not None
                else "None"
            ),
            "- **Minimum 20-day average share volume:** "
            + (
                _format_number(minimum_volume, suffix=" shares")
                if minimum_volume is not None
                else "None"
            ),
            f"- **Top N:** {filters['top_n']}",
        )
    )


def _render_snapshot_and_request(result: Mapping[str, object]) -> None:
    st.subheader("Accepted snapshot and request")
    run_column, date_column, mode_column, universe_column = st.columns(4)
    run_column.metric("Accepted run ID", result["accepted_run_id"])
    date_column.metric("As-of date", result["as_of_date"])
    mode_column.metric("Selected mode", _format_mode(result["mode"]))
    universe_column.metric(
        "Universe",
        UNIVERSE_LABELS.get(str(result["universe"]), str(result["universe"])),
    )
    st.caption(
        "Scoring contract "
        f"{result['scoring_contract_version']} · Factor model "
        f"{result['factor_model_version']} · Screening modes "
        f"{result['screening_modes_version']}"
    )
    st.markdown("**Active filters**")
    st.markdown(_format_active_filters(result))


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
        score_text = "" if score is None else f" Score: {float(score):.2f}."
        st.markdown(
            f"- {item['summary']}{score_text} Code: `{item['code']}`"
        )


def _render_stock_detail(stock: Mapping[str, Any]) -> None:
    ticker = stock["ticker"]
    st.markdown(
        f"**{stock['company_name']}** · {stock['sector']} · "
        f"{stock['industry']} · CIK {stock['cik']}"
    )
    score_column, price_column, cap_column, volume_column = st.columns(4)
    score_column.metric(
        f"{_format_mode(stock['screening_mode'])} score",
        f"{float(stock['mode_score']):.2f}",
    )
    price_column.metric(
        "Latest adjusted daily price",
        _format_number(stock["price"], currency=True),
    )
    cap_column.metric(
        "Market-cap proxy",
        _format_number(stock["market_cap_proxy"], currency=True),
    )
    volume_column.metric(
        "20-day average share volume",
        _format_number(stock["average_volume_20d"], suffix=" shares"),
    )
    st.caption(
        "Market-cap proxy is price times validated shares outstanding; it is "
        "not authoritative market capitalization. Volume is measured in "
        "shares. A higher Risk score means lower measured risk."
    )

    factor_scores = stock["factor_scores"]
    st.markdown("**Factor scores**")
    st.dataframe(
        [
            {"Factor": FACTOR_LABELS[factor_name], "Score": factor_scores[factor_name]}
            for factor_name in FACTOR_LABELS
        ],
        hide_index=True,
        width="stretch",
    )

    st.markdown("**Effective factor weights**")
    st.dataframe(
        [
            {
                "Factor": FACTOR_LABELS.get(factor_name, factor_name),
                "Effective factor weight": f"{float(weight):.2%}",
            }
            for factor_name, weight in stock[
                "effective_factor_weights"
            ].items()
        ],
        hide_index=True,
        width="stretch",
    )
    available_factors = stock["available_factors"]
    st.caption(
        "Available factors: "
        + (
            ", ".join(
                FACTOR_LABELS.get(factor_name, factor_name)
                for factor_name in available_factors
            )
            if available_factors
            else "None"
        )
    )

    source_market = stock["data_sources"].get("market") or "Unavailable"
    source_fundamentals = (
        stock["data_sources"].get("fundamentals") or "Unavailable"
    )
    st.markdown(
        f"**Sources:** market `{source_market}` · fundamentals "
        f"`{source_fundamentals}`"
    )
    st.dataframe(
        [
            {
                "Relevant date": DATE_LABELS.get(field_name, field_name),
                "Value": value if value is not None else "Unavailable",
            }
            for field_name, value in stock["data_dates"].items()
        ],
        hide_index=True,
        width="stretch",
    )

    missing_inputs = stock["missing_inputs"]
    if missing_inputs:
        st.info(f"{ticker} missing inputs: " + ", ".join(missing_inputs))
    else:
        st.caption("Missing inputs: none reported.")

    warnings = stock["warnings"]
    if warnings:
        st.warning(f"{ticker} warnings: " + "; ".join(warnings))
    else:
        st.caption("Warnings: none reported.")

    strength_column, risk_column = st.columns(2)
    with strength_column:
        _render_evidence_items("Strengths", stock["strengths"])
    with risk_column:
        _render_evidence_items("Risks", stock["risks"])

    st.markdown("**Reason codes**")
    st.markdown(
        ", ".join(f"`{code}`" for code in stock["reason_codes"])
        or "None reported."
    )
    st.markdown("**Next research questions**")
    for question in stock["next_research_questions"]:
        st.markdown(f"- {question}")


def _render_ranked_companies(result: Mapping[str, object]) -> None:
    st.subheader("Ranked companies")
    count_columns = st.columns(4)
    count_columns[0].metric("Candidates", result["candidate_count"])
    count_columns[1].metric(
        "Ranking eligible", result["ranking_eligible_count"]
    )
    count_columns[2].metric("Returned", result["returned_count"])
    count_columns[3].metric("Excluded", result["excluded_count"])

    stocks = result["stocks"]  # type: ignore[index]
    if not stocks:
        st.info(
            "No ranked companies matched the selected mode and requested "
            "filters. Review the explicit exclusions below."
        )
        return

    st.dataframe(
        ranked_company_rows(result),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Rows remain in the deterministic order returned by screen_stocks. "
        "The UI does not rescore or rerank them."
    )
    for stock in stocks:
        with st.expander(
            f"#{stock['rank']} {stock['ticker']} — {stock['company_name']}"
        ):
            _render_stock_detail(stock)


def _render_unknown_tickers(result: Mapping[str, object]) -> None:
    unknown_tickers = result["unknown_tickers"]  # type: ignore[index]
    if not unknown_tickers:
        return
    st.subheader("Unknown custom tickers")
    st.warning(
        "These custom tickers are not present in the accepted local S&P 500 "
        "snapshot and were not fetched or scored: "
        + ", ".join(unknown_tickers)
    )
    st.dataframe(
        [{"Unknown custom ticker": ticker} for ticker in unknown_tickers],
        hide_index=True,
        width="stretch",
    )


def _render_exclusions(result: Mapping[str, object]) -> None:
    st.subheader("Explicit exclusions")
    st.caption(
        f"Mode ineligible: {result['mode_ineligible_count']} · "
        f"Filter excluded: {result['filter_excluded_count']} · "
        f"Outside top N: {result['top_n_excluded_count']}"
    )
    rows = exclusion_rows(result)
    if not rows:
        st.caption("No known candidate tickers were excluded.")
        return
    st.dataframe(rows, hide_index=True, width="stretch")


def render_screening_result(result: Mapping[str, object]) -> None:
    """Render one service response without changing its analytical content."""

    _render_snapshot_and_request(result)
    _render_ranked_companies(result)
    _render_unknown_tickers(result)
    _render_exclusions(result)


def _render_stock_detail_header(result: Mapping[str, object]) -> None:
    identity = result["identity"]  # type: ignore[index]
    selected_mode = result["selected_mode"]  # type: ignore[index]
    st.subheader(
        f"{identity['ticker']} — {identity['company_name']}"
    )
    st.write(
        f"{identity['sector']} · {identity['industry']} · "
        f"CIK {identity['cik']}"
    )
    sec_entity_name = identity["sec_entity_name"]
    if sec_entity_name:
        st.caption(f"SEC entity name: {sec_entity_name}")

    run_column, date_column, mode_column, eligibility_column = st.columns(4)
    run_column.metric("Accepted run ID", result["accepted_run_id"])
    date_column.metric("As-of date", result["as_of_date"])
    mode_column.metric("Selected mode", _format_mode(result["mode"]))
    eligibility_column.metric(
        "Mode ranking eligibility",
        (
            "Eligible"
            if selected_mode["eligible_for_ranking"]
            else "Not eligible"
        ),
    )
    st.caption(
        "Scoring contract "
        f"{result['scoring_contract_version']} · Factor model "
        f"{result['factor_model_version']} · Screening modes "
        f"{result['screening_modes_version']} · Input feature run "
        f"{result['input_feature_run_id']} · Data contract "
        f"{result['input_contract_version']}"
    )

    score_column, factors_column = st.columns(2)
    score_column.metric(
        f"{_format_mode(result['mode'])} score",
        _format_number(selected_mode["score"]),
    )
    factors_column.metric(
        "Available factors",
        selected_mode["factor_count"]
        if selected_mode["factor_count"] is not None
        else "Unavailable",
    )
    if selected_mode["ranking_exclusion_reasons"]:
        st.warning(
            "Selected-mode ranking exclusion reasons: "
            + ", ".join(selected_mode["ranking_exclusion_reasons"])
        )
    if selected_mode["unavailable_reason"]:
        st.warning(
            "Selected-mode score unavailable reason: "
            + str(selected_mode["unavailable_reason"])
        )


def _render_detail_market(result: Mapping[str, object]) -> None:
    st.subheader("Market snapshot and verified history coverage")
    snapshot = result["market_snapshot"]  # type: ignore[index]
    price_column, cap_column, volume_column = st.columns(3)
    price_column.metric(
        "Latest adjusted daily price",
        _format_number(snapshot["price"], currency=True),
    )
    cap_column.metric(
        "Market-cap proxy",
        _format_number(snapshot["market_cap_proxy"], currency=True),
    )
    volume_column.metric(
        "20-day average share volume",
        _format_number(
            snapshot["average_volume_20d"],
            suffix=" shares",
        ),
    )
    st.caption(
        "Market-cap proxy is price times validated shares outstanding; it is "
        "not authoritative market capitalization. Volume is measured in "
        "shares, and the market snapshot is latest-available daily data."
    )

    history = result["price_history"]  # type: ignore[index]
    history_columns = st.columns(4)
    history_columns[0].metric("Price-history source", history["source"])
    history_columns[1].metric("History start", history["start_date"])
    history_columns[2].metric("History end", history["end_date"])
    history_columns[3].metric("History rows used", history["history_rows"])
    if history["series_available"]:
        st.dataframe(
            history["series"],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info(history["availability_reason"])

    st.markdown("**Stored market features**")
    st.dataframe(
        result["market_features"],
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Market data-quality evidence**")
    st.dataframe(
        [
            {
                "Evidence": field_name,
                "Value": "Unavailable" if value is None else str(value),
            }
            for field_name, value in result[  # type: ignore[union-attr]
                "market_quality"
            ].items()
        ],
        hide_index=True,
        width="stretch",
    )


def _render_detail_fundamentals(result: Mapping[str, object]) -> None:
    st.subheader("Fundamentals and filing dates")
    fundamentals = result["fundamentals"]  # type: ignore[index]
    source_column, period_column, filing_column, age_column = st.columns(4)
    source_column.metric("Fundamental source", fundamentals["source"])
    period_column.metric(
        "Latest fiscal period end",
        fundamentals["latest_period_end"],
    )
    filing_column.metric(
        "Latest filing across included fundamentals",
        fundamentals["latest_filed_date"],
    )
    age_column.metric(
        "Fundamental age at as-of date",
        (
            f"{fundamentals['fundamental_age_days']} days"
            if fundamentals["fundamental_age_days"] is not None
            else "Unavailable"
        ),
    )
    st.dataframe(
        fundamentals["metrics"],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "The filing date above is snapshot-wide: it is the latest filing date "
        "across included fundamental inputs. Metric-specific filing dates are "
        "not stored in the accepted artifact. "
        "Market-cap and annual P/E values are stored historical proxies, not "
        "authoritative vendor market capitalization or forward/vendor P/E. "
        "Raw profit margin is audit-only; the validated profit margin is the "
        "scoring input."
    )


def _render_detail_factors(result: Mapping[str, object]) -> None:
    st.subheader("Factor and metric evidence")
    selected_mode = result["selected_mode"]  # type: ignore[index]
    factor_details = result["factor_details"]  # type: ignore[index]
    st.dataframe(
        [
            {
                "Factor": factor["label"],
                "Score": factor["score"],
                "Available component count": factor["component_count"],
                "Unavailable reason": factor["unavailable_reason"],
            }
            for factor in factor_details
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "A higher Risk score means lower measured risk. A higher Sector "
        "Strength score means stronger measured sector relative strength."
    )

    st.markdown("**Selected-mode effective factor weights**")
    st.dataframe(
        [
            {
                "Factor": FACTOR_LABELS.get(factor_name, factor_name),
                "Effective factor weight": weight,
            }
            for factor_name, weight in selected_mode[
                "effective_factor_weights"
            ].items()
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Available factors: "
        + (
            ", ".join(
                FACTOR_LABELS.get(factor_name, factor_name)
                for factor_name in selected_mode["available_factors"]
            )
            if selected_mode["available_factors"]
            else "None"
        )
    )

    for factor in factor_details:
        with st.expander(f"{factor['label']} metric evidence"):
            st.write(
                "Effective metric weights: "
                + (
                    ", ".join(
                        f"{metric}={weight:.2%}"
                        for metric, weight in factor[
                            "effective_metric_weights"
                        ].items()
                    )
                    if factor["effective_metric_weights"]
                    else "None"
                )
            )
            st.caption(
                "Available components: "
                + (
                    ", ".join(factor["available_components"])
                    if factor["available_components"]
                    else "None"
                )
            )
            if factor["unavailable_reason"]:
                st.warning(
                    "Factor unavailable reason: "
                    + str(factor["unavailable_reason"])
                )
            st.dataframe(
                factor["components"],
                hide_index=True,
                width="stretch",
            )


def _render_detail_sector_context(result: Mapping[str, object]) -> None:
    st.subheader("Sector context")
    context = result["sector_context"]  # type: ignore[index]
    st.dataframe(
        [
            {
                "Sector": context["sector"],
                "Industry": context["industry"],
                "Company 3-month relative strength versus SPY": context[
                    "company_relative_strength_3m"
                ],
                "Sector median 3-month relative strength": context[
                    "sector_median_relative_strength_3m"
                ],
                "Sector strength member count": context[
                    "sector_strength_member_count"
                ],
                "Sector Strength score": context["sector_strength_score"],
            }
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Sector context is limited to stored accepted-snapshot evidence; this "
        "view does not create a market or sector overview."
    )


def _render_detail_quality_and_explanations(
    result: Mapping[str, object],
) -> None:
    st.subheader("Quality, provenance, and research evidence")
    quality = result["quality"]  # type: ignore[index]
    st.metric(
        "Base scoring eligibility",
        "Eligible" if quality["eligible_for_scoring"] else "Not eligible",
    )
    if quality["missing_inputs"]:
        st.info("Missing inputs: " + ", ".join(quality["missing_inputs"]))
    else:
        st.caption("Missing inputs: none reported.")
    if quality["warnings"]:
        st.warning("Warnings: " + "; ".join(quality["warnings"]))
    else:
        st.caption("Warnings: none reported.")
    if quality["stale_fundamental_metrics"]:
        st.warning(
            "Stale fundamental metrics: "
            + ", ".join(quality["stale_fundamental_metrics"])
        )
    if quality["base_exclusion_reasons"]:
        st.warning(
            "Base scoring exclusion reasons: "
            + ", ".join(quality["base_exclusion_reasons"])
        )
    for error_name in ("market_error", "fundamental_error"):
        if quality[error_name]:
            st.warning(f"{error_name}: {quality[error_name]}")

    st.markdown("**Relevant market and fundamental dates**")
    st.dataframe(
        [
            {
                "Relevant date": DATE_LABELS.get(field_name, field_name),
                "Value": value if value is not None else "Unavailable",
            }
            for field_name, value in result[  # type: ignore[union-attr]
                "data_dates"
            ].items()
        ],
        hide_index=True,
        width="stretch",
    )

    strength_column, risk_column = st.columns(2)
    with strength_column:
        _render_evidence_items(
            "Strengths",
            result["strengths"],  # type: ignore[arg-type]
        )
    with risk_column:
        _render_evidence_items("Risks", result["risks"])  # type: ignore[arg-type]

    st.markdown("**Reason codes**")
    st.markdown(
        ", ".join(f"`{code}`" for code in result["reason_codes"])  # type: ignore[index]
        or "None reported."
    )
    st.markdown("**Next research questions**")
    questions = result["next_research_questions"]  # type: ignore[index]
    if questions:
        for question in questions:
            st.markdown(f"- {question}")
    else:
        st.caption("None reported.")


def render_stock_detail_result(result: Mapping[str, object]) -> None:
    """Render one detail-service response without adding analytics."""

    _render_stock_detail_header(result)
    _render_detail_market(result)
    _render_detail_fundamentals(result)
    _render_detail_factors(result)
    _render_detail_sector_context(result)
    _render_detail_quality_and_explanations(result)


def _render_known_error(error: Exception) -> None:
    if isinstance(error, screening.ScreeningValidationError):
        st.error(f"Invalid screening request: {error}")
        return
    if isinstance(error, screening.ScreeningDataError):
        st.error(f"Accepted screening data error: {error}")
        return
    st.error(f"Accepted scoring run could not be verified: {error}")


def _render_stock_detail_error(error: Exception) -> None:
    if isinstance(error, stock_detail.StockDetailValidationError):
        st.error(f"Invalid Stock Detail request: {error}")
        return
    if isinstance(error, stock_detail.StockDetailNotFoundError):
        st.error(f"Stock Detail ticker not found: {error}")
        return
    if isinstance(error, stock_detail.StockDetailDataError):
        st.error(f"Accepted Stock Detail data error: {error}")
        return
    st.error(f"Accepted scoring run could not be verified: {error}")


def _render_disclaimer() -> None:
    st.divider()
    st.caption(DISCLAIMER)


def _render_screener_view() -> None:
    st.title("Equity Screening Agent")
    st.write(
        "Screen the frozen accepted local scoring snapshot. All eligibility, "
        "validation, filtering, ticker normalization, sorting, scores, weights, "
        "and explanations come from `src.screening.screen_stocks`."
    )
    st.caption(
        "Latest-available daily-data research support · Local and "
        "network-independent · No rescoring in Streamlit"
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
                "Custom tickers (one per line)",
                placeholder="AAPL\nMSFT\nBRK.B",
                help=(
                    "Used only for the custom universe. Ticker normalization "
                    "and unknown-ticker handling remain in screen_stocks."
                ),
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
                help="Leave empty to include all sectors.",
                key="sectors",
            )
        with second_column:
            minimum_price = st.number_input(
                "Minimum price (USD)",
                min_value=0.0,
                value=None,
                placeholder="No minimum",
                help="Latest adjusted daily price.",
                key="minimum_price",
            )
            minimum_market_cap_proxy = st.number_input(
                "Minimum market-cap proxy (USD)",
                min_value=0.0,
                value=None,
                placeholder="No minimum",
                help=(
                    "Price times validated shares outstanding. This is a proxy, "
                    "not authoritative market capitalization."
                ),
                key="minimum_market_cap_proxy",
            )
            minimum_average_volume_20d = st.number_input(
                "Minimum 20-day average share volume (shares)",
                min_value=0.0,
                value=None,
                placeholder="No minimum",
                help="Average daily share volume over the trailing 20 days.",
                key="minimum_average_volume_20d",
            )
            top_n = st.number_input(
                "Top N",
                min_value=1,
                value=20,
                step=1,
                key="top_n",
            )
        submitted = st.form_submit_button(
            "Run screen",
            type="primary",
            key="run_screen",
            width="stretch",
        )

    if not submitted:
        st.info(
            "Choose the screening inputs and select **Run screen**. The accepted "
            "artifact is verified only when a screen is requested."
        )
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
        top_n=top_n,
    )
    try:
        with st.spinner("Verifying the accepted run and screening companies..."):
            result = execute_screening(request)
    except (
        screening.ScreeningValidationError,
        screening.ScreeningDataError,
        scoring_contract.ScoringContractError,
    ) as error:
        _render_known_error(error)
        _render_disclaimer()
        return

    render_screening_result(result)
    _render_disclaimer()


def _render_stock_detail_view() -> None:
    st.title("Equity Screening Agent")
    st.write(
        "Inspect one security in the frozen accepted local scoring snapshot. "
        "Ticker normalization, validation, stored feature projection, factor "
        "evidence, eligibility, and explanations come from "
        "`src.stock_detail.get_stock_detail`."
    )
    st.caption(
        "Latest-available daily-data research support · Local and "
        "network-independent · No scoring, ranking, or provider calls in "
        "Streamlit"
    )

    with st.form("stock_detail_controls", enter_to_submit=False):
        ticker = st.text_input(
            "Ticker",
            placeholder="AAPL",
            help=(
                "Enter a ticker from the accepted local S&P 500 snapshot. "
                "Unknown tickers are not fetched."
            ),
            key="detail_ticker",
        )
        mode = st.selectbox(
            "Stock Detail screening mode",
            options=stock_detail.SUPPORTED_MODES,
            format_func=lambda value: MODE_LABELS[value],
            key="detail_mode",
        )
        submitted = st.form_submit_button(
            "Load Stock Detail",
            type="primary",
            key="load_stock_detail",
            width="stretch",
        )

    if not submitted:
        st.info(
            "Enter one accepted-snapshot ticker and select **Load Stock "
            "Detail**. The accepted artifact is verified only when detail is "
            "requested."
        )
        _render_disclaimer()
        return

    request = build_stock_detail_request(ticker=ticker, mode=mode)
    try:
        with st.spinner(
            "Verifying the accepted run and loading stored evidence..."
        ):
            result = execute_stock_detail(request)
    except (
        stock_detail.StockDetailValidationError,
        stock_detail.StockDetailNotFoundError,
        stock_detail.StockDetailDataError,
        scoring_contract.ScoringContractError,
    ) as error:
        _render_stock_detail_error(error)
        _render_disclaimer()
        return

    render_stock_detail_result(result)
    _render_disclaimer()


def main() -> None:
    st.set_page_config(
        page_title="Equity Screening Agent",
        page_icon="📊",
        layout="wide",
    )
    view = st.sidebar.radio(
        "View",
        options=("Stock Screener", "Stock Detail"),
        key="view",
    )
    st.sidebar.caption(
        "Both views use the same frozen accepted local scoring boundary."
    )
    if view == "Stock Detail":
        _render_stock_detail_view()
        return
    _render_screener_view()


if __name__ == "__main__":
    main()
