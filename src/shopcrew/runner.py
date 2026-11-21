"""Run the crew for a product, stream progress events, and save every output.

Both the CLI (``shopcrew.main``) and the dashboard (``app/dashboard.py``) call
``run_crew``. Progress is reported through an ``on_event`` callback fed by CrewAI's
event bus, so callers can show which agent is running, what tools it used and when
it finishes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from crewai.events import crewai_event_bus
from crewai.events.types.task_events import TaskCompletedEvent, TaskFailedEvent, TaskStartedEvent
from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent
from pydantic import BaseModel

from shopcrew.cost import CostEstimate, estimate_cost
from shopcrew.crew import ProcessName, ShopCrew
from shopcrew.datasource import PROJECT_ROOT, DataSource, get_data_source
from shopcrew.llm import build_llm, configured_model
from shopcrew.models import CampaignPlan, PricingReport, Product, ReviewInsights, SEOCopy
from shopcrew.render import campaign_markdown, seo_markdown

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR") or PROJECT_ROOT / "outputs")


@dataclass(frozen=True)
class Stage:
    """One agent/task in the pipeline, in execution order."""

    key: str
    agent: str
    label: str
    icon: str
    filename: str
    model: type[BaseModel]


STAGES: tuple[Stage, ...] = (
    Stage("review_task", "Review Analyst", "Reviews", "⭐", "review_insights.json", ReviewInsights),
    Stage("pricing_task", "Price Tracker", "Prices", "$", "pricing_report.json", PricingReport),
    Stage("seo_task", "SEO Writer", "SEO", "¶", "seo_copy.md", SEOCopy),
    Stage("marketing_task", "Marketer", "Marketing", "↗", "campaign_plan.md", CampaignPlan),
)

EventKind = Literal["run_started", "started", "tool", "completed", "failed", "run_finished"]


@dataclass
class RunEvent:
    """A progress update emitted while the crew runs."""

    kind: EventKind
    stage: str | None
    message: str
    timestamp: float = field(default_factory=time.time)

    def line(self) -> str:
        """Format as a log line."""
        stamp = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")
        who = next((s.agent for s in STAGES if s.key == self.stage), "Crew")
        return f"[{stamp}] {who:<14} {self.kind:<12} {self.message}"


@dataclass
class RunResult:
    """Everything a run produced."""

    product: Product
    process: ProcessName
    model: str
    out_dir: Path
    insights: ReviewInsights
    pricing: PricingReport
    seo: SEOCopy
    campaign: CampaignPlan
    cost: CostEstimate
    duration_s: float
    notes: list[str]

    def files(self) -> list[Path]:
        """All files written for this run."""
        return sorted(p for p in self.out_dir.iterdir() if p.is_file())


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class _EventBridge:
    """Translates CrewAI event-bus events for *this* crew's tasks into ``RunEvent``s."""

    def __init__(self, tasks: list[Any], emit: Callable[[RunEvent], None]) -> None:
        self._stage_by_task_id = {str(t.id): s.key for t, s in zip(tasks, STAGES, strict=True)}
        self._stage_by_role = {s.agent: s.key for s in STAGES}
        self._emit = emit
        self._lock = threading.Lock()
        self._handlers: list[tuple[type, Callable]] = [
            (TaskStartedEvent, self._on_started),
            (TaskCompletedEvent, self._on_completed),
            (TaskFailedEvent, self._on_failed),
            (ToolUsageFinishedEvent, self._on_tool),
        ]

    def __enter__(self) -> _EventBridge:
        for event_type, handler in self._handlers:
            crewai_event_bus.register_handler(event_type, handler)
        return self

    def __exit__(self, *exc: object) -> None:
        for event_type, handler in self._handlers:
            crewai_event_bus.off(event_type, handler)

    def _stage_of(self, event: Any) -> str | None:
        task = getattr(event, "task", None) or getattr(event, "from_task", None)
        task_id = str(getattr(task, "id", "") or getattr(event, "task_id", "") or "")
        return self._stage_by_task_id.get(task_id)

    def _send(self, kind: EventKind, stage: str | None, message: str) -> None:
        with self._lock:
            self._emit(RunEvent(kind, stage, message))

    def _on_started(self, _source: Any, event: TaskStartedEvent) -> None:
        if stage := self._stage_of(event):
            self._send("started", stage, "task started")

    def _on_completed(self, _source: Any, event: TaskCompletedEvent) -> None:
        if stage := self._stage_of(event):
            self._send("completed", stage, _short(event.output.raw))

    def _on_failed(self, _source: Any, event: TaskFailedEvent) -> None:
        if stage := self._stage_of(event):
            self._send("failed", stage, _short(event.error))

    def _on_tool(self, _source: Any, event: ToolUsageFinishedEvent) -> None:
        stage = self._stage_of(event) or self._stage_by_role.get(event.agent_role or "")
        if stage is None:
            return  # not one of this crew's tasks
        who = f"{event.agent_role} " if event.agent_role else ""
        self._send("tool", stage, f"{who}used {event.tool_name}({_short(event.tool_args, 80)})")


