"""End-to-end smoke tests: the real crew, real tools and real guardrails, mocked LLM.

No API key is needed. ``DemoLLM`` speaks CrewAI's ReAct protocol, so these tests cover
agent wiring, YAML config, context passing, tool calls, guardrails, both processes,
output files and usage tracking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shopcrew.crew import ShopCrew
from shopcrew.datasource import LocalDataSource
from shopcrew.demo import DemoLLM
from shopcrew.exceptions import ConfigError, NoReviewsError, ProductNotFoundError
from shopcrew.llm import build_llm
from shopcrew.main import main
from shopcrew.runner import STAGES, RunEvent, run_crew

EXPECTED_FILES = {
    "review_insights.json",
    "pricing_report.json",
    "seo_copy.md",
    "campaign_plan.md",
    "run_log.txt",
    "run_summary.json",
}


@pytest.mark.parametrize("process", ["sequential", "hierarchical"])
def test_full_crew_runs_with_mock_llm(
    process: str, source: LocalDataSource, tmp_path: Path
) -> None:
    events: list[RunEvent] = []
    result = run_crew(
        "earbuds-01",
        process=process,  # type: ignore[arg-type]
        model="mock",
        source=source,
        outputs_dir=tmp_path,
        on_event=events.append,
        verbose=False,
    )

    # every agent ran, in order, and used its tool
    completed = [e.stage for e in events if e.kind == "completed"]
    assert completed == [s.key for s in STAGES]
    assert {e.stage for e in events if e.kind == "tool"} == {s.key for s in STAGES}

    # all files written
    assert {p.name for p in result.files()} == EXPECTED_FILES

    # numbers come from code, not the LLM
    assert result.pricing.position == "below_avg"
    assert result.pricing.competitor_avg == 39.39
    assert result.insights.average_rating == pytest.approx(3.86, abs=0.01)

    # collaboration: the campaign uses review insights and the pricing position
    top_phrase = result.insights.customer_phrases[0]
    assert top_phrase in result.campaign.instagram_caption
    assert "below" in result.campaign.offer.lower()
    assert result.insights.top_praises[0].rstrip(".") in result.campaign.key_message

    # usage is tracked once per LLM call (4 workers x 2 calls, +8 manager calls)
    expected_calls = 8 if process == "sequential" else 16
    assert result.cost.requests == expected_calls
    assert result.cost.usd == 0.0

    saved = json.loads((result.out_dir / "pricing_report.json").read_text(encoding="utf-8"))
    assert saved["position"] == "below_avg"
    campaign = json.loads((result.out_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert len(campaign["campaign_plan"]["7_day_schedule"]) == 7


def test_crew_structure(source: LocalDataSource) -> None:
    builder = ShopCrew(llm=DemoLLM(source), source=source, product_id="earbuds-01")
    crew = builder.crew()
    assert [a.role for a in crew.agents] == [s.agent for s in STAGES]
    seo, marketing = crew.tasks[2], crew.tasks[3]
    assert [t.agent.role for t in seo.context] == ["Review Analyst"]
    assert [t.agent.role for t in marketing.context] == [
        "Review Analyst",
        "Price Tracker",
        "SEO Writer",
    ]
    assert all(t.guardrail_max_retries == 1 for t in crew.tasks)


class FlakyLLM(DemoLLM):
    """Returns broken JSON for the Price Tracker's first final answer, then behaves."""

    def __init__(self, source: LocalDataSource) -> None:
        super().__init__(source)
        self.broken_once = False

    def _final_answer(self, role: str | None, text: str) -> str:
        if role == "Price Tracker" and not self.broken_once:
            self.broken_once = True
            return 'Thought: done\nFinal Answer: {"our_price": "lots", "position": "cheap"}'
        return super()._final_answer(role, text)


def test_invalid_output_is_retried_once(source: LocalDataSource, monkeypatch: Any) -> None:
    flaky = FlakyLLM(source)
    monkeypatch.setattr("shopcrew.runner.build_llm", lambda model=None: flaky)
    result = run_crew("earbuds-01", model="mock", source=source, verbose=False)
    assert flaky.broken_once
    assert result.pricing.position == "below_avg"


def test_wrong_numbers_are_corrected_by_guardrail(
    source: LocalDataSource, monkeypatch: Any, tmp_path: Path
) -> None:
    class WrongMathLLM(DemoLLM):
        def _final_answer(self, role: str | None, text: str) -> str:
            reply = super()._final_answer(role, text)
            if role == "Price Tracker":
                reply = reply.replace('"competitor_avg": 39.39', '"competitor_avg": 1234.0')
            return reply

    monkeypatch.setattr("shopcrew.runner.build_llm", lambda model=None: WrongMathLLM(source))
    result = run_crew(
        "earbuds-01", model="mock", source=source, outputs_dir=tmp_path, verbose=False
    )
    assert result.pricing.competitor_avg == 39.39
    assert any("Price Tracker numbers corrected" in n for n in result.notes)
    assert "Guardrail notes" in (result.out_dir / "run_log.txt").read_text(encoding="utf-8")


def test_unknown_product_fails_before_llm(source: LocalDataSource) -> None:
    with pytest.raises(ProductNotFoundError):
        run_crew("does-not-exist", model="mock", source=source)


def test_empty_reviews_fail_clearly(tiny_data_dir: Path) -> None:
    with pytest.raises(NoReviewsError):
        run_crew("p2", model="mock", source=LocalDataSource(tiny_data_dir))


def test_missing_api_key_is_a_clear_error() -> None:
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        build_llm("anthropic/claude-sonnet-5-5")


def test_cli_list_and_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list"]) == 0
    assert "earbuds-01" in capsys.readouterr().out
    assert main(["--product", "nope", "--model", "mock"]) == 2
    assert "not found" in capsys.readouterr().err
    assert main(["--product", "earbuds-01", "--source", "shopify"]) == 2
