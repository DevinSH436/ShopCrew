"""Database tables for the store. Money is stored as whole US dollars (tax inclusive)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from northcart.db import Base


def utcnow() -> datetime:
    """Timezone-aware 'now' used for every timestamp column."""
    return datetime.now(UTC)


# Order lifecycle, in the order a happy-path order moves through it.
ORDER_FLOW = ["placed", "confirmed", "packed", "shipped", "out_for_delivery", "delivered"]
ORDER_STATUSES = [*ORDER_FLOW, "cancelled", "return_requested", "returned"]
ORDER_STATUS_LABELS = {
    "placed": "Order placed",
    "confirmed": "Confirmed",
    "packed": "Packed",
    "shipped": "Shipped",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "return_requested": "Return requested",
    "returned": "Returned",
}
PAYMENT_METHODS = {
    "card": "Credit / Debit card",
    "paypal": "PayPal",
    "bank": "Bank account (ACH)",
    "cod": "Pay on delivery",
}


class User(Base):
    """A customer or staff account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    addresses: Mapped[list[Address]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="Address.id"
    )
    orders: Mapped[list[Order]] = relationship(
        back_populates="user", order_by="Order.created_at.desc()"
    )

    @property
    def first_name(self) -> str:
        """First word of the name, for greetings."""
        return (self.name or "there").split()[0]


class Address(Base):
    """A saved delivery address."""

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str] = mapped_column(String(200), default="")
    landmark: Mapped[str] = mapped_column(String(120), default="")
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    zip_code: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10), default="home")  # home / work
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="addresses")

    def one_line(self) -> str:
        """Address on a single line."""
        parts = [self.line1, self.line2, self.landmark, self.city, f"{self.state} {self.zip_code}"]
        return ", ".join(p for p in parts if p)


class Category(Base):
    """A product category (one level of nesting is enough for this store)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    icon: Mapped[str] = mapped_column(String(40), default="box")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)

    products: Mapped[list[Product]] = relationship(back_populates="category")


class Product(Base):
    """A sellable item."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(80), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    price: Mapped[int] = mapped_column(Integer)
    mrp: Mapped[int] = mapped_column(Integer)
    cost_price: Mapped[int] = mapped_column(Integer, default=0)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=10)
    short_description: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    highlights: Mapped[list[str]] = mapped_column(JSON, default=list)
    specs: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Generated artwork: which drawing and which color to use when no photo is uploaded.
    art_kind: Mapped[str] = mapped_column(String(30), default="box")
    color: Mapped[str] = mapped_column(String(9), default="#4f46e5")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    # SEO fields (the ShopCrew SEO Writer can fill these in).
    seo_title: Mapped[str] = mapped_column(String(70), default="")
    seo_meta: Mapped[str] = mapped_column(String(160), default="")
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    # "Customers say": AI summary of reviews, written by the Review Analyst.
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_praises: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_complaints: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Denormalised review stats, refreshed whenever reviews change.
    rating_avg: Mapped[float] = mapped_column(Float, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    category: Mapped[Category] = relationship(back_populates="products")
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order"
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    competitor_prices: Mapped[list[CompetitorPrice]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    @property
    def discount_pct(self) -> int:
        """Percent off MRP, rounded down."""
        if not self.mrp or self.mrp <= self.price:
            return 0
        return int((self.mrp - self.price) * 100 / self.mrp)

    @property
    def in_stock(self) -> bool:
        """True if at least one unit can be sold."""
        return self.stock > 0

    @property
    def is_low_stock(self) -> bool:
        """True if stock is positive but at or below the threshold."""
        return 0 < self.stock <= self.low_stock_threshold

    @property
    def image_urls(self) -> list[str]:
        """Uploaded photos if any, else the generated artwork views."""
        if self.images:
            return [f"/media/{img.path}" for img in self.images]
        return [f"/art/{self.slug}.svg?v={v}" for v in range(4)]

    @property
    def thumb(self) -> str:
        """Main image URL."""
        return self.image_urls[0]


class ProductImage(Base):
    """An uploaded product photo stored under ``media/``."""

    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(255))
    alt: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="images")