def run_usage(crew: Any) -> dict[str, int]:
    """Total token usage for a crew, counting each LLM object once.

    CrewAI's ``Crew.token_usage`` adds every agent's LLM summary, so when agents share
    one LLM instance (as ours do) usage is multiplied by the number of agents.
    """
    llms = {id(a.llm): a.llm for a in [*crew.agents, crew.manager_agent] if a and a.llm}
    totals: dict[str, int] = {}
    for llm in llms.values():
        for key, value in llm.get_token_usage_summary().model_dump().items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals


def _validate_inputs(source: DataSource, product_id: str) -> Product:
    """Fail fast with clear errors before spending any tokens."""
    product = source.get_product(product_id)
    source.get_reviews(product_id)
    source.get_competitor_prices(product_id)
    return product


def _output_of(task: Any, stage: Stage) -> BaseModel:
    output = task.output
    if output is None or not isinstance(output.pydantic, stage.model):
        raise RuntimeError(f"{stage.agent} did not produce a valid {stage.model.__name__}")
    return output.pydantic


def save_outputs(result: RunResult, log_lines: list[str]) -> None:
    """Write the four output files, ``run_log.txt`` and ``run_summary.json``."""
    out = result.out_dir
    out.mkdir(parents=True, exist_ok=True)

    def dump(model: BaseModel) -> str:
        return json.dumps(
            model.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False
        )

    (out / "review_insights.json").write_text(dump(result.insights), encoding="utf-8")
    (out / "pricing_report.json").write_text(dump(result.pricing), encoding="utf-8")
    (out / "seo_copy.md").write_text(seo_markdown(result.product, result.seo), encoding="utf-8")
    (out / "campaign_plan.md").write_text(
        campaign_markdown(result.product, result.campaign, result.pricing), encoding="utf-8"
    )
    header = [
        f"ShopCrew run for {result.product.id} ({result.product.name})",
        f"Process: {result.process} | Model: {result.model}",
        f"Duration: {result.duration_s:.1f}s",
        result.cost.describe(),
        "",
    ]
    notes = ["", "Guardrail notes:", *(f"- {n}" for n in result.notes)] if result.notes else []
    (out / "run_log.txt").write_text("\n".join(header + log_lines + notes) + "\n", encoding="utf-8")
    summary = {
        "product": result.product.model_dump(),
        "process": result.process,
        "model": result.model,
        "duration_s": round(result.duration_s, 2),
        "cost": result.cost.to_dict(),
        "notes": result.notes,
        "review_insights": result.insights.model_dump(mode="json"),
        "pricing_report": result.pricing.model_dump(mode="json"),
        "seo_copy": result.seo.model_dump(mode="json"),
        "campaign_plan": result.campaign.model_dump(mode="json", by_alias=True),
    }
    (out / "run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_crew(
    product_id: str,
    process: ProcessName = "sequential",
    model: str | None = None,
    source: DataSource | None = None,
    outputs_dir: Path | None = None,
    on_event: Callable[[RunEvent], None] | None = None,
    verbose: bool | None = None,
) -> RunResult:
    """Run the full crew for ``product_id`` and save its outputs.

    Args:
        product_id: Product to analyse, e.g. ``earbuds-01``.
        process: ``sequential`` or ``hierarchical`` (manager agent delegates).
        model: Model id override; defaults to the ``MODEL`` env var.
        source: Data source; defaults to ``DATA_SOURCE`` (local files).
        outputs_dir: Parent folder for run folders; defaults to ``outputs/``.
        on_event: Called with a ``RunEvent`` for every progress update.
        verbose: Print CrewAI's agent trace; defaults to the ``VERBOSE`` env var.

    Raises:
        ProductNotFoundError, NoReviewsError, NoCompetitorPricesError, ConfigError.
    """
    source = source or get_data_source()
    product = _validate_inputs(source, product_id)
    model = model or configured_model()
    llm = build_llm(model)
    if getattr(llm, "_source", "absent") is None:
        llm._source = source  # demo LLM: answer from the same data the tools read
    if verbose is None:
        verbose = os.getenv("VERBOSE", "false").strip().lower() in {"1", "true", "yes"}

    log_lines: list[str] = []

    def emit(event: RunEvent) -> None:
        log_lines.append(event.line())
        if on_event is not None:
            on_event(event)

    builder = ShopCrew(
        llm=llm, source=source, product_id=product_id, process=process, verbose=verbose
    )
    crew = builder.crew()
    started = time.time()
    emit(RunEvent("run_started", None, f"{product.name} | process={process} | model={model}"))
    with _EventBridge(crew.tasks, emit):
        crew.kickoff(inputs={"product_id": product.id, "product_name": product.name})
    duration = time.time() - started

    cost = estimate_cost(model, run_usage(crew))
    emit(RunEvent("run_finished", None, cost.describe()))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result = RunResult(
        product=product,
        process=process,
        model=model,
        out_dir=(outputs_dir or OUTPUTS_DIR) / f"{product.id}_{stamp}",
        insights=_output_of(crew.tasks[0], STAGES[0]),  # type: ignore[arg-type]
        pricing=_output_of(crew.tasks[1], STAGES[1]),  # type: ignore[arg-type]
        seo=_output_of(crew.tasks[2], STAGES[2]),  # type: ignore[arg-type]
        campaign=_output_of(crew.tasks[3], STAGES[3]),  # type: ignore[arg-type]
        cost=cost,
        duration_s=duration,
        notes=list(builder.notes),
    )
    save_outputs(result, log_lines)
    logger.info("Saved run to %s", result.out_dir)
    return result
