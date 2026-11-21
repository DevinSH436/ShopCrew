"""Pydantic schemas for the domain data and for every agent's structured output.

Each task in the crew sets ``output_pydantic`` to one of the output models below, so
CrewAI asks the LLM for JSON matching the schema and validates it. A task guardrail
(see ``shopcrew.guardrails``) re-validates and gives the agent one retry on failure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------------------
# Domain data (what the tools return)
# --------------------------------------------------------------------------------------


class Product(BaseModel):
    """A product in our catalog."""

    id: str
    name: str
    category: str
    our_price: float = Field(gt=0, description="Our selling price in USD")
    current_description: str
    features: list[str]


class Review(BaseModel):
    """A single customer review."""

    product_id: str
    rating: int = Field(ge=1, le=5)
    text: str
    date: str


class CompetitorPrice(BaseModel):
    """One competitor's listing for a product."""

    product_id: str
    competitor: str
    price: float = Field(gt=0)
    in_stock: bool
    last_checked: str


PricePosition = Literal["cheapest", "below_avg", "above_avg", "most_expensive"]


class ReviewStats(BaseModel):
    """Deterministic review statistics computed in code (never by the LLM)."""

    review_count: int
    average_rating: float
    rating_histogram: dict[int, int]
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class PriceStats(BaseModel):
    """Deterministic competitor price statistics computed in code (never by the LLM)."""

    our_price: float
    competitor_min: float
    competitor_max: float
    competitor_avg: float
    position: PricePosition
    diff_vs_avg_pct: float = Field(description="(our - avg) / avg * 100, rounded")
    in_stock_competitors: int


# --------------------------------------------------------------------------------------
# Agent outputs
# --------------------------------------------------------------------------------------


class SentimentBreakdown(BaseModel):
    """Share of reviews by sentiment, as percentages that sum to ~100."""

    positive: float = Field(ge=0, le=100)
    neutral: float = Field(ge=0, le=100)
    negative: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _sums_to_100(self) -> SentimentBreakdown:
        total = self.positive + self.neutral + self.negative
        if not 98 <= total <= 102:
            raise ValueError(f"sentiment percentages must sum to 100, got {total:.1f}")
        return self


class ReviewInsights(BaseModel):
    """Output of the Review Analyst."""

    average_rating: float = Field(ge=1, le=5)
    sentiment_breakdown: SentimentBreakdown
    top_praises: list[str] = Field(min_length=1, max_length=6)
    top_complaints: list[str] = Field(min_length=1, max_length=6)
    customer_phrases: list[str] = Field(
        min_length=3, description="Exact words/phrases customers use, quoted from reviews"
    )
    summary: str = Field(min_length=20)


class PricingReport(BaseModel):
    """Output of the Price Tracker."""

    our_price: float = Field(gt=0)
    competitor_min: float = Field(gt=0)
    competitor_max: float = Field(gt=0)
    competitor_avg: float = Field(gt=0)
    position: PricePosition
    recommended_price: float = Field(gt=0)
    reasoning: str = Field(min_length=20)


class SEOCopy(BaseModel):
    """Output of the SEO Writer."""

    title: str = Field(max_length=70)
    meta_description: str = Field(max_length=160)
    bullet_points: list[str] = Field(min_length=5, max_length=5)
    long_description: str
    keywords: list[str] = Field(min_length=3)

    @field_validator("long_description")
    @classmethod
    def _word_count(cls, value: str) -> str:
        words = len(value.split())
        if not 150 <= words <= 250:
            raise ValueError(f"long_description must be 150-250 words, got {words}")
        return value


class GoogleAd(BaseModel):
    """A Google responsive search ad (one headline + one description)."""

    headline: str = Field(max_length=30)
    description: str = Field(max_length=90)


class Email(BaseModel):
    """A marketing email."""

    subject: str = Field(max_length=80)
    body: str


class ScheduleItem(BaseModel):
    """One day of the launch schedule."""

    day: int = Field(ge=1, le=7)
    channel: str
    action: str


class CampaignPlan(BaseModel):
    """Output of the Marketer."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    target_audience: str
    positioning_statement: str
    key_message: str
    offer: str
    instagram_caption: str
    google_ad: GoogleAd
    email: Email
    seven_day_schedule: list[ScheduleItem] = Field(
        alias="7_day_schedule", min_length=7, max_length=7
    )
    how_we_address_complaints: str

    @field_validator("seven_day_schedule")
    @classmethod
    def _days_one_to_seven(cls, items: list[ScheduleItem]) -> list[ScheduleItem]:
        if sorted(item.day for item in items) != list(range(1, 8)):
            raise ValueError("7_day_schedule must contain exactly one entry for each day 1-7")
        return sorted(items, key=lambda item: item.day)