class Review(Base):
    """A customer review."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(80))
    author_city: Mapped[str] = mapped_column(String(60), default="")
    rating: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120), default="")
    body: Mapped[str] = mapped_column(Text)
    verified_purchase: Mapped[bool] = mapped_column(Boolean, default=False)
    helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="published")  # published/hidden
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="reviews")


class CompetitorPrice(Base):
    """A competitor's listing price, used by the ShopCrew Price Tracker."""

    __tablename__ = "competitor_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    competitor: Mapped[str] = mapped_column(String(80))
    price: Mapped[int] = mapped_column(Integer)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="competitor_prices")


class CartItem(Base):
    """A line in a cart. Guests are keyed by session, signed-in users by user id."""

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),
        UniqueConstraint("session_key", "product_id", name="uq_cart_session_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    session_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    saved_for_later: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship()


class WishlistItem(Base):
    """A product a user saved to their wishlist."""

    __tablename__ = "wishlist_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_wishlist"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship()


class Coupon(Base):
    """A discount code."""

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(10), default="percent")  # percent / flat
    value: Mapped[int] = mapped_column(Integer)
    min_order: Mapped[int] = mapped_column(Integer, default=0)
    max_discount: Mapped[int] = mapped_column(Integer, default=0)  # 0 = no cap
    usage_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    """A placed order, with the delivery address and prices frozen at checkout time."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="placed", index=True)
    payment_method: Mapped[str] = mapped_column(String(12))
    payment_status: Mapped[str] = mapped_column(String(12), default="pending")
    payment_ref: Mapped[str] = mapped_column(String(40), default="")
    subtotal: Mapped[int] = mapped_column(Integer)
    mrp_total: Mapped[int] = mapped_column(Integer, default=0)
    discount: Mapped[int] = mapped_column(Integer, default=0)
    coupon_code: Mapped[str] = mapped_column(String(30), default="")
    shipping_fee: Mapped[int] = mapped_column(Integer, default=0)
    cod_fee: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    ship_name: Mapped[str] = mapped_column(String(120))
    ship_phone: Mapped[str] = mapped_column(String(20))
    ship_line1: Mapped[str] = mapped_column(String(200))
    ship_line2: Mapped[str] = mapped_column(String(200), default="")
    ship_city: Mapped[str] = mapped_column(String(80))
    ship_state: Mapped[str] = mapped_column(String(80))
    ship_zip: Mapped[str] = mapped_column(String(10))
    courier: Mapped[str] = mapped_column(String(60), default="")
    tracking_number: Mapped[str] = mapped_column(String(40), default="")
    expected_delivery: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderEvent.created_at"
    )

    @property
    def status_label(self) -> str:
        """Human label for ``status``."""
        return ORDER_STATUS_LABELS.get(self.status, self.status.title())

    @property
    def payment_label(self) -> str:
        """Human label for ``payment_method``."""
        return PAYMENT_METHODS.get(self.payment_method, self.payment_method)

    @property
    def item_count(self) -> int:
        """Total units in the order."""
        return sum(i.quantity for i in self.items)

    @property
    def can_cancel(self) -> bool:
        """Customers can cancel until the parcel ships."""
        return self.status in {"placed", "confirmed", "packed"}

    @property
    def ship_address(self) -> str:
        """Delivery address on one line."""
        parts = [self.ship_line1, self.ship_line2, self.ship_city]
        return ", ".join(p for p in parts if p) + f", {self.ship_state} {self.ship_zip}"


class OrderItem(Base):
    """A line in an order. Name and price are copied so later product edits don't change it."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(40))
    price: Mapped[int] = mapped_column(Integer)
    mrp: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()

    @property
    def line_total(self) -> int:
        """Price x quantity."""
        return self.price * self.quantity


class OrderEvent(Base):
    """One step in an order's tracking timeline."""

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="events")


class Setting(Base):
    """Key/value store settings editable from the admin panel."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class CrewRun(Base):
    """One ShopCrew run started from the admin panel."""

    __tablename__ = "crew_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued/running/done/failed
    process: Mapped[str] = mapped_column(String(16), default="sequential")
    model: Mapped[str] = mapped_column(String(80), default="")
    stages_done: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_stage: Mapped[str] = mapped_column(String(30), default="")
    log: Mapped[list[str]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    out_dir: Mapped[str] = mapped_column(String(300), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    applied: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship()
