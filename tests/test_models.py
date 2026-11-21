"""Tests for the Pydantic output schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shopcrew.models import CampaignPlan, PricingReport, ReviewInsights, SEOCopy
from tests.fixtures import campaign_dict, insights_dict, pricing_dict, seo_dict


def test_valid_outputs_parse() -> None:
    ReviewInsights(**insights_dict())
    PricingReport(**pricing_dict())
    SEOCopy(**seo_dict())
    CampaignPlan(**campaign_dict())


def test_sentiment_must_sum_to_100() -> None:
    data = insights_dict()
    data["sentiment_breakdown"] = {"positive": 50, "neutral": 10, "negative": 10}
    with pytest.raises(ValidationError, match="sum to 100"):
        ReviewInsights(**data)


def test_invalid_price_position_rejected() -> None:
    with pytest.raises(ValidationError):
        PricingReport(**{**pricing_dict(), "position": "cheap-ish"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "x" * 71),
        ("meta_description", "x" * 161),
        ("bullet_points", ["a", "b", "c", "d"]),
        ("long_description", "too short"),
        ("long_description", "word " * 260),
    ],
)
def test_seo_limits(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SEOCopy(**{**seo_dict(), field: value})


def test_campaign_schedule_alias_and_ordering() -> None:
    data = campaign_dict()
    data["7_day_schedule"] = list(reversed(data["7_day_schedule"]))
    plan = CampaignPlan(**data)
    assert [item.day for item in plan.seven_day_schedule] == list(range(1, 8))
    assert "7_day_schedule" in plan.model_dump(by_alias=True)


def test_campaign_schedule_needs_each_day_once() -> None:
    data = campaign_dict()
    data["7_day_schedule"][6]["day"] = 1
    with pytest.raises(ValidationError, match="each day"):
        CampaignPlan(**data)


def test_google_ad_headline_limit() -> None:
    data = campaign_dict()
    data["google_ad"]["headline"] = "x" * 31
    with pytest.raises(ValidationError):
        CampaignPlan(**data)
