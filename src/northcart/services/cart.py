"""Shopping cart: owner resolution, line edits, coupon maths and the price summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from northcart.config import get_settings
from northcart.models import CartItem, Coupon, Product

MAX_QTY_PER_LINE = 10


class CartError(ValueError):
    """A cart action the customer should be told about (out of stock, bad coupon...)."""


@dataclass(frozen=True)
class CartOwner:
    """Who a cart belongs to: a signed-in user or a guest session."""

    user_id: int | None = None
    session_key: str | None = None

    def clause(self):  # type: ignore[no-untyped-def]
        """SQL filter selecting this owner's rows."""
        if self.user_id is not None:
            return CartItem.user_id == self.user_id
        return CartItem.session_key == (self.session_key or "-")


@dataclass
class CartSummary:
    """Prices for a cart (or for checkout), all in whole dollars."""

    lines: list[CartItem] = field(default_factory=list)
    saved: list[CartItem] = field(default_factory=list)
    item_count: int = 0
    mrp_total: int = 0
    subtotal: int = 0
    coupon: Coupon | None = None
    coupon_discount: int = 0
    coupon_error: str = ""
    shipping_fee: int = 0
    cod_fee: int = 0
    total: int = 0
    free_shipping_gap: int = 0

    @property
    def savings(self) -> int:
        """Total saved vs MRP, including the coupon."""
        return self.mrp_total - self.subtotal + self.coupon_discount

    @property
    def has_unavailable(self) -> bool:
        """True if any line exceeds current stock."""
        return any(line.quantity > line.product.stock for line in self.lines)


def _lines(db: Session, owner: CartOwner, saved: bool) -> list[CartItem]:
    return list(
        db.scalars(
            select(CartItem)
            .where(owner.clause(), CartItem.saved_for_later.is_(saved))
            .options(selectinload(CartItem.product).selectinload(Product.images))
            .order_by(CartItem.created_at.desc(), CartItem.id.desc())
        )
    )


def count(db: Session, owner: CartOwner) -> int:
    """Units in the active cart (for the header badge)."""
    return sum(line.quantity for line in _lines(db, owner, saved=False))


def add(db: Session, owner: CartOwner, product_id: int, quantity: int = 1) -> CartItem:
    """Add ``quantity`` of a product, merging with an existing line."""
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise CartError("This product is no longer available.")
    if product.stock <= 0:
        raise CartError(f"{product.name} is out of stock.")
    line = db.scalar(select(CartItem).where(owner.clause(), CartItem.product_id == product_id))
    if line is None:
        line = CartItem(
            user_id=owner.user_id,
            session_key=None if owner.user_id else owner.session_key,
            product_id=product_id,
            quantity=0,
        )
        db.add(line)
    line.saved_for_later = False
    line.quantity = min(line.quantity + max(1, quantity), MAX_QTY_PER_LINE, product.stock)
    db.commit()
    return line


def _owned_line(db: Session, owner: CartOwner, line_id: int) -> CartItem:
    line = db.scalar(select(CartItem).where(owner.clause(), CartItem.id == line_id))
    if line is None:
        raise CartError("That item is no longer in your cart.")
    return line


def set_quantity(db: Session, owner: CartOwner, line_id: int, quantity: int) -> None:
    """Change a line's quantity; zero removes it."""
    line = _owned_line(db, owner, line_id)
    if quantity <= 0:
        db.delete(line)
    else:
        line.quantity = min(quantity, MAX_QTY_PER_LINE, max(1, line.product.stock))
    db.commit()


def remove(db: Session, owner: CartOwner, line_id: int) -> None:
    """Delete a line."""
    db.delete(_owned_line(db, owner, line_id))
    db.commit()


def toggle_saved(db: Session, owner: CartOwner, line_id: int) -> None:
    """Move a line between the cart and 'Saved for later'."""
    line = _owned_line(db, owner, line_id)
    line.saved_for_later = not line.saved_for_later
    db.commit()


def clear(db: Session, owner: CartOwner) -> None:
    """Empty the active cart (after an order is placed)."""
    db.execute(delete(CartItem).where(owner.clause(), CartItem.saved_for_later.is_(False)))
    db.commit()


def merge_guest_cart(db: Session, session_key: str, user_id: int) -> None:
    """On sign-in, move a guest's lines into the user's cart."""
    guest = CartOwner(session_key=session_key)
    user = CartOwner(user_id=user_id)
    for line in _lines(db, guest, saved=False) + _lines(db, guest, saved=True):
        existing = db.scalar(
            select(CartItem).where(user.clause(), CartItem.product_id == line.product_id)
        )
        if existing:
            existing.quantity = min(existing.quantity + line.quantity, MAX_QTY_PER_LINE)
            db.delete(line)
        else:
            line.user_id = user_id
            line.session_key = None
    db.commit()


def find_coupon(db: Session, code: str) -> Coupon | None:
    """Look a coupon up by code (case-insensitive)."""
    return db.scalar(select(Coupon).where(Coupon.code == code.strip().upper()))


def coupon_discount(coupon: Coupon, subtotal: int) -> int:
    """Discount a coupon gives on ``subtotal``, or raise ``CartError`` explaining why not."""
    if not coupon.is_active:
        raise CartError(f"{coupon.code} is no longer active.")
    expires = coupon.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            raise CartError(f"{coupon.code} has expired.")
    if coupon.usage_limit and coupon.used_count >= coupon.usage_limit:
        raise CartError(f"{coupon.code} has reached its usage limit.")
    if subtotal < coupon.min_order:
        raise CartError(f"Add ${coupon.min_order - subtotal:,} more to use {coupon.code}.")
    if coupon.kind == "percent":
        amount = subtotal * coupon.value // 100
        if coupon.max_discount:
            amount = min(amount, coupon.max_discount)
    else:
        amount = coupon.value
    return min(amount, subtotal)


def summarize(
    db: Session,
    owner: CartOwner,
    coupon_code: str = "",
    payment_method: str = "",
) -> CartSummary:
    """Build the full price breakdown for the owner's cart."""
    settings = get_settings()
    s = CartSummary(lines=_lines(db, owner, False), saved=_lines(db, owner, True))
    for line in s.lines:
        s.item_count += line.quantity
        s.mrp_total += line.product.mrp * line.quantity
        s.subtotal += line.product.price * line.quantity
    if coupon_code:
        coupon = find_coupon(db, coupon_code)
        if coupon is None:
            s.coupon_error = f"'{coupon_code.upper()}' is not a valid coupon."
        else:
            try:
                s.coupon_discount = coupon_discount(coupon, s.subtotal)
                s.coupon = coupon
            except CartError as err:
                s.coupon_error = str(err)
    after_coupon = s.subtotal - s.coupon_discount
    if s.lines and after_coupon < settings.free_shipping_threshold:
        s.shipping_fee = settings.shipping_fee
        s.free_shipping_gap = settings.free_shipping_threshold - after_coupon
    if payment_method == "cod":
        s.cod_fee = settings.cod_fee
    s.total = after_coupon + s.shipping_fee + s.cod_fee
    return s
