"""SEC Company Facts adapter and conservative annual fundamental extraction."""

from __future__ import annotations

import json
import math
import os
import re
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

    def is_cached(self, cik: str) -> bool:
        """Return whether Company Facts is cached for a normalized CIK."""

        normalized_cik = str(cik).zfill(10)
        return (self.cache_dir / f"CIK{normalized_cik}.json").exists()

    def company_facts_cached(self, cik: str) -> Dict[str, Any]:
        """Read Company Facts from cache without a network fallback."""

        normalized_cik = str(cik).zfill(10)
        cache_path = self.cache_dir / f"CIK{normalized_cik}.json"
        if not cache_path.exists():
            raise FundamentalDataError(
                f"SEC Company Facts cache not found for CIK {normalized_cik}"
            )
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FundamentalDataError(
                f"Invalid SEC Company Facts cache for CIK {normalized_cik}"
            ) from exc

    def company_facts(self, cik: str, refresh: bool = False) -> Dict[str, Any]:
        normalized_cik = str(cik).zfill(10)
        cache_path = self.cache_dir / f"CIK{normalized_cik}.json"
        if cache_path.exists() and not refresh:
            return self.company_facts_cached(normalized_cik)

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
    filed_on_or_before: Optional[date] = None,
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
                filed = _parse_iso_date(entry.get("filed"))
                if filed_on_or_before is not None and (
                    filed is None or filed > filed_on_or_before
                ):
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
                if not math.isfinite(numeric_value):
                    continue
                records.append(
                    {
                        "end": end.isoformat(),
                        "start": start.isoformat() if start else None,
                        "filed": entry.get("filed"),
                        "accn": entry.get("accn"),
                        "frame": entry.get("frame"),
                        "fy": entry.get("fy"),
                        "fp": entry.get("fp"),
                        "form": entry.get("form"),
                        "value": numeric_value,
                        "tag": tag,
                        "unit": unit,
                        "tag_priority": tag_priority,
                    }
                )

    # Prefer the first declared synonym, an annual frame, and the latest filing.
    # If the winning filing context contains conflicting values, omit that
    # tag-period rather than selecting an arbitrary array order.
    by_end: Dict[str, List[Dict[str, object]]] = {}
    for record in records:
        by_end.setdefault(str(record["end"]), []).append(record)

    merged: List[Dict[str, object]] = []
    for end in sorted(by_end):
        candidates = by_end[end]

        def selection_key(item: Dict[str, object]) -> tuple:
            frame = str(item.get("frame") or "")
            frame_rank = 2 if re.fullmatch(r"CY\d{4}", frame) else 1 if not frame else 0
            return (
                -int(item["tag_priority"]),
                frame_rank,
                str(item.get("filed") or ""),
                str(item.get("accn") or ""),
            )

        winning_key = max(selection_key(item) for item in candidates)
        winners = [item for item in candidates if selection_key(item) == winning_key]
        winning_values = {float(item["value"]) for item in winners}
        if len(winning_values) != 1:
            continue
        merged.append(dict(sorted(winners, key=lambda item: str(item["tag"]))[0]))

    for record in merged:
        record.pop("tag_priority", None)
    return merged


