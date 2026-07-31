from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest

from src import ai_report
from src.research_report import DISCLAIMER


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("AI report test attempted network access")

    monkeypatch.setattr(socket.socket, "connect", fail_network)


def _report() -> dict[str, object]:
    return {
        "service": "get_research_report",
        "schema_version": "1.0.0",
        "accepted_run_id": "accepted_scores",
        "scoring_contract_version": "1.0.2",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "as_of_date": "2026-07-13",
        "ticker": "AAA",
        "mode": "value",
        "identity": {
            "ticker": "AAA",
            "company_name": "Alpha Corp",
            "sector": "Technology",
            "industry": "Software",
            "cik": "0000000001",
        },
        "research_posture": {
            "classification": "strong",
            "label": "Strong",
            "selected_mode_score": 82.5,
            "eligible_for_ranking": True,
            "basis_codes": ["eligible_for_ranking"],
            "meaning": (
                "Fit with the selected screening mode using accepted evidence; "
                "not a buy, sell, hold, or suitability recommendation."
            ),
        },
        "summary": (
            "AAA shows strong fit with the accepted Value screening evidence "
            "at a stored score of 82.50."
        ),
        "factor_scores": {
            "momentum": 91.0,
            "quality": 75.0,
            "valuation": 80.0,
            "risk": 45.0,
            "sector_strength": None,
        },
        "strengths": [
            {
                "code": "high_factor_score:momentum",
                "factor": "Momentum",
                "score": 91.0,
                "summary": "Momentum is a high-scoring accepted factor.",
            },
            {
                "code": "high_factor_score:valuation",
                "factor": "Valuation",
                "score": 80.0,
                "summary": "Valuation is a high-scoring accepted factor.",
            },
        ],
        "risks": [
            {
                "code": "missing_factor_score:sector_strength",
                "factor": "Sector Strength",
                "score": None,
                "summary": "The Sector Strength factor is unavailable.",
            }
        ],
        "quality": {
            "eligible_for_scoring": True,
            "missing_inputs": [],
            "warnings": [],
            "stale_fundamental_metrics": [],
            "base_exclusion_reasons": [],
        },
        "data_dates": {
            "as_of_date": "2026-07-13",
            "price_data_end": "2026-07-10",
            "fundamental_filed_date": None,
        },
        "next_research_questions": [
            "What drivers explain the current Momentum score?",
            "What changed since the included filing?",
        ],
        "terminology": {
            "risk_score": "A higher Risk score means lower measured risk.",
            "market_cap_proxy": (
                "A proxy, not authoritative market capitalization."
            ),
            "average_volume_20d": "20-day average share volume.",
        },
        "disclaimer": DISCLAIMER,
    }


class _FakeResponses:
    def __init__(self, output_parsed=None, error: Exception | None = None):
        self.output_parsed = output_parsed
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_parsed=self.output_parsed)


class _FakeClient:
    def __init__(self, responses: _FakeResponses):
        self.responses = responses


def test_structured_plan_schema_is_narrow_strict_and_fully_required() -> None:
    schema = ai_report.AIReportPlan.model_json_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["headline_style", "narrative_item_ids"]
    assert set(schema["properties"]) == {
        "headline_style",
        "narrative_item_ids",
    }
    assert schema["properties"]["headline_style"]["enum"] == [
        "company",
        "posture",
    ]
    assert schema["properties"]["narrative_item_ids"]["minItems"] == 1
    assert schema["properties"]["narrative_item_ids"]["maxItems"] == 5


