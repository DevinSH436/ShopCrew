"""Admin dashboard and report numbers. All grouping is by the store's date (US Eastern)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from northcart.models import Category, Order, OrderItem, Product, Review, User

STORE_TZ = ZoneInfo("America/New_York")
LOST_STATUSES = ("cancelled", "returned")
# State sales tax rates (percent, statewide base rate; local add-ons ignored in this demo).
STATE_TAX_RATES: dict[str, float] = {
    "Alabama": 4, "Alaska": 0, "Arizona": 5.6, "Arkansas": 6.5, "California": 7.25,
    "Colorado": 2.9, "Connecticut": 6.35, "Delaware": 0, "District of Columbia": 6,
    "Florida": 6, "Georgia": 4, "Hawaii": 4, "Idaho": 6, "Illinois": 6.25, "Indiana": 7,
    "Iowa": 6, "Kansas": 6.5, "Kentucky": 6, "Louisiana": 5, "Maine": 5.5, "Maryland": 6,
    "Massachusetts": 6.25, "Michigan": 6, "Minnesota": 6.875, "Mississippi": 7,
    "Missouri": 4.225, "Montana": 0, "Nebraska": 5.5, "Nevada": 6.85, "New Hampshire": 0,
    "New Jersey": 6.625, "New Mexico": 4.875, "New York": 4, "North Carolina": 4.75,
    "North Dakota": 5, "Ohio": 5.75, "Oklahoma": 4.5, "Oregon": 0, "Pennsylvania": 6,
    "Rhode Island": 7, "South Carolina": 6, "South Dakota": 4.2, "Tennessee": 7, "Texas": 6.25,
    "Utah": 6.1, "Vermont": 6, "Virginia": 5.3, "Washington": 6.5, "West Virginia": 6,
    "Wisconsin": 5, "Wyoming": 4,
}  # fmt: skip


def aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; stored values are UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def ist_date(value: datetime) -> date:
    """Store-calendar (US Eastern) date of a stored timestamp."""
    return aware(value).astimezone(STORE_TZ).date()  # type: ignore[union-attr]


def period_bounds(days: int, now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    """(previous period start, current period start, now) for a rolling window of ``days``."""
    now = now or datetime.now(UTC)
    today_ist = now.astimezone(STORE_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (today_ist - timedelta(days=days - 1)).astimezone(UTC)
    prev = start - timedelta(days=days)
    return prev, start, now


def _orders_between(db: Session, start: datetime, end: datetime) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .where(Order.created_at >= start, Order.created_at <= end)
            .options(selectinload(Order.items))
        )
    )


def _pct(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return round((cur - prev) * 100 / prev, 1)


def _summarise(orders: list[Order]) -> dict[str, float]:
    valid = [o for o in orders if o.status not in LOST_STATUSES]
    revenue = sum(o.total for o in valid)
    return {
        "revenue": revenue,
        "orders": len(valid),
        "aov": round(revenue / len(valid)) if valid else 0,
        "units": sum(i.quantity for o in valid for i in o.items),
        "cancelled": len(orders) - len(valid),
    }


def kpis(db: Session, days: int = 30) -> dict[str, dict[str, Any]]:
    """Headline numbers for the period, each with a % change vs the previous period."""
    prev_start, start, now = period_bounds(days)
    cur = _summarise(_orders_between(db, start, now))
    prev = _summarise(_orders_between(db, prev_start, start))
    new_cur = db.scalar(select(func.count(User.id)).where(User.created_at >= start)) or 0
    new_prev = (
        db.scalar(
            select(func.count(User.id)).where(
                User.created_at >= prev_start, User.created_at < start
            )
        )
        or 0
    )
    cur["customers"], prev["customers"] = new_cur, new_prev
    return {
        key: {"value": cur[key], "prev": prev[key], "delta": _pct(cur[key], prev[key])}
        for key in ("revenue", "orders", "aov", "units", "customers", "cancelled")
    }


def revenue_by_day(db: Session, days: int = 30) -> dict[str, list]:
    """Daily revenue and order counts (STORE_TZ days), zero-filled."""
    _, start, now = period_bounds(days)
    labels = [(start.astimezone(STORE_TZ).date() + timedelta(days=i)) for i in range(days)]
    revenue = dict.fromkeys(labels, 0)
    orders = dict.fromkeys(labels, 0)
    for o in _orders_between(db, start, now):
        d = ist_date(o.created_at)
        if d in revenue and o.status not in LOST_STATUSES:
            revenue[d] += o.total
            orders[d] += 1
    return {
        "labels": [d.strftime("%b %d") for d in labels],
        "revenue": list(revenue.values()),
        "orders": list(orders.values()),
    }


def orders_by_status(db: Session, days: int | None = None) -> dict[str, int]:
    """Order counts per status (optionally limited to the last ``days``)."""
    stmt = select(Order.status, func.count(Order.id)).group_by(Order.status)
    if days:
        stmt = stmt.where(Order.created_at >= period_bounds(days)[1])
    return {s: n for s, n in db.execute(stmt).all()}


def _valid_items(db: Session, start: datetime, end: datetime):  # type: ignore[no-untyped-def]
    return (
        select(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            Order.created_at >= start,
            Order.created_at <= end,
            Order.status.not_in(LOST_STATUSES),
        )
    )


def top_products(
    db: Session,
    days: int = 30,
    limit: int = 8,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Best sellers by revenue."""
    if start is None:
        _, start, end = period_bounds(days)
    end = end or datetime.now(UTC)
    sub = _valid_items(db, start, end).subquery()
    rows = db.execute(
        select(
            sub.c.product_id,
            sub.c.name,
            func.sum(sub.c.quantity).label("units"),
            func.sum(sub.c.quantity * sub.c.price).label("revenue"),
        )
        .group_by(sub.c.product_id, sub.c.name)
        .order_by(func.sum(sub.c.quantity * sub.c.price).desc())
        .limit(limit)
    ).all()
    out = []
    for pid, name, units, revenue in rows:
        product = db.get(Product, pid) if pid else None
        out.append({"product": product, "name": name, "units": int(units), "revenue": int(revenue)})
    return out