def _latest_instant_record(
    payload: Dict[str, Any],
    taxonomy: str,
    tag_candidates: Sequence[str],
    units: Sequence[str],
    filed_on_or_before: Optional[date] = None,
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
                filed = _parse_iso_date(entry.get("filed"))
                if filed_on_or_before is not None and (
                    filed is None or filed > filed_on_or_before
                ):
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


def _same_filing_context(
    left: Dict[str, object], right: Dict[str, object]
) -> bool:
    """Require composite revenue components to come from one annual filing context."""

    return all(
        left.get(field) == right.get(field)
        for field in ("start", "end", "filed", "accn", "frame")
    )


def _sum_aligned_records(
    left_records: Sequence[Dict[str, object]],
    right_records: Sequence[Dict[str, object]],
    source_label: str,
) -> List[Dict[str, object]]:
    """Build non-overlapping annual revenue composites from aligned SEC facts."""

    left_by_end = {str(item["end"]): item for item in left_records}
    right_by_end = {str(item["end"]): item for item in right_records}
    combined: List[Dict[str, object]] = []
    for end in sorted(set(left_by_end) & set(right_by_end)):
        left = left_by_end[end]
        right = right_by_end[end]
        if not _same_filing_context(left, right):
            continue
        total_value = float(left["value"]) + float(right["value"])
        if not math.isfinite(total_value) or total_value <= 0:
            continue
        combined.append(
            {
                "end": end,
                "start": left.get("start") or right.get("start"),
                "filed": left.get("filed"),
                "accn": left.get("accn") or right.get("accn"),
                "frame": left.get("frame") or right.get("frame"),
                "fy": left.get("fy") or right.get("fy"),
                "fp": left.get("fp") or right.get("fp"),
                "form": left.get("form") or right.get("form"),
                "value": total_value,
                "tag": source_label,
                "unit": "USD",
                "selection_method": "aligned_composite",
            }
        )
    return combined


def _annual_revenue_records(
    payload: Dict[str, Any],
    filed_on_or_before: Optional[date] = None,
) -> List[Dict[str, object]]:
    """Choose one defensible revenue basis and keep growth on that basis."""

    def direct_family(
        tag: str,
        *,
        selection_method: str = "direct",
    ) -> List[Dict[str, object]]:
        records = _annual_records(
            payload,
            (tag,),
            ("USD",),
            duration=True,
            filed_on_or_before=filed_on_or_before,
        )
        return [
            {
                **record,
                "selection_method": selection_method,
                "revenue_family": tag,
            }
            for record in records
        ]

    families: Dict[str, List[Dict[str, object]]] = {
        "contract_excluding": direct_family(
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ),
        "revenues": direct_family("Revenues"),
        "sales_net": direct_family("SalesRevenueNet"),
        "sales_goods": direct_family("SalesRevenueGoodsNet"),
        "contract_including": direct_family(
            "RevenueFromContractWithCustomerIncludingAssessedTax"
        ),
        "net_revenue": direct_family("RevenuesNetOfInterestExpense"),
        "regulated_revenue": direct_family(
            "RegulatedAndUnregulatedOperatingRevenue"
        ),
    }
    net_interest = _annual_records(
        payload,
        ("InterestIncomeExpenseNet", "InterestRevenueExpenseNet"),
        ("USD",),
        duration=True,
        filed_on_or_before=filed_on_or_before,
    )
    noninterest_income = _annual_records(
        payload,
        ("NoninterestIncome",),
        ("USD",),
        duration=True,
        filed_on_or_before=filed_on_or_before,
    )
    contract_revenue = families["contract_excluding"]
    operating_lease_income = _annual_records(
        payload,
        ("OperatingLeaseLeaseIncome",),
        ("USD",),
        duration=True,
        filed_on_or_before=filed_on_or_before,
    )
    families["lease_income"] = [
        {
            **record,
            "selection_method": "guarded_direct_fallback",
            "revenue_family": "lease_income",
        }
        for record in operating_lease_income
    ]
    families["bank_composite"] = [
        {**record, "revenue_family": "bank_composite"}
        for record in _sum_aligned_records(
            net_interest,
            noninterest_income,
            "InterestIncomeExpenseNet+NoninterestIncome",
        )
    ]
    families["lease_composite"] = [
        {**record, "revenue_family": "lease_composite"}
        for record in _sum_aligned_records(
            operating_lease_income,
            contract_revenue,
            "OperatingLeaseLeaseIncome+ContractRevenue",
        )
    ]

    records_by_family = {
        family: {str(record["end"]): record for record in records}
        for family, records in families.items()
    }
    all_ends = sorted(
        {
            end
            for records_by_end in records_by_family.values()
            for end in records_by_end
        }
    )
    if not all_ends:
        return []
    latest_end = all_ends[-1]

    def latest_record(family: str) -> Optional[Dict[str, object]]:
        record = records_by_family.get(family, {}).get(latest_end)
        if record is None or float(record["value"]) <= 0:
            return None
        return record

    def comparison_warning(ratio: float) -> Optional[str]:
        tolerance = 1e-12
        if ratio >= 1.20 - tolerance:
            return "broad_total_material_override"
        if ratio < 0.95 - tolerance:
            return "revenue_source_conflict"
        if abs(ratio - 1.0) > 0.05 + tolerance:
            return "revenue_source_review"
        return None

    baseline_order = (
        "contract_excluding",
        "revenues",
        "sales_net",
        "sales_goods",
    )
    baseline_family = next(
        (family for family in baseline_order if latest_record(family)), None
    )
    baseline = latest_record(baseline_family) if baseline_family else None
    broad_order = (
        "revenues",
        "regulated_revenue",
        "net_revenue",
        "bank_composite",
        "lease_composite",
    )
    broad_family = next(
        (
            family
            for family in broad_order
            if family != baseline_family and latest_record(family)
        ),
        None,
    )
    broad = latest_record(broad_family) if broad_family else None

    selected_family = baseline_family
    basis_warning = None
    if baseline is None:
        fallback_order = (
            "regulated_revenue",
            "net_revenue",
            "bank_composite",
            "contract_including",
            "lease_composite",
            "lease_income",
        )
        selected_family = next(
            (family for family in fallback_order if latest_record(family)), None
        )
        if selected_family == "regulated_revenue":
            contract_including = latest_record("contract_including")
            if contract_including is not None:
                ratio = float(latest_record("regulated_revenue")["value"]) / float(
                    contract_including["value"]
                )
                basis_warning = comparison_warning(ratio)
        elif selected_family == "lease_income":
            basis_warning = "operating_lease_income_only"
    elif baseline_family != "revenues" and broad is not None:
        ratio = float(broad["value"]) / float(baseline["value"])
        basis_warning = comparison_warning(ratio)
        if basis_warning == "broad_total_material_override":
            selected_family = broad_family

    if selected_family is None:
        return []
    selected = [dict(record) for record in families[selected_family]]
    selected.sort(key=lambda item: str(item["end"]))
    if selected and basis_warning:
        selected[-1]["revenue_basis_warning"] = basis_warning
    return selected


def _value(record: Optional[Dict[str, object]]) -> Optional[float]:
    return float(record["value"]) if record else None


def _tag(record: Optional[Dict[str, object]]) -> Optional[str]:
    return str(record["tag"]) if record else None


def extract_sec_fundamentals(
    payload: Dict[str, Any],
    as_of: Optional[date] = None,
) -> Dict[str, object]:
    """Extract comparable annual fields available by an optional filing cutoff."""

    revenue_records = _annual_revenue_records(
        payload,
        filed_on_or_before=as_of,
    )
    net_income_records = _annual_records(
        payload,
        (
            "NetIncomeLoss",
            "ProfitLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
        ),
        ("USD",),
        duration=True,
        filed_on_or_before=as_of,
    )
    equity_records = _annual_records(
        payload,
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        ("USD",),
        duration=False,
        filed_on_or_before=as_of,
    )
    liabilities_records = _annual_records(
        payload,
        ("Liabilities",),
        ("USD",),
        duration=False,
        filed_on_or_before=as_of,
    )
    assets_records = _annual_records(
        payload,
        ("Assets",),
        ("USD",),
        duration=False,
        filed_on_or_before=as_of,
    )
    operating_cash_flow_records = _annual_records(
        payload,
        ("NetCashProvidedByUsedInOperatingActivities",),
        ("USD",),
        duration=True,
        filed_on_or_before=as_of,
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
        filed_on_or_before=as_of,
    )
    eps_records = _annual_records(
        payload,
        ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
        ("USD/shares",),
        duration=True,
        filed_on_or_before=as_of,
    )
    shares = _latest_instant_record(
        payload,
        "dei",
        ("EntityCommonStockSharesOutstanding",),
        ("shares",),
        filed_on_or_before=as_of,
    ) or _latest_instant_record(
        payload,
        "us-gaap",
        ("CommonStockSharesOutstanding",),
        ("shares",),
        filed_on_or_before=as_of,
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
    revenue_growth_quality_warning = (
        "insufficient_same_basis_history"
        if revenue and previous_revenue is None
        else None
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
    roe_nonpositive_equity = bool(
        roe_equity and float(roe_equity["value"]) <= 0
    )
    if roe_nonpositive_equity:
        roe = None

    liabilities_source_tag = _tag(leverage_liabilities)
    liabilities_to_equity = _aligned_ratio(leverage_liabilities, leverage_equity)
    leverage_nonpositive_equity = bool(
        leverage_equity and float(leverage_equity["value"]) <= 0
    )
    if leverage_nonpositive_equity:
        liabilities_to_equity = None
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
                leverage_nonpositive_equity = False
            else:
                leverage_nonpositive_equity = True

    equity_warning = (
        "nonpositive_stockholders_equity"
        if roe_nonpositive_equity or leverage_nonpositive_equity
        else None
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
        "annual_revenue_period_end": revenue["end"] if revenue else None,
        "annual_net_income": _value(net_income),
        "annual_net_income_period_end": net_income["end"] if net_income else None,
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
        "revenue_growth_quality_warning": revenue_growth_quality_warning,
        "profit_margin": profit_margin,
        "profit_margin_raw": profit_margin,
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
        "revenue_selection_method": (
            revenue.get("selection_method") if revenue else None
        ),
        "revenue_basis_warning": (
            revenue.get("revenue_basis_warning") if revenue else None
        ),
        "net_income_source_tag": _tag(net_income),
        "equity_source_tag": _tag(equity),
        "liabilities_source_tag": liabilities_source_tag,
        "cash_flow_source_tag": _tag(operating_cash_flow),
        "capex_source_tag": _tag(capex_aligned),
        "shares_source_tag": _tag(shares),
    }
