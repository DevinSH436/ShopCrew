"""Valid example payloads for each agent output model (fresh copies on every call)."""

from __future__ import annotations

from typing import Any

_LONG = " ".join(["Great earbuds with long battery life and clear calls."] * 20)  # 180 words


def insights_dict() -> dict[str, Any]:
    """A valid ReviewInsights payload."""
    return {
        "average_rating": 3.9,
        "sentiment_breakdown": {"positive": 65, "neutral": 14, "negative": 21},
        "top_praises": ["Long battery life", "Punchy bass"],
        "top_complaints": ["Over-sensitive touch controls"],
        "customer_phrases": ["battery life is insane", "value for money", "punchy bass"],
        "summary": "Customers love the battery life but dislike the touch controls.",
    }


def pricing_dict() -> dict[str, Any]:
    """A valid PricingReport payload."""
    return {
        "our_price": 36,
        "competitor_min": 34.99,
        "competitor_max": 42.99,
        "competitor_avg": 39.39,
        "position": "below_avg",
        "recommended_price": 37,
        "reasoning": "We are 9% below average, so there is room for a small increase.",
    }


def seo_dict() -> dict[str, Any]:
    """A valid SEOCopy payload."""
    return {
        "title": "PulseBeat Pro Wireless Earbuds - 40H Battery, ENC Calls",
        "meta_description": "Wireless earbuds with 40 hours of battery life and clear calls.",
        "bullet_points": ["40H battery", "Fast charge", "ENC mics", "Game mode", "IPX5"],
        "long_description": _LONG,
        "keywords": ["wireless earbuds", "long battery earbuds", "earbuds under 40"],
    }


def campaign_dict() -> dict[str, Any]:
    """A valid CampaignPlan payload (uses the ``7_day_schedule`` alias)."""
    return {
        "target_audience": "Commuters and gym-goers aged 18-30",
        "positioning_statement": "The longest battery life at a better price.",
        "key_message": "40 hours of music for less than the competition.",
        "offer": "Free pouch with every order this week",
        "instagram_caption": "One charge. 40 hours of music. #PulseBeat",
        "google_ad": {"headline": "40H Battery Earbuds", "description": "Under $35."},
        "email": {"subject": "Charge once, listen all day", "body": "Hi there..."},
        "7_day_schedule": [
            {"day": d, "channel": "Instagram", "action": f"Post {d}"} for d in range(1, 8)
        ],
        "how_we_address_complaints": "The demo video shows how to use the touch controls.",
    }
