"""Deterministic maths for reviews and prices.

The spec requires numbers to be computed in code, not by the LLM, so that they are
always correct. Tools expose these results to agents, and the runner uses them to
overwrite any numeric field an agent got wrong.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from shopcrew.models import CompetitorPrice, PricePosition, PriceStats, Review, ReviewStats


def sentiment_of(rating: int) -> str:
    """Map a 1-5 star rating to a sentiment label (4-5 positive, 3 neutral, 1-2 negative)."""
    if rating >= 4:
        return "positive"
    if rating == 3:
        return "neutral"
    return "negative"


def compute_review_stats(reviews: Sequence[Review]) -> ReviewStats:
    """Compute review count, average rating, histogram and sentiment percentages."""
    if not reviews:
        raise ValueError("cannot compute stats for an empty review list")
    count = len(reviews)
    histogram = Counter(r.rating for r in reviews)
    sentiments = Counter(sentiment_of(r.rating) for r in reviews)
    pct = {k: round(sentiments.get(k, 0) / count * 100, 1) for k in ("positive", "neutral")}
    # Derive the last bucket so the three always sum to exactly 100.
    negative = round(100 - pct["positive"] - pct["neutral"], 1)
    return ReviewStats(
        review_count=count,
        average_rating=round(sum(r.rating for r in reviews) / count, 2),
        rating_histogram={star: histogram.get(star, 0) for star in range(5, 0, -1)},
        positive_pct=pct["positive"],
        neutral_pct=pct["neutral"],
        negative_pct=negative,
    )


def classify_position(our_price: float, prices: Sequence[float]) -> PricePosition:
    """Classify our price against competitor prices.

    ``cheapest`` if we are at or below every competitor, ``most_expensive`` if we are at
    or above every competitor, otherwise ``below_avg`` / ``above_avg`` relative to the mean.
    """
    low, high = min(prices), max(prices)
    avg = sum(prices) / len(prices)
    if our_price <= low:
        return "cheapest"
    if our_price >= high:
        return "most_expensive"
    return "below_avg" if our_price < avg else "above_avg"


def compute_price_stats(our_price: float, rows: Sequence[CompetitorPrice]) -> PriceStats:
    """Compute min/max/avg competitor price and our market position."""
    if not rows:
        raise ValueError("cannot compute stats without competitor prices")
    prices = [row.price for row in rows]
    avg = sum(prices) / len(prices)
    return PriceStats(
        our_price=our_price,
        competitor_min=min(prices),
        competitor_max=max(prices),
        competitor_avg=round(avg, 2),
        position=classify_position(our_price, prices),
        diff_vs_avg_pct=round((our_price - avg) / avg * 100, 1),
        in_stock_competitors=sum(1 for row in rows if row.in_stock),
    )
