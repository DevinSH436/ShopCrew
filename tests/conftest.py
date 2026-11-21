"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shopcrew.datasource import DEFAULT_DATA_DIR, LocalDataSource


@pytest.fixture(autouse=True)
def _isolated_outputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Runs made by tests go to a temp folder, never the real ``outputs/``."""
    monkeypatch.setattr("shopcrew.runner.OUTPUTS_DIR", tmp_path / "outputs")


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no test ever reaches a paid LLM API."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CREWAI_DISABLE_TELEMETRY", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")


@pytest.fixture
def source() -> LocalDataSource:
    """The real sample data shipped in ``data/``."""
    return LocalDataSource(DEFAULT_DATA_DIR)


@pytest.fixture
def tiny_data_dir(tmp_path: Path) -> Path:
    """A minimal data folder with hand-checkable numbers.

    ``p1`` has 4 reviews (5, 4, 3, 1) and competitors at 100/200/300 with our price 150.
    ``p2`` exists but has no reviews or competitor prices.
    """
    products = [
        {
            "id": "p1",
            "name": "Test Product",
            "category": "Test",
            "our_price": 150,
            "current_description": "desc",
            "features": ["feature a"],
        },
        {
            "id": "p2",
            "name": "Empty Product",
            "category": "Test",
            "our_price": 99,
            "current_description": "desc",
            "features": [],
        },
    ]
    reviews = [
        {"product_id": "p1", "rating": r, "text": f"review {r}", "date": "2026-01-01"}
        for r in (5, 4, 3, 1)
    ]
    (tmp_path / "products.json").write_text(json.dumps(products), encoding="utf-8")
    (tmp_path / "reviews.json").write_text(json.dumps(reviews), encoding="utf-8")
    (tmp_path / "competitor_prices.csv").write_text(
        "product_id,competitor,price,in_stock,last_checked\n"
        "p1,A,100,true,2026-01-01\n"
        "p1,B,200,false,2026-01-01\n"
        "p1,C,300,true,2026-01-01\n",
        encoding="utf-8",
    )
    return tmp_path
