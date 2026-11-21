"""Tool that gives the Price Tracker competitor prices and the maths already done."""

from __future__ import annotations

from crewai.tools import BaseTool

from shopcrew.exceptions import ShopCrewError
from shopcrew.stats import compute_price_stats
from shopcrew.tools.base import DataSourceMixin, ProductIdInput, error_json, to_json


class CompetitorPriceTool(DataSourceMixin, BaseTool):
    """Return competitor price rows plus min/max/avg and our market position."""

    name: str = "competitor_prices"
    description: str = (
        "Get competitor prices for a product. Returns each competitor's price and stock "
        "status, plus our_price, competitor_min, competitor_max, competitor_avg and "
        "position computed in code. Do not recompute these numbers; interpret them."
    )
    args_schema: type[ProductIdInput] = ProductIdInput

    def _run(self, product_id: str) -> str:
        try:
            source = self._source()
            product = source.get_product(product_id)
            rows = source.get_competitor_prices(product_id)
        except ShopCrewError as err:
            return error_json(err)
        stats = compute_price_stats(product.our_price, rows)
        return to_json(
            {
                "product_id": product_id,
                "currency": "USD",
                "stats": stats.model_dump(),
                "competitors": [
                    {
                        "competitor": r.competitor,
                        "price": r.price,
                        "in_stock": r.in_stock,
                        "last_checked": r.last_checked,
                    }
                    for r in rows
                ],
            }
        )
