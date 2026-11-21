"""Unit tests for output parsing, guardrails and cost estimation."""

from __future__ import annotations

import json

import pytest
from crewai import TaskOutput

from shopcrew.cost import estimate_cost
from shopcrew.datasource import LocalDataSource
from shopcrew.guardrails import (
    CLAIM_WARNING,
    campaign_guardrail,
    parse_output,
    pricing_guardrail,
    review_guardrail,
    seo_guardrail,
)
from shopcrew.models import CampaignPlan, PricingReport, ReviewInsights, SEOCopy
from tests.fixtures import campaign_dict, insights_dict, pricing_dict, seo_dict


def _output(payload: dict | str) -> TaskOutput:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return TaskOutput(description="d", raw=raw, agent="a")


@pytest.mark.parametrize(
    "wrapper",
    ["{}", "```json\n{}\n```", "Here is the result:\n{}\nHope this helps!"],
)
def test_parse_output_handles_fences_and_chatter(wrapper: str) -> None:
    raw = wrapper.replace("{}", json.dumps(pricing_dict()))
    assert parse_output(raw, PricingReport).position == "below_avg"


def test_guardrail_rejects_invalid_output_with_helpful_message(source: LocalDataSource) -> None:
    guard = seo_guardrail(source, "earbuds-01")
    ok, message = guard(_output({**seo_dict(), "long_description": "too short"}))
    assert not ok
    assert "SEOCopy" in message and "long_description" in message


def test_guardrail_trims_overlong_text_fields(source: LocalDataSource) -> None:
    notes: list[str] = []
    long_title = "PulseBeat Pro Wireless Earbuds - 40 Hour Battery Life and Crystal Clear Calls"
    guard = seo_guardrail(source, "earbuds-01", notes)
    ok, seo = guard(_output({**seo_dict(), "title": long_title}))
    assert ok and isinstance(seo, SEOCopy)
    assert len(seo.title) <= 70 and long_title.startswith(seo.title)
    assert not seo.title.endswith(" ")
    assert notes == ["SEOCopy: trimmed title to 70 characters"]


def test_parse_output_picks_final_object_when_model_emits_several() -> None:
    raw = (
        'Action: SEOCopy\nAction Input: {"title": "draft"}\n\n```json\n'
        + json.dumps(seo_dict())
        + "\n```"
    )
    assert parse_output(raw, SEOCopy).title == seo_dict()["title"]


def test_guardrail_accepts_valid_output(source: LocalDataSource) -> None:
    ok, value = seo_guardrail(source, "earbuds-01")(_output(seo_dict()))
    assert ok and isinstance(value, SEOCopy)


def test_campaign_claims_rejected_once_then_warned(source: LocalDataSource) -> None:
    notes: list[str] = []
    guard = campaign_guardrail(source, "earbuds-01", notes)
    bad = {**campaign_dict(), "positioning_statement": "The only earbuds you will ever need."}

    ok, message = guard(_output(bad))
    assert not ok
    assert "The only" in message and "Rewrite those sentences" in message
    assert notes == []

    ok, plan = guard(_output(bad))  # the retry still has the claim: keep it, but warn
    assert ok and isinstance(plan, CampaignPlan)
    assert len(notes) == 1 and notes[0].startswith(CLAIM_WARNING)


def test_campaign_without_claims_passes_first_time(source: LocalDataSource) -> None:
    notes: list[str] = []
    ok, _ = campaign_guardrail(source, "earbuds-01", notes)(_output(campaign_dict()))
    assert ok and notes == []


def test_pricing_guardrail_fixes_math(source: LocalDataSource) -> None:
    notes: list[str] = []
    wrong = {**pricing_dict(), "competitor_avg": 1, "position": "cheapest"}
    ok, report = pricing_guardrail(source, "earbuds-01", notes)(_output(wrong))
    assert ok and isinstance(report, PricingReport)
    assert report.competitor_avg == 39.39 and report.position == "below_avg"
    assert notes


def test_pricing_guardrail_rejects_absurd_recommendation(source: LocalDataSource) -> None:
    ok, message = pricing_guardrail(source, "earbuds-01", [])(
        _output({**pricing_dict(), "recommended_price": 99999})
    )
    assert not ok and "unrealistic" in message


def test_review_guardrail_fixes_stats(source: LocalDataSource) -> None:
    notes: list[str] = []
    ok, insights = review_guardrail(source, "earbuds-01", notes)(_output(insights_dict()))
    assert ok and isinstance(insights, ReviewInsights)
    assert insights.average_rating == pytest.approx(3.86, abs=0.01)
    assert notes


def test_cost_known_model() -> None:
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 100_000, "total_tokens": 1_100_000}
    cost = estimate_cost("anthropic/claude-sonnet-5-5", usage)
    assert cost.usd == pytest.approx(2.0 + 1.0)
    assert "estimated cost: $3.0000" in cost.describe()


def test_cost_prefers_longest_model_match() -> None:
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    assert estimate_cost("anthropic/claude-opus-5-5", usage).usd == pytest.approx(4.0)
    assert estimate_cost("anthropic/claude-opus-5", usage).usd == pytest.approx(5.0)


def test_ollama_llm_uses_native_api_with_big_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from shopcrew.llm import build_llm

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example-host:11434")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    llm = build_llm("ollama/qwen3.5:4b")
    assert llm.model.endswith("qwen3.5:4b") and "ollama" in llm.model
    assert getattr(llm, "base_url", None) == "http://example-host:11434"
    assert (getattr(llm, "additional_params", {}) or {}).get("num_ctx") == 8192 or (
        getattr(llm, "num_ctx", None) == 8192
    )
    assert estimate_cost("ollama/qwen3.5:4b", {"prompt_tokens": 10**6}).usd == 0.0


def test_cost_unknown_model_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert estimate_cost("openai/some-new-model", usage).usd is None
    monkeypatch.setenv("PRICE_INPUT_PER_MTOK", "1")
    monkeypatch.setenv("PRICE_OUTPUT_PER_MTOK", "2")
    assert estimate_cost("openai/some-new-model", usage).usd == pytest.approx(3.0)
