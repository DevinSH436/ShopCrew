"""Tool that returns a product's catalogue details (name, price, real features)."""

from __future__ import annotations

from crewai.tools import BaseTool

from shopcrew.exceptions import ShopCrewError
from shopcrew.tools.base import DataSourceMixin, ProductIdInput, error_json, to_json


class ProductInfoTool(DataSourceMixin, BaseTool):
    """Return product details. The feature list is the source of truth for claims."""

    name: str = "product_info"
    description: str = (
        "Get a product's name, category, our price (INR), current description and its "
        "feature list. Only the listed features may be claimed in any copy."
    )
    args_schema: type[ProductIdInput] = ProductIdInput

    def _run(self, product_id: str) -> str:
        try:
            product = self._source().get_product(product_id)
        except ShopCrewError as err:
            return error_json(err)
        return to_json(product.model_dump())
