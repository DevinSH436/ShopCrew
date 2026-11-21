"""Domain errors with messages written for the person running the crew."""

from __future__ import annotations


class ShopCrewError(Exception):
    """Base class for all ShopCrew errors."""


class ProductNotFoundError(ShopCrewError):
    """Raised when a product ID does not exist in the data source."""

    def __init__(self, product_id: str, available: list[str]) -> None:
        self.product_id = product_id
        self.available = available
        super().__init__(
            f"Product '{product_id}' not found. Available products: {', '.join(available)}"
        )


class NoReviewsError(ShopCrewError):
    """Raised when a product has no reviews, so the Review Analyst has nothing to analyse."""

    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        super().__init__(
            f"Product '{product_id}' has no reviews. Add reviews to the data source "
            "before running the crew."
        )


class NoCompetitorPricesError(ShopCrewError):
    """Raised when a product has no competitor price rows."""

    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        super().__init__(
            f"Product '{product_id}' has no competitor prices, so pricing cannot be compared."
        )


class ConfigError(ShopCrewError):
    """Raised for missing or invalid configuration (e.g. no API key)."""
