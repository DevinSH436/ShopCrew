"""Tests for the data source, deterministic stats and the three CrewAI tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shopcrew.datasource import LocalDataSource, get_data_source
from shopcrew.exceptions import (
    ConfigError,
    NoCompetitorPricesError,
    NoReviewsError,
    ProductNotFoundError,
)
from shopcrew.models import CompetitorPrice
from shopcrew.stats import classify_position, compute_price_stats
from shopcrew.tools import CompetitorPriceTool, ProductInfoTool, ReviewLoaderTool

# ---- sample data sanity ---------------------------------------------------------------


def test_sample_data_meets_spec(source: LocalDataSource) -> None:
    products = source.list_products()
    assert 3 <= len(products) <= 5
    for product in products:
        assert len(source.get_reviews(product.id)) >= 30
        assert len(source.get_competitor_prices(product.id)) >= 4
    ratings = {r.rating for r in source.get_reviews("earbuds-01")}
    assert ratings >= {1, 3, 5}, "reviews should have mixed sentiment"


# ---- data source errors ---------------------------------------------------------------


def test_unknown_product_lists_available(tiny_data_dir: Path) -> None:
    src = LocalDataSource(tiny_data_dir)
    with pytest.raises(ProductNotFoundError) as exc:
        src.get_product("nope")
    assert "p1" in str(exc.value) and "nope" in str(exc.value)


def test_empty_reviews_and_prices_raise(tiny_data_dir: Path) -> None:
    src = LocalDataSource(tiny_data_dir)
    with pytest.raises(NoReviewsError):
        src.get_reviews("p2")
    with pytest.raises(NoCompetitorPricesError):
        src.get_competitor_prices("p2")


def test_unimplemented_sources_raise_clear_error() -> None:
    with pytest.raises(ConfigError, match="not implemented"):
        get_data_source("shopify")
    with pytest.raises(ConfigError, match="Unknown data source"):
        get_data_source("ftp")


# ---- stats --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("our", "expected"),
    [
        (90, "cheapest"),
        (100, "cheapest"),
        (150, "below_avg"),
        (250, "above_avg"),
        (300, "most_expensive"),
        (999, "most_expensive"),
    ],
)
def test_classify_position(our: float, expected: str) -> None:
    assert classify_position(our, [100, 200, 300]) == expected


def test_compute_price_stats() -> None:
    rows = [
        CompetitorPrice(product_id="x", competitor=c, price=p, in_stock=s, last_checked="d")
        for c, p, s in [("A", 100, True), ("B", 200, False), ("C", 300, True)]
    ]
    stats = compute_price_stats(150, rows)
    assert (stats.competitor_min, stats.competitor_max, stats.competitor_avg) == (100, 300, 200)
    assert stats.position == "below_avg"
    assert stats.diff_vs_avg_pct == -25.0
    assert stats.in_stock_competitors == 2


# ---- tools ---------------------------------------------------------------------------


def test_review_tool_returns_correct_stats(tiny_data_dir: Path) -> None:
    tool = ReviewLoaderTool(source=LocalDataSource(tiny_data_dir))
    data = json.loads(tool.run(product_id="p1"))
    stats = data["stats"]
    assert stats["review_count"] == 4
    assert stats["average_rating"] == 3.25
    assert (stats["positive_pct"], stats["neutral_pct"], stats["negative_pct"]) == (50, 25, 25)
    assert len(data["reviews"]) == 4


def test_price_tool_does_the_math(tiny_data_dir: Path) -> None:
    tool = CompetitorPriceTool(source=LocalDataSource(tiny_data_dir))
    data = json.loads(tool.run(product_id="p1"))
    assert data["stats"]["competitor_avg"] == 200
    assert data["stats"]["position"] == "below_avg"
    assert {c["competitor"] for c in data["competitors"]} == {"A", "B", "C"}


def test_product_tool(tiny_data_dir: Path) -> None:
    tool = ProductInfoTool(source=LocalDataSource(tiny_data_dir))
    data = json.loads(tool.run(product_id="p1"))
    assert data["name"] == "Test Product" and data["features"] == ["feature a"]


def test_tools_return_errors_as_json(tiny_data_dir: Path) -> None:
    src = LocalDataSource(tiny_data_dir)
    assert "not found" in json.loads(ProductInfoTool(source=src).run(product_id="zz"))["error"]
    assert "no reviews" in json.loads(ReviewLoaderTool(source=src).run(product_id="p2"))["error"]


def test_real_data_positions_differ(source: LocalDataSource) -> None:
    """The sample data is designed so each product lands in a different price position."""
    tool = CompetitorPriceTool(source=source)
    positions = {
        p.id: json.loads(tool.run(product_id=p.id))["stats"]["position"]
        for p in source.list_products()
    }
    assert positions == {
        "earbuds-01": "below_avg",
        "watch-01": "most_expensive",
        "bottle-01": "cheapest",
        "backpack-01": "above_avg",
    }
