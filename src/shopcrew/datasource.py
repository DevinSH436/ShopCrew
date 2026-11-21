"""Data access behind a small interface so real sources can be swapped in later.

Only ``local`` (JSON/CSV files in ``data/``) is implemented. ``shopify``, ``woocommerce``
and ``csv_upload`` are registered as stubs that explain they are not implemented yet.
"""

from __future__ import annotations

import csv
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

from shopcrew.exceptions import (
    ConfigError,
    NoCompetitorPricesError,
    NoReviewsError,
    ProductNotFoundError,
)
from shopcrew.models import CompetitorPrice, Product, Review

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


@runtime_checkable
class DataSource(Protocol):
    """Read-only access to products, reviews and competitor prices."""

    def list_products(self) -> list[Product]:
        """Return every product in the catalog."""
        ...

    def get_product(self, product_id: str) -> Product:
        """Return one product or raise ``ProductNotFoundError``."""
        ...

    def get_reviews(self, product_id: str) -> list[Review]:
        """Return reviews for a product, raising ``NoReviewsError`` if there are none."""
        ...

    def get_competitor_prices(self, product_id: str) -> list[CompetitorPrice]:
        """Return competitor prices, raising ``NoCompetitorPricesError`` if there are none."""
        ...


class LocalDataSource:
    """Reads ``products.json``, ``reviews.json`` and ``competitor_prices.csv`` from a folder."""

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_dir():
            raise ConfigError(f"Data directory not found: {self.data_dir}")

    def _read_json(self, name: str) -> list[dict]:
        path = self.data_dir / name
        if not path.exists():
            raise ConfigError(f"Missing data file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_products(self) -> list[Product]:
        """Return every product in ``products.json``."""
        return [Product(**row) for row in self._read_json("products.json")]

    def get_product(self, product_id: str) -> Product:
        """Return one product or raise ``ProductNotFoundError``."""
        products = self.list_products()
        for product in products:
            if product.id == product_id:
                return product
        raise ProductNotFoundError(product_id, [p.id for p in products])

    def get_reviews(self, product_id: str) -> list[Review]:
        """Return all reviews for ``product_id``."""
        self.get_product(product_id)  # validates the ID first
        reviews = [
            Review(**row)
            for row in self._read_json("reviews.json")
            if row.get("product_id") == product_id
        ]
        if not reviews:
            raise NoReviewsError(product_id)
        return reviews

    def get_competitor_prices(self, product_id: str) -> list[CompetitorPrice]:
        """Return competitor price rows for ``product_id``."""
        self.get_product(product_id)
        path = self.data_dir / "competitor_prices.csv"
        if not path.exists():
            raise ConfigError(f"Missing data file: {path}")
        with path.open(newline="", encoding="utf-8") as f:
            rows = [
                CompetitorPrice(
                    product_id=row["product_id"],
                    competitor=row["competitor"],
                    price=float(row["price"]),
                    in_stock=row["in_stock"].strip().lower() in {"true", "1", "yes"},
                    last_checked=row["last_checked"],
                )
                for row in csv.DictReader(f)
                if row["product_id"] == product_id
            ]
        if not rows:
            raise NoCompetitorPricesError(product_id)
        return rows


class _NotImplementedSource:
    """Placeholder for a future connector (Shopify, WooCommerce, CSV upload...)."""

    def __init__(self, name: str) -> None:
        raise ConfigError(
            f"Data source '{name}' is not implemented yet. Use DATA_SOURCE=local. "
            "Implement the DataSource protocol in shopcrew/datasource.py to add it."
        )


SOURCES = ("local", "shopify", "woocommerce", "csv_upload")


def get_data_source(name: str | None = None, data_dir: Path | str | None = None) -> DataSource:
    """Build the data source named by ``name`` (default: ``DATA_SOURCE`` env var or local)."""
    name = (name or os.getenv("DATA_SOURCE") or "local").strip().lower()
    if name not in SOURCES:
        raise ConfigError(f"Unknown data source '{name}'. Choose one of: {', '.join(SOURCES)}")
    if name == "local":
        return LocalDataSource(data_dir or os.getenv("DATA_DIR") or DEFAULT_DATA_DIR)
    return _NotImplementedSource(name)  # type: ignore[return-value]


@lru_cache(maxsize=1)
def default_source() -> DataSource:
    """Process-wide default data source, used by tools when none is injected."""
    return get_data_source()
