"""Tests for the unsupported-claim detector.

The ``OLLAMA_*`` sentences are verbatim from a real qwen3.5:4b run that the earlier
guardrails let through.
"""

from __future__ import annotations

import pytest

from shopcrew.claims import collect_text, find_unsupported_claims
from shopcrew.datasource import LocalDataSource
from shopcrew.demo import demo_campaign_plan, demo_seo_copy
from shopcrew.models import Product

OLLAMA_ONLY = (
    "The only wireless earbuds offering up to 40 hours of total playtime at a competitive "
    "price point, perfect for all-day use."
)
OLLAMA_OPTIMIZED = (
    "That's why we've optimized our case design and sound clarity to maximize your experience."
)
OLLAMA_SEVEN_DAYS = (
    "Showcase a 7-day usage timer graphic with text: 'From Day 1 to Day 7: Still Charged'."
)
ANC = "feature not listed (active noise cancellation)"


def _check(source: LocalDataSource, text: str, product_id: str = "earbuds-01") -> list[str]:
    product = source.get_product(product_id)
    reviews = [r.text for r in source.get_reviews(product_id)]
    return [i.kind for i in find_unsupported_claims([text], product, reviews)]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (OLLAMA_ONLY, "exclusivity/guarantee"),
        (OLLAMA_OPTIMIZED, "unverified product change"),
        (OLLAMA_SEVEN_DAYS, "duration not in features"),
        ("Guaranteed to last all day.", "exclusivity/guarantee"),
        ("Block out the metro with active noise cancellation.", ANC),
        ("Fully waterproof for swimming.", "feature not listed (waterproof)"),
        ("Comes with a 2-year warranty.", "feature not listed (warranty)"),
        # verbatim from a real qwen3.5:4b run
        (
            "Free premium carrying case and 6-month extended warranty to justify our value.",
            "feature not listed (warranty)",
        ),
        ("Enjoy 60 hours of playback.", "duration not in features"),
    ],
)
def test_flags_unsupported_claims(source: LocalDataSource, text: str, kind: str) -> None:
    assert kind in _check(source, text)


@pytest.mark.parametrize(
    "text",
    [
        "Up to 40 hours of playtime with the case and 8 h per charge.",
        "A 10-minute fast charge gives 2 hours of playback.",
        "These earbuds do not have ANC, but Quad-mic ENC keeps calls clear.",
        # verbatim from a real qwen3.5:4b run, previously a false positive
        "Address complaints: 'Honest talk about mic in wind vs ANC, plus fit tips for small ears.'",
        "Customers say 'battery life is insane, I charge the case maybe once a week'.",
        "Launch week: extra 5% off with code LAUNCH5 for 72 hours only.",
        "Best value wireless earbuds under $35.",
    ],
)
def test_allows_supported_text(source: LocalDataSource, text: str) -> None:
    assert _check(source, text) == []


def test_waterproof_allowed_when_product_is_ip68(source: LocalDataSource) -> None:
    assert _check(source, "Waterproof enough for the pool.", "watch-01") == []


@pytest.mark.parametrize(
    ("feature", "allowed"),
    [("IPX7: survives a dunk", True), ("5 ATM swim-proof", True), ("IPX5 splash", False)],
)
def test_waterproof_needs_an_immersion_rating(feature: str, allowed: bool) -> None:
    # Regression: a real qwen3.5:4b run on an IPX7 speaker wrote "IPX7 waterproof".
    product = Product(
        id="spk", name="Speaker", category="Audio", our_price=999,
        current_description="d", features=[feature],
    )  # fmt: skip
    issues = find_unsupported_claims(["Deep bass & IPX7 waterproof."], product, [])
    assert (issues == []) is allowed


def test_invented_slogan_in_quotes_is_still_checked(source: LocalDataSource) -> None:
    """Quotes are only exempt when a customer actually wrote them."""
    assert _check(source, "Our tagline: 'Still charged after a week of battery use'.") != []


@pytest.mark.parametrize("product_id", ["earbuds-01", "watch-01", "bottle-01", "backpack-01"])
def test_demo_outputs_are_claim_free(source: LocalDataSource, product_id: str) -> None:
    product = source.get_product(product_id)
    reviews = [r.text for r in source.get_reviews(product_id)]
    for output in (demo_seo_copy(source, product_id), demo_campaign_plan(source, product_id)):
        texts = collect_text(output.model_dump(mode="json", by_alias=True))
        assert find_unsupported_claims(texts, product, reviews) == []