def test_success_uses_responses_parse_and_only_selects_grounded_source_text(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    responses = _FakeResponses(
        ai_report.AIReportPlan(
            headline_style="company",
            narrative_item_ids=["risk:0", "summary", "strength:1"],
        )
    )
    client = _FakeClient(responses)
    source = _report()

    result = ai_report.render_ai_research_report(
        source,
        client=client,
        api_key="test-key-not-secret",
    )

    assert len(responses.calls) == 1
    request = responses.calls[0]
    assert request["model"] == "gpt-5.6-terra"
    assert request["text_format"] is ai_report.AIReportPlan
    assert request["store"] is False
    assert request["max_output_tokens"] == 250
    assert "Do not write prose" in request["instructions"]
    assert "test-key-not-secret" not in repr(request)

    assert result["renderer"] == {
        "status": "openai",
        "requested_provider": "openai",
        "model": "gpt-5.6-terra",
        "fallback_reason": None,
        "grounding": "source_text_selection_only",
    }
    assert result["headline"] == "AAA — Alpha Corp"
    assert [item["id"] for item in result["narrative_items"]] == [
        "risk:0",
        "summary",
        "strength:1",
    ]
    assert result["analysis"] == " ".join(
        [
            source["risks"][0]["summary"],
            source["summary"],
            source["strengths"][1]["summary"],
        ]
    )
    assert result["research_posture"] == source["research_posture"]
    assert result["strengths"] == source["strengths"]
    assert result["risks"] == source["risks"]
    assert result["next_research_questions"] == source[
        "next_research_questions"
    ]
    assert result["disclaimer"] == source["disclaimer"]
    json.dumps(result, allow_nan=False)


def test_missing_key_never_calls_client_and_returns_repeatable_fallback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    responses = _FakeResponses(
        ai_report.AIReportPlan(
            headline_style="company",
            narrative_item_ids=["summary"],
        )
    )
    client = _FakeClient(responses)

    first = ai_report.render_ai_research_report(_report(), client=client)
    second = ai_report.render_ai_research_report(_report(), client=client)

    assert responses.calls == []
    assert first == second
    assert first["renderer"]["status"] == "deterministic_fallback"
    assert first["renderer"]["fallback_reason"] == "missing_api_key"
    assert first["narrative_items"][0]["id"] == "summary"


def test_openai_model_environment_override_is_forwarded(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "custom-model")
    responses = _FakeResponses(
        {"headline_style": "posture", "narrative_item_ids": ["summary"]}
    )

    result = ai_report.render_ai_research_report(
        _report(),
        client=_FakeClient(responses),
        api_key="test-key",
    )

    assert responses.calls[0]["model"] == "custom-model"
    assert result["renderer"]["model"] == "custom-model"
    assert result["headline"] == "AAA — Strong Value research fit"


def test_api_error_returns_safe_fallback_without_traceback_or_secret() -> None:
    secret = "sk-super-secret-value"
    responses = _FakeResponses(error=RuntimeError(f"provider failed {secret}"))

    result = ai_report.render_ai_research_report(
        _report(),
        client=_FakeClient(responses),
        api_key=secret,
    )
    serialized = json.dumps(result)

    assert result["renderer"]["fallback_reason"] == "openai_request_failed"
    assert secret not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized
    assert result["strengths"] == _report()["strengths"]


def test_sdk_creation_error_returns_safe_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        ai_report,
        "_new_openai_client",
        lambda api_key: (_ for _ in ()).throw(ImportError("missing SDK secret")),
    )

    result = ai_report.render_ai_research_report(
        _report(),
        api_key="test-key",
    )

    assert result["renderer"]["status"] == "deterministic_fallback"
    assert result["renderer"]["fallback_reason"] == "openai_sdk_unavailable"
    assert "missing SDK secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "invalid_output",
    [
        None,
        {"headline_style": "company"},
        {
            "headline_style": "company",
            "narrative_item_ids": ["summary"],
            "analysis": "Buy now at a target price of 999.",
        },
        {
            "headline_style": "company",
            "narrative_item_ids": ["unsupported_fact"],
        },
        {
            "headline_style": "company",
            "narrative_item_ids": ["summary", "summary"],
        },
    ],
)
def test_invalid_structured_output_cannot_enter_final_report(invalid_output) -> None:
    responses = _FakeResponses(invalid_output)

    result = ai_report.render_ai_research_report(
        _report(),
        client=_FakeClient(responses),
        api_key="test-key",
    )
    serialized = json.dumps(result)

    assert result["renderer"]["fallback_reason"] == "invalid_structured_output"
    assert "Buy now" not in serialized
    assert "target price of 999" not in serialized
    assert "unsupported_fact" not in serialized


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report.update(service="other"), "service"),
        (
            lambda report: report["research_posture"].update(
                classification="buy"
            ),
            "classification",
        ),
        (lambda report: report.pop("factor_scores"), "factor_scores"),
        (lambda report: report.update(disclaimer=""), "disclaimer"),
        (lambda report: report.update(as_of_date=float("nan")), "as_of_date"),
    ],
)
def test_invalid_source_schema_fails_before_client_call(
    mutation,
    message,
) -> None:
    source = _report()
    mutation(source)
    responses = _FakeResponses(
        {"headline_style": "company", "narrative_item_ids": ["summary"]}
    )

    with pytest.raises(ai_report.AIReportValidationError, match=message):
        ai_report.render_ai_research_report(
            source,
            client=_FakeClient(responses),
            api_key="test-key",
        )
    assert responses.calls == []
