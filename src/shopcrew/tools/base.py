"""Shared plumbing for ShopCrew's CrewAI tools."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from shopcrew.datasource import DataSource, default_source
from shopcrew.exceptions import ShopCrewError


class ProductIdInput(BaseModel):
    """Input schema shared by every tool: just the product ID."""

    product_id: str = Field(..., description="The product ID, e.g. 'earbuds-01'")


class DataSourceMixin(BaseModel):
    """Gives a tool an injectable data source (defaults to the process-wide one)."""

    source: Any = Field(default=None, exclude=True)

    def _source(self) -> DataSource:
        return self.source or default_source()


def to_json(payload: dict[str, Any]) -> str:
    """Serialise a tool result for the LLM."""
    return json.dumps(payload, indent=2, ensure_ascii=False)


def error_json(err: ShopCrewError) -> str:
    """Return a domain error to the agent as JSON instead of crashing the crew."""
    return to_json({"error": str(err)})
