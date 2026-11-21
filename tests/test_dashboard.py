"""Headless test of the Streamlit dashboard using Streamlit's AppTest."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")


@pytest.fixture(autouse=True)
def _demo_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODEL", "mock")
    monkeypatch.setattr("shopcrew.runner.OUTPUTS_DIR", tmp_path)


def test_dashboard_loads() -> None:
    at = AppTest.from_file(DASHBOARD, default_timeout=30).run()
    assert not at.exception, [ascii(e.value) for e in at.exception]
    assert at.title[0].value.endswith("ShopCrew")
    assert any("Run Crew" in b.label for b in at.button)


def test_dashboard_runs_crew_and_shows_results() -> None:
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    run_button = next(b for b in at.button if "Run Crew" in b.label)
    at = run_button.click().run()
    assert not at.exception, [ascii(e.value) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "⭐ Reviews",
        "$ Prices",
        "¶ SEO",
        "↗ Marketing",
        "Run log",
    ]
    assert any(m.label == "Average rating" for m in at.metric)
