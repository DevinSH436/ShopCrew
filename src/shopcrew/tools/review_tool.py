"""Tool that gives the Review Analyst a product's reviews plus pre-computed stats."""

from __future__ import annotations

from crewai.tools import BaseTool

from shopcrew.exceptions import ShopCrewError
from shopcrew.stats import compute_review_stats, sentiment_of
from shopcrew.tools.base import DataSourceMixin, ProductIdInput, error_json, to_json


class ReviewLoaderTool(DataSourceMixin, BaseTool):
    """Load all customer reviews for a product, with rating stats computed in code."""

    name: str = "review_loader"
    description: str = (
        "Load every customer review for a product. Returns exact statistics "
        "(review_count, average_rating, rating_histogram, sentiment percentages) "
        "computed in code - use these numbers as-is - plus the full review texts."
    )
    args_schema: type[ProductIdInput] = ProductIdInput

    def _run(self, product_id: str) -> str:
        try:
            reviews = self._source().get_reviews(product_id)
        except ShopCrewError as err:
            return error_json(err)
        stats = compute_review_stats(reviews)
        return to_json(
            {
                "product_id": product_id,
                "stats": stats.model_dump(),
                "reviews": [
                    {"rating": r.rating, "sentiment": sentiment_of(r.rating), "text": r.text}
                    for r in reviews
                ],
            }
        )
