"""SEC Company Facts adapter and conservative annual fundamental extraction."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests
from dotenv import load_dotenv

from src.http_client import build_session


SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
CURRENT_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A", "6-K", "6-K/A"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class FundamentalDataError(RuntimeError):
    """Raised when SEC Company Facts cannot be retrieved or interpreted."""


@dataclass
class SecCompanyFactsClient:
    """Retrieve and cache SEC Company Facts responses."""

    cache_dir: Path
    timeout: int = 45
    pause_seconds: float = 0.15
    session: requests.Session = field(init=False)

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        user_agent = os.getenv(
            "SEC_USER_AGENT",
            "equity-screening-agent/0.1 academic-data-feasibility",
        )
        self.session = build_session(user_agent, {"Accept-Encoding": "gzip, deflate"})

    def company_facts(self, cik: str, refresh: bool = False) -> Dict[str, Any]:
        normalized_cik = str(cik).zfill(10)
        cache_path = self.cache_dir / f"CIK{normalized_cik}.json"
        if cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        response = self.session.get(
            SEC_COMPANY_FACTS_URL.format(cik=normalized_cik),
            timeout=self.timeout,
        )
        time.sleep(self.pause_seconds)
        if response.status_code != 200:
            raise FundamentalDataError(
                f"SEC returned HTTP {response.status_code} for CIK {normalized_cik}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise FundamentalDataError(
                f"SEC returned non-JSON data for CIK {normalized_cik}"
            ) from exc

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload


def _parse_iso_date(value: object) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _annual_records(
    payload: Dict[str, Any],
    tag_candidates: Sequence[str],
    units: Sequence[str],
    duration: bool,
) -> List[Dict[str, object]]:
    us_gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    records: List[Dict[str, object]] = []
    for tag_priority, tag in enumerate(tag_candidates):
        tag_data = us_gaap.get(tag) or {}
        units_data = tag_data.get("units") or {}
        for unit in units:
            for entry in units_data.get(unit, []):
                if entry.get("form") not in ANNUAL_FORMS or entry.get("fp") != "FY":
                    continue
                end = _parse_iso_date(entry.get("end"))
                start = _parse_iso_date(entry.get("start"))
                if end is None:
                    continue
                if duration:
                    if start is None:
                        continue
                    days = (end - start).days
                    if not 300 <= days <= 430:
                        continue
                try:
                    numeric_value = float(entry["val"])
                except (KeyError, TypeError, ValueError):
                    continue
                records.append(
                    {
                        "end": end.isoformat(),
                        "start": start.isoformat() if start else None,
                        "filed": entry.get("filed"),
                        "value": numeric_value,
                        "tag": tag,
                        "unit": unit,
                        "tag_priority": tag_priority,
                    }
                )

    # Companies frequently transition between synonymous XBRL tags. Merge by
    # fiscal period so a stale high-priority tag cannot hide current data.
    by_end: Dict[str, Dict[str, object]] = {}
    for record in records:
        end = str(record["end"])
        prior = by_end.get(end)
        if prior is None:
            by_end[end] = record
            continue
        record_priority = int(record["tag_priority"])
        prior_priority = int(prior["tag_priority"])
        if record_priority < prior_priority or (
            record_priority == prior_priority
            and str(record.get("filed", "")) > str(prior.get("filed", ""))
        ):
            by_end[end] = record

    merged = sorted(by_end.values(), key=lambda item: str(item["end"]))
    for record in merged:
        record.pop("tag_priority", None)
    return merged


def _latest_instant_record(
    payload: Dict[str, Any],
    taxonomy: str,
    tag_candidates: Sequence[str],
    units: Sequence[str],
) -> Optional[Dict[str, object]]:
    taxonomy_facts = ((payload.get("facts") or {}).get(taxonomy) or {})
    records: List[Dict[str, object]] = []
    for tag_priority, tag in enumerate(tag_candidates):
        tag_data = taxonomy_facts.get(tag) or {}
        units_data = tag_data.get("units") or {}
        for unit in units:
            for entry in units_data.get(unit, []):
                if entry.get("form") not in CURRENT_FORMS:
                    continue
                end = _parse_iso_date(entry.get("end"))
                if end is None:
                    continue
                try:
                    numeric_value = float(entry["val"])
                except (KeyError, TypeError, ValueError):
                    continue
                records.append(
                    {
                        "end": end.isoformat(),
                        "filed": entry.get("filed"),
                        "value": numeric_value,
                        "tag": f"{taxonomy}:{tag}",
                        "unit": unit,
                        "tag_priority": tag_priority,
                    }
                )
    if not records:
        return None
    records.sort(
        key=lambda item: (
            str(item["end"]),
            str(item.get("filed", "")),
            -int(item["tag_priority"]),
        )
    )
    latest = records[-1]
    latest.pop("tag_priority", None)
    return latest


def _latest(records: Sequence[Dict[str, object]]) -> Optional[Dict[str, object]]:
    return records[-1] if records else None


def _aligned_ratio(
    numerator: Optional[Dict[str, object]],
    denominator: Optional[Dict[str, object]],
) -> Optional[float]:
    if not numerator or not denominator or numerator["end"] != denominator["end"]:
        return None
    denominator_value = float(denominator["value"])
    if denominator_value == 0:
        return None
    return float(numerator["value"]) / denominator_value


def _latest_aligned_pair(
    left_records: Sequence[Dict[str, object]],
    right_records: Sequence[Dict[str, object]],
) -> tuple:
    left_by_end = {str(item["end"]): item for item in left_records}
    right_by_end = {str(item["end"]): item for item in right_records}
    common_ends = sorted(set(left_by_end) & set(right_by_end))
    if not common_ends:
        return None, None
    latest_end = common_ends[-1]
    return left_by_end[latest_end], right_by_end[latest_end]


def _value(record: Optional[Dict[str, object]]) -> Optional[float]:
    return float(record["value"]) if record else None


def _tag(record: Optional[Dict[str, object]]) -> Optional[str]:
    return str(record["tag"]) if record else None


def extract_sec_fundamentals(payload: Dict[str, Any]) -> Dict[str, object]:
    """Extract comparable annual fields without pretending SEC tags are uniform."""

    revenue_records = _annual_records(
        payload,
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ),
        ("USD",),
        duration=True,
    )
    net_income_records = _annual_records(
        payload,
        ("NetIncomeLoss", "ProfitLoss"),
        ("USD",),
        duration=True,
    )
    equity_records = _annual_records(
        payload,
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        ("USD",),
        duration=False,
    )
    liabilities_records = _annual_records(
        payload,
        ("Liabilities",),
        ("USD",),
        duration=False,
    )
    assets_records = _annual_records(
        payload,
        ("Assets",),
        ("USD",),
        duration=False,
    )
    operating_cash_flow_records = _annual_records(
        payload,
        ("NetCashProvidedByUsedInOperatingActivities",),
        ("USD",),
        duration=True,
    )
    capex_records = _annual_records(
        payload,
        (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
            "PaymentsToAcquireOilAndGasPropertyAndEquipment",
            "PaymentsForProceedsFromOtherPropertyPlantAndEquipment",
        ),
        ("USD",),
        duration=True,
    )
    eps_records = _annual_records(
        payload,
        ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
        ("USD/shares",),
        duration=True,
    )
    shares = _latest_instant_record(
        payload,
        "dei",
        ("EntityCommonStockSharesOutstanding",),
        ("shares",),
    ) or _latest_instant_record(
        payload,
        "us-gaap",
        ("CommonStockSharesOutstanding",),
        ("shares",),
    )

    revenue = _latest(revenue_records)
    previous_revenue = revenue_records[-2] if len(revenue_records) >= 2 else None
    net_income = _latest(net_income_records)
    equity = _latest(equity_records)
    liabilities = _latest(liabilities_records)
    assets = _latest(assets_records)
    operating_cash_flow = _latest(operating_cash_flow_records)
    capex = _latest(capex_records)
    eps = _latest(eps_records)

    revenue_growth = None
    if revenue and previous_revenue and float(previous_revenue["value"]) != 0:
        revenue_growth = (
            float(revenue["value"]) / float(previous_revenue["value"]) - 1
        )

    margin_income, margin_revenue = _latest_aligned_pair(
        net_income_records, revenue_records
    )
    roe_income, roe_equity = _latest_aligned_pair(net_income_records, equity_records)
    leverage_liabilities, leverage_equity = _latest_aligned_pair(
        liabilities_records, equity_records
    )
    cash_flow_aligned, capex_aligned = _latest_aligned_pair(
        operating_cash_flow_records, capex_records
    )

    profit_margin = _aligned_ratio(margin_income, margin_revenue)
    profit_margin_warning = (
        "absolute_value_above_1"
        if profit_margin is not None and abs(profit_margin) > 1
        else None
    )
    roe = _aligned_ratio(roe_income, roe_equity)
    equity_warning = None
    if roe_equity and float(roe_equity["value"]) <= 0:
        roe = None
        equity_warning = "nonpositive_stockholders_equity"

    liabilities_source_tag = _tag(leverage_liabilities)
    liabilities_to_equity = _aligned_ratio(leverage_liabilities, leverage_equity)
    if leverage_equity and float(leverage_equity["value"]) <= 0:
        liabilities_to_equity = None
        equity_warning = "nonpositive_stockholders_equity"
    effective_liabilities = _value(leverage_liabilities)
    leverage_period_end = leverage_equity["end"] if leverage_equity else None
    if liabilities_to_equity is None:
        aligned_assets, aligned_equity = _latest_aligned_pair(
            assets_records, equity_records
        )
        if aligned_assets and aligned_equity:
            derived_liabilities = float(aligned_assets["value"]) - float(
                aligned_equity["value"]
            )
            effective_liabilities = derived_liabilities
            liabilities_source_tag = "AssetsMinusStockholdersEquity"
            leverage_period_end = aligned_equity["end"]
            if float(aligned_equity["value"]) > 0:
                liabilities_to_equity = derived_liabilities / float(
                    aligned_equity["value"]
                )

    free_cash_flow = None
    if cash_flow_aligned and capex_aligned:
        free_cash_flow = float(cash_flow_aligned["value"]) - abs(
            float(capex_aligned["value"])
        )

    period_candidates = [
        item["end"]
        for item in (revenue, net_income, equity, operating_cash_flow)
        if item
    ]
    filed_candidates = [
        item.get("filed")
        for item in (revenue, net_income, equity, operating_cash_flow)
        if item and item.get("filed")
    ]
    fundamental_period_end = max(period_candidates) if period_candidates else None
    shares_value = _value(shares)
    shares_warning = None
    if shares is None:
        shares_warning = "missing"
    elif shares_value is None or shares_value < 100_000:
        shares_warning = "implausible_value"
        shares_value = None
    elif fundamental_period_end:
        shares_end = _parse_iso_date(shares["end"])
        fundamentals_end = _parse_iso_date(fundamental_period_end)
        if (
            shares_end
            and fundamentals_end
            and (fundamentals_end - shares_end).days > 550
        ):
            shares_warning = "stale_relative_to_fundamentals"
            shares_value = None

    return {
        "sec_entity_name": payload.get("entityName"),
        "fundamental_period_end": fundamental_period_end,
        "fundamental_filed_date": max(filed_candidates) if filed_candidates else None,
        "annual_revenue": _value(revenue),
        "annual_net_income": _value(net_income),
        "stockholders_equity": _value(equity),
        "total_liabilities": effective_liabilities,
        "total_assets": _value(assets),
        "annual_operating_cash_flow": _value(operating_cash_flow),
        "annual_capex": _value(capex),
        "annual_free_cash_flow": free_cash_flow,
        "annual_diluted_eps": _value(eps),
        "shares_outstanding": shares_value,
        "shares_outstanding_period_end": shares["end"] if shares else None,
        "shares_quality_warning": shares_warning,
        "revenue_growth": revenue_growth,
        "profit_margin": profit_margin,
        "profit_margin_period_end": margin_income["end"] if margin_income else None,
        "profit_margin_quality_warning": profit_margin_warning,
        "roe": roe,
        "roe_period_end": roe_income["end"] if roe_income else None,
        "liabilities_to_equity": liabilities_to_equity,
        "equity_quality_warning": equity_warning,
        "leverage_period_end": leverage_period_end,
        "free_cash_flow_period_end": (
            cash_flow_aligned["end"] if cash_flow_aligned else None
        ),
        "revenue_source_tag": _tag(revenue),
        "net_income_source_tag": _tag(net_income),
        "equity_source_tag": _tag(equity),
        "liabilities_source_tag": liabilities_source_tag,
        "cash_flow_source_tag": _tag(operating_cash_flow),
        "capex_source_tag": _tag(capex_aligned),
        "shares_source_tag": _tag(shares),
    }
