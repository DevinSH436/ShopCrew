"""Create and fill the store database with a realistic demo catalog and order history.

Usage::

    uv run python -m northcart.seed            # create tables and seed if the DB is empty
    uv run python -m northcart.seed --reset    # drop everything and reseed

Demo sign-ins come from ``.env`` (``ADMIN_EMAIL`` / ``ADMIN_PASSWORD`` and
``DEMO_CUSTOMER_EMAIL`` / ``DEMO_CUSTOMER_PASSWORD``); see ``.env.example``.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from northcart import catalog_data as cd
from northcart import db as dbmod
from northcart.config import PROJECT_ROOT, get_settings
from northcart.models import (
    ORDER_FLOW,
    Address,
    Category,
    CompetitorPrice,
    Coupon,
    Order,
    OrderItem,
    Product,
    Review,
    User,
)
from northcart.security import hash_password
from northcart.services.catalog import refresh_rating
from northcart.services.orders import COURIERS, add_event, delivery_estimate

SEED = 7
NOW = datetime.now(UTC).replace(microsecond=0)
DATA_DIR = PROJECT_ROOT / "data"

CUSTOMER_CITIES = [
    ("New York", "New York", "10011"), ("Brooklyn", "New York", "11215"),
    ("Boston", "Massachusetts", "02116"), ("Philadelphia", "Pennsylvania", "19103"),
    ("Washington", "District of Columbia", "20009"), ("Atlanta", "Georgia", "30308"),
    ("Miami", "Florida", "33130"), ("Columbus", "Ohio", "43215"),
    ("Chicago", "Illinois", "60614"), ("Minneapolis", "Minnesota", "55408"),
    ("Dallas", "Texas", "75204"), ("Houston", "Texas", "77006"),
    ("Austin", "Texas", "78704"), ("Denver", "Colorado", "80206"),
    ("Phoenix", "Arizona", "85004"), ("Los Angeles", "California", "90026"),
    ("San Diego", "California", "92103"), ("San Francisco", "California", "94110"),
    ("Portland", "Oregon", "97214"), ("Seattle", "Washington", "98122"),
]  # fmt: skip
FIRST = ["James", "Olivia", "Liam", "Emma", "Noah", "Ava", "Ethan", "Sophia", "Mason", "Mia",
         "Lucas", "Amelia", "Logan", "Harper", "Jacob", "Evelyn", "Daniel", "Abigail", "Henry",
         "Emily", "Jackson", "Ella", "Sebastian", "Grace", "Aiden", "Chloe", "Carlos", "Maria",
         "Jamal", "Aaliyah", "Kevin", "Priya", "Wei", "Mei", "Diego", "Sofia"]  # fmt: skip
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Jackson",
        "Lee", "Harris", "Clark", "Lewis", "Walker", "Young", "Nguyen", "Patel"]  # fmt: skip
STREETS = [
    "Main Street",
    "Oak Avenue",
    "Maple Drive",
    "Park Avenue",
    "Elm Street",
    "Washington Boulevard",
    "Lakeview Road",
    "Cedar Lane",
    "Sunset Boulevard",
    "Pine Street",
]


def _load_shopcrew_data() -> tuple[dict, dict[str, list[dict]], dict[str, list[dict]]]:
    products = {p["id"]: p for p in json.loads((DATA_DIR / "products.json").read_text("utf-8"))}
    reviews: dict[str, list[dict]] = {}
    for r in json.loads((DATA_DIR / "reviews.json").read_text("utf-8")):
        reviews.setdefault(r["product_id"], []).append(r)
    prices: dict[str, list[dict]] = {}
    with (DATA_DIR / "competitor_prices.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prices.setdefault(row["product_id"], []).append(row)
    return products, reviews, prices


def _review_body(rng: random.Random, spec: dict, rating: int) -> str:
    pros = spec.get("pros", []) or ["Works well."]
    cons = spec.get("cons", []) or ["Nothing major."]
    if rating == 5:
        parts = rng.sample(pros, min(len(pros), rng.choice([1, 2]))) + (
            [rng.choice(cd.GENERIC_PRAISE)] if rng.random() < 0.5 else []
        )
    elif rating == 4:
        parts = [rng.choice(pros), rng.choice(cons) if rng.random() < 0.5 else ""]
        parts.append(rng.choice(cd.GENERIC_PRAISE) if rng.random() < 0.4 else "")
    elif rating == 3:
        parts = [rng.choice(cd.GENERIC_NEUTRAL), rng.choice(pros), rng.choice(cons)]
    else:
        parts = rng.sample(cons, min(len(cons), 2)) + (
            [rng.choice(cd.GENERIC_COMPLAINT)] if rng.random() < 0.5 else []
        )
    return " ".join(p for p in parts if p)


def _rating(rng: random.Random, quality: float) -> int:
    weights = {5: 40 * quality, 4: 30, 3: 14, 2: 7 / quality, 1: 6 / quality}
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _make_user(rng: random.Random, i: int) -> User:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    city, state, pin = rng.choice(CUSTOMER_CITIES)
    user = User(
        email=f"{first.lower()}.{last.lower()}{i}@example.com",
        name=f"{first} {last}",
        phone=f"{rng.randint(201, 989)}555{rng.randint(1000, 9999)}",
        password_hash="!",  # cannot sign in
        created_at=NOW - timedelta(days=rng.randint(20, 400)),
    )
    user.addresses.append(
        Address(
            full_name=user.name,
            phone=user.phone,
            line1=f"{rng.randint(10, 9800)} {rng.choice(STREETS)}",
            line2=rng.choice(["", "", f"Apt {rng.randint(1, 30)}{rng.choice('ABCD')}"]),
            city=city,
            state=state,
            zip_code=pin,
            is_default=True,
        )
    )
    return user


def _seed_orders(db: Session, rng: random.Random, users: list[User], products: list[Product]):
    """About 420 orders over the last 120 days, busier on weekends and recent weeks."""
    popularity = [max(1.0, 9 / p.price) for p in products]
    used: set[str] = set()
    for day in range(120, -1, -1):
        when = NOW - timedelta(days=day)
        base = 2.2 + (120 - day) / 60 + (1.2 if when.weekday() >= 5 else 0)
        for _ in range(rng.randint(int(base), int(base) + 3)):
            user = rng.choice(users)
            addr = user.addresses[0]
            placed = when.replace(hour=rng.randint(8, 23), minute=rng.randint(0, 59))
            if placed > NOW:
                placed = NOW - timedelta(minutes=rng.randint(5, 600))
            picks = rng.choices(products, weights=popularity, k=rng.choice([1, 1, 1, 2, 2, 3]))
            items = {p.id: p for p in picks}.values()
            number = f"NC-{placed:%y%m}-{rng.randint(100000, 999999)}"
            while number in used:
                number = f"NC-{placed:%y%m}-{rng.randint(100000, 999999)}"
            used.add(number)
            order = Order(
                number=number,
                user=user,
                payment_method=rng.choices(["card", "paypal", "bank", "cod"], [62, 25, 8, 5])[0],
                ship_name=addr.full_name,
                ship_phone=addr.phone,
                ship_line1=addr.line1,
                ship_line2=addr.line2,
                ship_city=addr.city,
                ship_state=addr.state,
                ship_zip=addr.zip_code,
                created_at=placed,
                subtotal=0,
                total=0,
                discount=0,
                coupon_code="",
            )
            for p in items:
                qty = rng.choices([1, 2, 3], [85, 12, 3])[0]
                order.items.append(
                    OrderItem(product_id=p.id, name=p.name, sku=p.sku, price=p.price,
                              mrp=p.mrp, quantity=qty)
                )  # fmt: skip
                p.sold_count += qty
            order.subtotal = sum(i.price * i.quantity for i in order.items)
            order.mrp_total = sum(i.mrp * i.quantity for i in order.items)
            if rng.random() < 0.18 and order.subtotal >= 25:
                order.coupon_code = "WELCOME10"
                order.discount = min(15, order.subtotal // 10)
            after = order.subtotal - order.discount
            order.shipping_fee = 5 if after < 35 else 0
            order.cod_fee = 2 if order.payment_method == "cod" else 0
            order.total = after + order.shipping_fee + order.cod_fee
            order.expected_delivery = delivery_estimate(addr.zip_code, placed)
            online = order.payment_method != "cod"
            order.payment_status = "paid" if online else "pending"
            order.payment_ref = f"pay_{rng.getrandbits(48):012x}" if online else ""
            add_event(order, "placed", "Order placed.", placed)

            # Walk the order along its lifecycle according to its age.
            age_h = (NOW - placed).total_seconds() / 3600
            fate = rng.random()
            if fate < 0.05 and age_h > 2:
                add_event(order, "cancelled", "Cancelled by customer.", placed + timedelta(hours=2))
                if online:
                    order.payment_status = "refunded"
            else:
                hours = {"confirmed": 1, "packed": 14, "shipped": 26, "out_for_delivery": 70,
                         "delivered": 78}  # fmt: skip
                for status in ORDER_FLOW[1:]:
                    if age_h < hours[status]:
                        break
                    at = placed + timedelta(hours=hours[status] + rng.random() * 4)
                    if status == "shipped":
                        order.courier = rng.choice(COURIERS)
                        order.tracking_number = str(rng.randint(10**11, 10**12 - 1))
                        add_event(order, status, f"Shipped with {order.courier}.", at)
                    else:
                        add_event(order, status, "", at)
                    if status == "delivered":
                        order.delivered_at = at
                        order.payment_status = "paid"
                if order.status == "delivered" and rng.random() < 0.03:
                    at = order.delivered_at + timedelta(days=2)  # type: ignore[operator]
                    add_event(order, "return_requested", "Return requested: size issue", at)
                    add_event(order, "returned", "Return received. Refund initiated.",
                              at + timedelta(days=3))  # fmt: skip
                    order.payment_status = "refunded"
            db.add(order)


def seed(db: Session) -> None:
    """Fill an empty database."""
    rng = random.Random(SEED)
    settings = get_settings()
    crew_products, crew_reviews, crew_prices = _load_shopcrew_data()

    cats: dict[str, Category] = {}
    for i, c in enumerate(cd.CATEGORIES):
        cats[c["slug"]] = Category(sort_order=i, **c)
        db.add(cats[c["slug"]])

    products: list[Product] = []
    for spec in cd.PRODUCTS:
        crew = crew_products.get(spec.get("shopcrew_id", ""))
        highlights = spec.get("highlights") or (crew["features"][:6] if crew else [])
        description = spec.get("description") or " ".join(
            [spec["short"], *(f"{h}." for h in highlights[:4])]
        )
        p = Product(
            slug=spec["slug"], sku=spec["sku"], name=spec["name"], brand=spec["brand"],
            category=cats[spec["cat"]], price=spec["price"], mrp=spec["mrp"],
            cost_price=spec["cost"], stock=spec["stock"], short_description=spec["short"],
            description=description, highlights=highlights, specs=spec.get("specs", {}),
            tags=spec.get("tags", []), art_kind=spec["art"], color=spec["color"],
            is_featured=spec.get("featured", False),
            created_at=NOW - timedelta(days=rng.randint(5, 240)),
        )  # fmt: skip
        db.add(p)
        products.append(p)

        # Reviews
        if crew:
            for r in crew_reviews.get(crew["id"], []):
                p.reviews.append(
                    Review(
                        author_name=rng.choice(cd.REVIEWER_NAMES),
                        author_city=rng.choice(cd.CITIES),
                        rating=int(r["rating"]),
                        title=rng.choice(cd.TITLES[int(r["rating"])]),
                        body=r["text"],
                        verified_purchase=rng.random() < 0.9,
                        helpful_count=rng.choice([0, 0, 1, 2, 3, 5, 8, 13, 21]),
                        created_at=datetime.fromisoformat(r["date"]).replace(
                            tzinfo=UTC, hour=rng.randint(8, 22)
                        ),
                    )
                )
        else:
            quality = rng.uniform(0.8, 1.6)
            for _ in range(rng.randint(14, 48)):
                rating = _rating(rng, quality)
                p.reviews.append(
                    Review(
                        author_name=rng.choice(cd.REVIEWER_NAMES),
                        author_city=rng.choice(cd.CITIES),
                        rating=rating,
                        title=rng.choice(cd.TITLES[rating]),
                        body=_review_body(rng, spec, rating),
                        verified_purchase=rng.random() < 0.85,
                        helpful_count=rng.choice([0, 0, 0, 1, 2, 4, 7, 12]),
                        created_at=NOW
                        - timedelta(days=rng.randint(1, 300), hours=rng.randint(0, 23)),
                    )
                )

        # Competitor prices
        if crew:
            for row in crew_prices.get(crew["id"], []):
                p.competitor_prices.append(
                    CompetitorPrice(
                        competitor=row["competitor"],
                        price=int(float(row["price"])),
                        in_stock=row["in_stock"].lower() == "true",
                        last_checked=datetime.fromisoformat(row["last_checked"]).replace(
                            tzinfo=UTC
                        ),
                    )
                )
        else:
            names = cd.COMPETITORS.get(spec["cat"], cd.COMPETITORS["default"])
            for name in rng.sample(names, min(len(names), 4)):
                factor = rng.uniform(0.9, 1.22)
                price = round(spec["price"] * factor)
                p.competitor_prices.append(
                    CompetitorPrice(
                        competitor=name, price=max(1, price), in_stock=rng.random() < 0.85,
                        last_checked=NOW - timedelta(days=rng.randint(0, 6)),
                    )
                )  # fmt: skip

    # People
    admin = User(email=settings.admin_email, name="Alex Morgan", phone="6145550100",
                 password_hash=hash_password(settings.admin_password), is_admin=True)  # fmt: skip
    demo = User(
        email=os.getenv("DEMO_CUSTOMER_EMAIL", "customer@northcart.test"),
        name="Jordan Taylor",
        phone="6145550123",
        password_hash=hash_password(os.getenv("DEMO_CUSTOMER_PASSWORD", "shop1234")),
    )
    demo.addresses.append(
        Address(full_name="Jordan Taylor", phone="6145550123", line1="742 Maple Drive",
                line2="Apt 3B", landmark="Leave at the front desk",
                city="Columbus", state="Ohio", zip_code="43215", is_default=True)
    )  # fmt: skip
    demo.addresses.append(
        Address(full_name="Jordan Taylor", phone="6145550123", line1="500 Commerce Street",
                line2="Suite 400", city="Columbus", state="Ohio", zip_code="43215",
                kind="work")
    )  # fmt: skip
    db.add_all([admin, demo])
    customers = [_make_user(rng, i) for i in range(90)]
    db.add_all(customers)

    # Coupons
    db.add_all([
        Coupon(code="WELCOME10", description="10% off your order, up to $15", kind="percent",
               value=10, min_order=25, max_discount=15),
        Coupon(code="FLAT10", description="Flat $10 off on orders above $75", kind="flat",
               value=10, min_order=75),
        Coupon(code="HOLIDAY20", description="20% off up to $50 on orders above $100",
               kind="percent", value=20, min_order=100, max_discount=50,
               expires_at=NOW + timedelta(days=12)),
        Coupon(code="SUMMER15", description="Summer sale (ended)", kind="percent", value=15,
               min_order=50, max_discount=20, is_active=False,
               expires_at=NOW - timedelta(days=60)),
    ])  # fmt: skip
    db.flush()

    _seed_orders(db, rng, [*customers, demo], products)
    db.flush()
    for p in products:
        refresh_rating(db, p)
    db.commit()


def run(reset: bool = False) -> bool:
    """Create tables and seed if empty (or after ``reset``). Returns True if it seeded."""
    engine = dbmod.engine()
    if reset:
        dbmod.Base.metadata.drop_all(engine)
    dbmod.create_all()
    with dbmod.SessionLocal() as db:
        if db.scalar(select(func.count(Product.id))):
            return False
        seed(db)
    return True


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Seed the Northcart demo store database.")
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    args = parser.parse_args()
    seeded = run(reset=args.reset)
    with dbmod.SessionLocal() as db:
        counts = {
            "products": db.scalar(select(func.count(Product.id))),
            "reviews": db.scalar(select(func.count(Review.id))),
            "orders": db.scalar(select(func.count(Order.id))),
            "customers": db.scalar(select(func.count(User.id))),
        }
    print(
        ("Seeded" if seeded else "Already seeded")
        + ": "
        + ", ".join(f"{v} {k}" for k, v in counts.items())
    )


if __name__ == "__main__":
    main()
