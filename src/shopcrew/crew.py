"""The ShopCrew crew: four specialist agents, optionally coordinated by a manager.

Uses CrewAI's YAML config pattern (``config/agents.yaml`` and ``config/tasks.yaml``)
with the ``@CrewBase`` decorator. Outputs flow forward through each task's ``context``:
Reviews -> Prices -> SEO (uses reviews) -> Marketing (uses all three).
"""

from __future__ import annotations

from typing import Literal

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.llms.base_llm import BaseLLM
from crewai.project import CrewBase, agent, crew, task

from shopcrew.datasource import DataSource
from shopcrew.guardrails import (
    campaign_guardrail,
    pricing_guardrail,
    review_guardrail,
    seo_guardrail,
)
from shopcrew.models import CampaignPlan, PricingReport, ReviewInsights, SEOCopy
from shopcrew.tools import CompetitorPriceTool, ProductInfoTool, ReviewLoaderTool

ProcessName = Literal["sequential", "hierarchical"]
GUARDRAIL_RETRIES = 1  # spec: retry once on invalid output


@CrewBase
class ShopCrew:
    """Builds the crew for one product."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(
        self,
        llm: BaseLLM,
        source: DataSource,
        product_id: str,
        process: ProcessName = "sequential",
        verbose: bool = False,
    ) -> None:
        """Configure the crew.

        Args:
            llm: LLM shared by every agent (and the manager in hierarchical mode).
            source: Data source the tools read from.
            product_id: Product the guardrails compute exact stats for.
            process: ``sequential`` or ``hierarchical``.
            verbose: Print CrewAI's step-by-step agent output.
        """
        self.llm = llm
        self.source = source
        self.product_id = product_id
        self.process = process
        self.verbose = verbose
        self.notes: list[str] = []  # corrections made by guardrails, shown in run_log.txt

    # ---- agents -------------------------------------------------------------------

    def _agent(self, key: str, tools: list) -> Agent:
        return Agent(
            config=self.agents_config[key],  # type: ignore[index]
            llm=self.llm,
            tools=tools,
            allow_delegation=False,
            max_iter=8,
            verbose=self.verbose,
        )

    @agent
    def review_analyst(self) -> Agent:
        """Reads reviews and extracts insights."""
        return self._agent("review_analyst", [ReviewLoaderTool(source=self.source)])

    @agent
    def price_tracker(self) -> Agent:
        """Compares our price with competitors."""
        return self._agent("price_tracker", [CompetitorPriceTool(source=self.source)])

    @agent
    def seo_writer(self) -> Agent:
        """Writes SEO copy from the review insights."""
        return self._agent("seo_writer", [ProductInfoTool(source=self.source)])

    @agent
    def marketer(self) -> Agent:
        """Plans the launch campaign from all three earlier outputs."""
        return self._agent("marketer", [ProductInfoTool(source=self.source)])

    def store_manager(self) -> Agent:
        """Manager for hierarchical mode. Not decorated, so it is not in ``self.agents``."""
        return Agent(
            config=self.agents_config["store_manager"],  # type: ignore[index]
            llm=self.llm,
            allow_delegation=True,
            max_iter=10,
            verbose=self.verbose,
        )

    # ---- tasks --------------------------------------------------------------------

    @task
    def review_task(self) -> Task:
        """Review analysis -> ReviewInsights."""
        return Task(
            config=self.tasks_config["review_task"],  # type: ignore[index]
            output_pydantic=ReviewInsights,
            guardrail=review_guardrail(self.source, self.product_id, self.notes),
            guardrail_max_retries=GUARDRAIL_RETRIES,
        )

    @task
    def pricing_task(self) -> Task:
        """Pricing analysis -> PricingReport."""
        return Task(
            config=self.tasks_config["pricing_task"],  # type: ignore[index]
            output_pydantic=PricingReport,
            guardrail=pricing_guardrail(self.source, self.product_id, self.notes),
            guardrail_max_retries=GUARDRAIL_RETRIES,
        )

    @task
    def seo_task(self) -> Task:
        """SEO copywriting (context: reviews) -> SEOCopy."""
        return Task(
            config=self.tasks_config["seo_task"],  # type: ignore[index]
            output_pydantic=SEOCopy,
            guardrail=seo_guardrail(self.source, self.product_id, self.notes),
            guardrail_max_retries=GUARDRAIL_RETRIES,
        )

    @task
    def marketing_task(self) -> Task:
        """Launch campaign (context: reviews, pricing, SEO) -> CampaignPlan."""
        return Task(
            config=self.tasks_config["marketing_task"],  # type: ignore[index]
            output_pydantic=CampaignPlan,
            guardrail=campaign_guardrail(self.source, self.product_id, self.notes),
            guardrail_max_retries=GUARDRAIL_RETRIES,
        )

    # ---- crew ---------------------------------------------------------------------

    @crew
    def crew(self) -> Crew:
        """Assemble the crew in sequential or hierarchical mode."""
        if self.process == "hierarchical":
            return Crew(
                agents=self.agents,
                tasks=self.tasks,
                process=Process.hierarchical,
                manager_agent=self.store_manager(),
                verbose=self.verbose,
            )
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=self.verbose,
        )