def sales_by_category(
    db: Session, days: int = 30, start: datetime | None = None, end: datetime | None = None
) -> list[dict[str, Any]]:
    """Revenue and units per category."""
    if start is None:
        _, start, end = period_bounds(days)
    end = end or datetime.now(UTC)
    sub = _valid_items(db, start, end).subquery()
    rows = db.execute(
        select(
            Category.name,
            func.sum(sub.c.quantity).label("units"),
            func.sum(sub.c.quantity * sub.c.price).label("revenue"),
        )
        .join(Product, Product.id == sub.c.product_id)
        .join(Category, Category.id == Product.category_id)
        .group_by(Category.name)
        .order_by(func.sum(sub.c.quantity * sub.c.price).desc())
    ).all()
    return [{"name": n, "units": int(u), "revenue": int(r)} for n, u, r in rows]


def payment_method_split(db: Session, days: int = 30) -> dict[str, int]:
    """Order counts by payment method."""
    start = period_bounds(days)[1]
    rows = db.execute(
        select(Order.payment_method, func.count(Order.id))
        .where(Order.created_at >= start, Order.status.not_in(LOST_STATUSES))
        .group_by(Order.payment_method)
    ).all()
    return {m: n for m, n in rows}


def low_stock(db: Session, limit: int = 10) -> list[Product]:
    """Active products at or below their low-stock threshold (out of stock first)."""
    return list(
        db.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.stock <= Product.low_stock_threshold)
            .order_by(Product.stock.asc())
            .limit(limit)
        )
    )


def recent_orders(db: Session, n: int = 8) -> list[Order]:
    """Latest orders."""
    return list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(n)
        )
    )


def reviews_needing_attention(db: Session, n: int = 5) -> list[Review]:
    """Latest published 1-2 star reviews."""
    return list(
        db.scalars(
            select(Review)
            .where(Review.rating <= 2, Review.status == "published")
            .options(selectinload(Review.product))
            .order_by(Review.created_at.desc())
            .limit(n)
        )
    )


def sales_report(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    """Day-by-day sales for a date range plus category and product breakdowns."""
    days: dict[date, dict[str, int]] = defaultdict(
        lambda: {"orders": 0, "units": 0, "gross": 0, "discount": 0, "shipping": 0, "net": 0}
    )
    for o in _orders_between(db, start, end):
        if o.status in LOST_STATUSES:
            continue
        row = days[ist_date(o.created_at)]
        row["orders"] += 1
        row["units"] += sum(i.quantity for i in o.items)
        row["gross"] += o.subtotal
        row["discount"] += o.discount
        row["shipping"] += o.shipping_fee + o.cod_fee
        row["net"] += o.total
    rows = [{"date": d, **v} for d, v in sorted(days.items())]
    totals = {k: sum(r[k] for r in rows) for k in ("orders", "units", "gross", "discount",
                                                   "shipping", "net")}  # fmt: skip
    return {
        "rows": rows,
        "totals": totals,
        "categories": sales_by_category(db, start=start, end=end),
        "products": top_products(db, start=start, end=end, limit=50),
    }


def tax_rate(state: str) -> float:
    """Sales tax rate (percent) for a US state; unknown states are taxed at 0%."""
    return STATE_TAX_RATES.get(state.strip(), 0.0)


def split_tax(amount: int, state: str) -> dict[str, float]:
    """Split a tax-inclusive amount into the pre-tax value and the state sales tax."""
    rate = tax_rate(state)
    taxable = round(amount * 100 / (100 + rate), 2)
    return {"taxable": taxable, "tax": round(amount - taxable, 2), "rate": rate}


def tax_summary(db: Session) -> list[dict[str, Any]]:
    """Monthly sales tax summary for delivered orders (by delivery month)."""
    months: dict[str, dict[str, float]] = defaultdict(
        lambda: {"orders": 0, "gross": 0, "taxable": 0.0, "tax": 0.0}
    )
    for o in db.scalars(select(Order).where(Order.status == "delivered")):
        when = aware(o.delivered_at or o.created_at).astimezone(STORE_TZ)  # type: ignore[union-attr]
        m = months[when.strftime("%Y-%m")]
        t = split_tax(o.total, o.ship_state)
        m["orders"] += 1
        m["gross"] += o.total
        m["taxable"] += t["taxable"]
        m["tax"] += t["tax"]
    return [
        {
            "month": datetime.strptime(k, "%Y-%m").strftime("%b %Y"),
            **{kk: (round(v, 2) if isinstance(v, float) else v) for kk, v in m.items()},
        }
        for k, m in sorted(months.items(), reverse=True)
    ]
