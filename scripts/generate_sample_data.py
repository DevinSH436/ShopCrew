"""Generate the deterministic sample data in ``data/``.

Run with ``uv run python scripts/generate_sample_data.py``. The output is committed, so
this script only needs re-running if you change the product catalogue or review pools.
Reviews are assembled from hand-written, product-specific snippets with a fixed seed so
the data looks realistic but is reproducible.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEED = 42

PRODUCTS: list[dict] = [
    {
        "id": "earbuds-01",
        "name": "PulseBeat Pro Wireless Earbuds",
        "category": "Audio / True Wireless Earbuds",
        "our_price": 36,
        "current_description": "Wireless earbuds with good sound and long battery. Bluetooth 5.3.",
        "features": [
            "Up to 40 hours total playtime with charging case (8 h per charge)",
            "10-minute fast charge gives 2 hours of playback",
            "Bluetooth 5.3 with one-tap pairing",
            "Quad-mic ENC for clear calls",
            "40 ms low-latency game mode",
            "IPX5 sweat and splash resistance",
            "Touch controls and voice assistant support",
        ],
    },
    {
        "id": "watch-01",
        "name": "FitPulse Active Smartwatch",
        "category": "Wearables / Smartwatch",
        "our_price": 57,
        "current_description": "Smartwatch with AMOLED display and health tracking.",
        "features": [
            '1.83" AMOLED display, 600 nits peak brightness',
            "Bluetooth calling with built-in mic and speaker",
            "24x7 heart rate, SpO2 and sleep tracking",
            "100+ sports modes",
            "Up to 7 days battery life (2 days with heavy calling)",
            "IP68 water and dust resistance",
            "Customisable watch faces",
        ],
    },
    {
        "id": "bottle-01",
        "name": "HydroSteel Insulated Water Bottle 1L",
        "category": "Home & Kitchen / Drinkware",
        "our_price": 12,
        "current_description": "Steel water bottle that keeps drinks hot and cold.",
        "features": [
            "Double-wall vacuum insulation: 24 h cold, 12 h hot",
            "Food-grade 18/8 stainless steel, BPA-free",
            "Leak-proof screw lid with carry loop",
            "1 litre capacity",
            "Powder-coated, sweat-free exterior",
            "Fits most car cup holders",
        ],
    },
    {
        "id": "backpack-01",
        "name": "UrbanTrek 30L Laptop Backpack",
        "category": "Bags / Laptop Backpack",
        "our_price": 26,
        "current_description": "Laptop backpack with many pockets and USB port.",
        "features": [
            '30 L capacity with padded sleeve for laptops up to 15.6"',
            "Water-resistant polyester fabric",
            "External USB charging port (power bank not included)",
            "Hidden anti-theft back pocket",
            "Breathable padded shoulder straps and back panel",
            "Luggage trolley strap",
        ],
    },
]

# Per product: positive / neutral / negative review snippets.
REVIEW_POOLS: dict[str, dict[str, list[str]]] = {
    "earbuds-01": {
        "positive": [
            "Battery life is insane, I charge the case maybe once a week.",
            "Best battery life I have had in budget earbuds, easily lasts my whole work day.",
            "Bass is punchy and the sound is very clear for this price.",
            "Pairing was instant, they connect as soon as I open the case.",
            "Call quality is surprisingly good, people can hear me even on the road.",
            "Game mode actually works, no delay in BGMI.",
            "Fast charging is a lifesaver, 10 minutes and I am good for my commute.",
            "Very comfortable fit, I wear them for hours at the gym without pain.",
            "Value for money, sounds better than earbuds costing double.",
            "Survived a lot of sweaty workouts, no issues so far.",
        ],
        "neutral": [
            "Sound is decent, nothing extraordinary but fine for daily use.",
            "Good earbuds overall but the case is a bit bulky for small pockets.",
            "Works as expected. Battery is great, ANC would have been nice.",
            "Okay product, touch controls take some getting used to.",
        ],
        "negative": [
            "Touch controls are too sensitive, music pauses when I adjust them.",
            "Left earbud disconnects randomly once in a while.",
            "No active noise cancellation, so they are useless in the subway.",
            "Case hinge feels cheap and loose after two months.",
            "Fit is not great for small ears, they keep falling out while running.",
            "Mic is bad in windy conditions.",
        ],
    },
    "watch-01": {
        "positive": [
            "The AMOLED display is gorgeous and super bright even in sunlight.",
            "Bluetooth calling works really well, I take calls while cooking.",
            "Sleep tracking is surprisingly detailed and accurate.",
            "Looks premium, people think it is a much more expensive watch.",
            "Lots of watch faces to choose from, I change it every day.",
            "Strap is comfortable even when I wear it all night.",
            "Heart rate readings match my gym equipment closely.",
            "Notifications come through instantly, very handy in meetings.",
        ],
        "neutral": [
            "Nice watch but the app could be more polished.",
            "Battery is okay, about 4 to 5 days for me with normal use.",
            "Decent for the price, step count sometimes overcounts.",
            "Good display, but sports modes are more than I will ever use.",
        ],
        "negative": [
            "Battery drains fast if you use calling, barely 2 days.",
            "GPS is only connected GPS, need my phone for runs.",
            "Price is high compared to similar watches on sale.",
            "App keeps disconnecting from my phone and I have to re-pair.",
            "SpO2 readings are inconsistent.",
            "Charger is proprietary and the magnet is weak.",
        ],
    },
    "bottle-01": {
        "positive": [
            "Keeps water ice cold for a full day, even in Phoenix summer.",
            "Completely leak-proof, I throw it in my laptop bag without worry.",
            "Tea stays hot till evening, great for long train journeys.",
            "Sturdy build, survived multiple drops with just a small dent.",
            "No metallic taste at all, very happy with it.",
            "Fits perfectly in my car cup holder.",
            "Matte finish looks great and does not sweat.",
            "Best purchase for office, I drink more water now.",
        ],
        "neutral": [
            "Good bottle, a little heavy when full.",
            "Does the job. Mouth is a bit narrow for ice cubes.",
            "Fine quality, colour slightly different from the photo.",
        ],
        "negative": [
            "Paint started chipping near the base after a month.",
            "Mouth is too narrow to clean properly without a brush.",
            "Got a dent on delivery, packaging was poor.",
            "Lid is hard to open with wet hands.",
        ],
    },
    "backpack-01": {
        "positive": [
            "Lots of compartments, everything has a place.",
            "Laptop sleeve is well padded, my 15.6 inch laptop fits perfectly.",
            "Anti-theft pocket is very useful in crowded buses.",
            "Shoulder straps are comfortable even with a heavy load.",
            "Looks professional, perfect for office and college.",
            "Survived heavy Seattle rain, everything inside stayed dry.",
            "USB port is handy for charging the phone on the go.",
            "Trolley strap makes airport travel easy.",
        ],
        "neutral": [
            "Good bag but slightly smaller than I expected for 30 litres.",
            "Decent quality. Water bottle side pocket is a bit tight.",
            "Okay for the price, zips could be smoother.",
        ],
        "negative": [
            "Zipper broke within three months of daily use.",
            "Stitching on the handle came loose quickly.",
            "Side pocket cannot hold a 1 litre bottle.",
            "USB port cable came out from inside after a few weeks.",
            "Fabric smells strongly of chemicals when new.",
        ],
    },
}

RATING_WEIGHTS = {5: 0.38, 4: 0.27, 3: 0.14, 2: 0.11, 1: 0.10}

# Competitor rows: (competitor, price, in_stock). Chosen so each product lands in a
# different pricing position, which makes the demo more interesting.
COMPETITORS: dict[str, list[tuple[str, int, bool]]] = {
    "earbuds-01": [  # we are below average
        ("MegaStore", 39.99, True),
        ("ShopMart", 37.99, True),
        ("TechBarn", 42.99, True),
        ("GadgetHub", 40.99, False),
        ("ClickCart", 34.99, True),
    ],
    "watch-01": [  # we are the most expensive
        ("MegaStore", 49.99, True),
        ("ShopMart", 46.99, True),
        ("TechBarn", 53.99, True),
        ("GadgetHub", 52.99, True),
        ("ClickCart", 50.99, False),
    ],
    "bottle-01": [  # we are the cheapest
        ("MegaStore", 13.99, True),
        ("ShopMart", 13.99, True),
        ("GlowBox Home", 16.99, True),
        ("HomeNest", 15.99, False),
        ("ValueMart", 12.99, True),
    ],
    "backpack-01": [  # we are above average but not the most expensive
        ("MegaStore", 23.99, True),
        ("ShopMart", 22.99, True),
        ("StyleLane", 26.99, True),
        ("Threadly", 24.99, True),
        ("ClickCart", 23.99, False),
    ],
}

REVIEWS_PER_PRODUCT = 36
TODAY = date(2026, 11, 15)


def _sentiment_for_rating(rating: int) -> str:
    if rating >= 4:
        return "positive"
    if rating == 3:
        return "neutral"
    return "negative"


def build_reviews(rng: random.Random) -> list[dict]:
    """Build a list of review dicts for every product."""
    reviews: list[dict] = []
    ratings = list(RATING_WEIGHTS)
    weights = list(RATING_WEIGHTS.values())
    for product in PRODUCTS:
        pool = REVIEW_POOLS[product["id"]]
        for _ in range(REVIEWS_PER_PRODUCT):
            rating = rng.choices(ratings, weights)[0]
            sentiment = _sentiment_for_rating(rating)
            sentences = rng.sample(pool[sentiment], k=min(2, len(pool[sentiment])))
            sentences = sentences[: rng.randint(1, len(sentences))]
            if sentiment == "positive" and rng.random() < 0.25:
                # Positive reviews sometimes mention a small gripe, like real ones do.
                sentences.append("Only issue: " + rng.choice(pool["negative"]).lower())
            review_date = TODAY - timedelta(days=rng.randint(1, 180))
            reviews.append(
                {
                    "product_id": product["id"],
                    "rating": rating,
                    "text": " ".join(sentences),
                    "date": review_date.isoformat(),
                }
            )
    return reviews


def main() -> None:
    """Write products.json, reviews.json and competitor_prices.csv."""
    rng = random.Random(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "products.json").write_text(json.dumps(PRODUCTS, indent=2), encoding="utf-8")
    (DATA_DIR / "reviews.json").write_text(
        json.dumps(build_reviews(rng), indent=2), encoding="utf-8"
    )
    with (DATA_DIR / "competitor_prices.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["product_id", "competitor", "price", "in_stock", "last_checked"])
        for product_id, rows in COMPETITORS.items():
            for competitor, price, in_stock in rows:
                checked = TODAY - timedelta(days=rng.randint(0, 3))
                writer.writerow(
                    [product_id, competitor, price, str(in_stock).lower(), checked.isoformat()]
                )
    print(f"Sample data written to {DATA_DIR}")


if __name__ == "__main__":
    main()
