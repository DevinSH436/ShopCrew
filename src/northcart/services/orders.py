"""Placing orders, the status lifecycle, and delivery estimates."""

from __future__ import annotations

import random
import string
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from northcart.models import (
    ORDER_FLOW,
    ORDER_STATUS_LABELS,
    PAYMENT_METHODS,
    Address,
    Order,
    OrderEvent,
    OrderItem,
    Product,
    User,
)
from northcart.services import cart as cart_svc

COURIERS = ["Delhivery", "Blue Dart", "Ekart", "XpressBees", "Shadowfax"]

# First digit of an Indian PIN code -> postal region. Metro-heavy regions ship faster.
_REGION_DAYS = {"1": 3, "2": 4, "3": 4, "4": 2, "5": 3, "6": 3, "7": 5, "8": 5, "9": 6}
_METRO_PREFIXES = ("110", "400", "560", "600", "700", "500", "411", "380", "122", "201")

# Which statuses an admin may move an order to from its current status.
TRANSITIONS: dict[str, list[str]] = {
    "placed": ["confirmed", "cancelled"],
    "confirmed": ["packed", "cancelled"],
    "packed": ["shipped", "cancelled"],
    "shipped": ["out_for_delivery"],
    "out_for_delivery": ["delivered"],
    "delivered": ["return_requested"],
    "return_requested": ["returned", "delivered"],
    "cancelled": [],
    "returned": [],
}


class OrderError(ValueError):
    """An order action that cannot be performed, with a customer-facing message."""


def valid_pincode(pincode: str) -> bool:
    """Indian PIN codes are 6 digits and never start with 0."""
    return len(pincode) == 6 and pincode.isdigit() and pincode[0] != "0"


def delivery_days(pincode: str) -> int:
    """Estimated business days to deliver to ``pincode``."""
    if pincode.startswith(_METRO_PREFIXES):
        return 2
    return _REGION_DAYS.get(pincode[:1], 5)


def delivery_estimate(pincode: str, start: datetime | None = None) -> datetime:
    """Expected delivery date, skipping Sundays."""
    day = (start or datetime.now(UTC)).replace(hour=0, minute=0, second=0, microsecond=0)
    remaining = delivery_days(pincode)
    while remaining > 0:
        day += timedelta(days=1)
        if day.weekday() != 6:
            remaining -= 1
    return day


def new_order_number(db: Session, when: datetime | None = None) -> str:
    """Order number like ``HT-2611-482193`` (year, month, random)."""
    when = when or datetime.now(UTC)
    while True:
        number = f"HT-{when:%y%m}-" + "".join(random.choices(string.digits, k=6))
        if db.scalar(select(Order.id).where(Order.number == number)) is None:
            return number


def add_event(order: Order, status: str, note: str = "", at: datetime | None = None) -> None:
    """Append a timeline entry and set the order's status."""
    order.status = status
    order.events.append(
        OrderEvent(
            status=status,
            note=note or ORDER_STATUS_LABELS.get(status, status),
            created_at=at or datetime.now(UTC),
        )
    )


def place_order(
    db: Session,
    user: User,
    address: Address,
    payment_method: str,
    coupon_code: str = "",
) -> Order:
    """Turn the user's cart into an order, reserve stock and clear the cart.

    Payment is simulated: online methods are marked paid immediately with a fake
    gateway reference; cash on delivery stays pending until delivery.
    """
    if payment_method not in PAYMENT_METHODS:
        raise OrderError("Please choose a payment method.")
    if address.user_id != user.id:
        raise OrderError("Please choose one of your saved addresses.")
    owner = cart_svc.CartOwner(user_id=user.id)
    summary = cart_svc.summarize(db, owner, coupon_code, payment_method)
    if not summary.lines:
        raise OrderError("Your cart is empty.")
    if summary.coupon_error:
        raise OrderError(summary.coupon_error)
    for line in summary.lines:
        product = db.get(Product, line.product_id, with_for_update=True)
        if product is None or not product.is_active:
            raise OrderError(f"{line.product.name} is no longer available.")
        if product.stock < line.quantity:
            raise OrderError(
                f"Only {product.stock} left of {product.name}. Please update your cart."
            )

    now = datetime.now(UTC)
    online = payment_method != "cod"
    order = Order(
        number=new_order_number(db, now),
        user_id=user.id,
        payment_method=payment_method,
        payment_status="paid" if online else "pending",
        payment_ref=("pay_" + "".join(random.choices(string.ascii_letters + string.digits, k=14)))
        if online
        else "",
        subtotal=summary.subtotal,
        mrp_total=summary.mrp_total,
        discount=summary.coupon_discount,
        coupon_code=summary.coupon.code if summary.coupon else "",
        shipping_fee=summary.shipping_fee,
        cod_fee=summary.cod_fee,
        total=summary.total,
        ship_name=address.full_name,
        ship_phone=address.phone,
        ship_line1=address.line1,
        ship_line2=", ".join(p for p in [address.line2, address.landmark] if p),
        ship_city=address.city,
        ship_state=address.state,
        ship_pincode=address.pincode,
        expected_delivery=delivery_estimate(address.pincode, now),
        created_at=now,
    )
    for line in summary.lines:
        product = line.product
        order.items.append(
            OrderItem(
                product_id=product.id,
                name=product.name,
                sku=product.sku,
                price=product.price,
                mrp=product.mrp,
                quantity=line.quantity,
            )
        )
        product.stock -= line.quantity
        product.sold_count += line.quantity
    if summary.coupon:
        summary.coupon.used_count += 1
    note = "Payment received" if online else "Pay on delivery"
    add_event(order, "placed", f"Order placed. {note} via {PAYMENT_METHODS[payment_method]}.", now)
    db.add(order)
    db.commit()
    cart_svc.clear(db, owner)
    return order


def set_status(db: Session, order: Order, status: str, note: str = "") -> None:
    """Move an order to ``status`` (admin action), enforcing allowed transitions."""
    if status not in TRANSITIONS.get(order.status, []):
        current = ORDER_STATUS_LABELS.get(order.status, order.status)
        raise OrderError(f"Can't move an order from '{current}' to '{status}'.")
    now = datetime.now(UTC)
    if status == "shipped" and not order.tracking_number:
        order.courier = order.courier or random.choice(COURIERS)
        order.tracking_number = "".join(random.choices(string.digits, k=12))
        note = note or f"Shipped with {order.courier}. AWB {order.tracking_number}."
    if status == "delivered":
        order.delivered_at = now
        if order.payment_method == "cod":
            order.payment_status = "paid"
    if status == "cancelled":
        _restock(order)
        if order.payment_status == "paid":
            order.payment_status = "refunded"
            note = note or "Order cancelled. Refund initiated to the original payment method."
    if status == "returned":
        _restock(order)
        order.payment_status = "refunded"
        note = note or "Return received. Refund initiated."
    add_event(order, status, note, now)
    db.commit()


def _restock(order: Order) -> None:
    for item in order.items:
        if item.product is not None:
            item.product.stock += item.quantity
            item.product.sold_count = max(0, item.product.sold_count - item.quantity)


def cancel_by_customer(db: Session, order: Order, reason: str = "") -> None:
    """Customer-initiated cancellation (only before shipping)."""
    if not order.can_cancel:
        raise OrderError("This order has already shipped and can no longer be cancelled.")
    set_status(db, order, "cancelled", f"Cancelled by customer. {reason}".strip())


def request_return(db: Session, order: Order, reason: str, window_days: int) -> None:
    """Customer return request, allowed within the return window after delivery."""
    if order.status != "delivered" or order.delivered_at is None:
        raise OrderError("Only delivered orders can be returned.")
    delivered = order.delivered_at
    if delivered.tzinfo is None:
        delivered = delivered.replace(tzinfo=UTC)
    if datetime.now(UTC) - delivered > timedelta(days=window_days):
        raise OrderError(f"The {window_days}-day return window for this order has closed.")
    set_status(db, order, "return_requested", f"Return requested: {reason or 'no reason given'}")


def progress_steps(order: Order) -> list[dict]:
    """Tracking timeline for templates: each happy-path step with done/current flags."""
    reached = {e.status: e for e in order.events}
    if order.status in {"cancelled", "return_requested", "returned"}:
        flow = [s for s in ORDER_FLOW if s in reached] + [order.status]
    else:
        flow = ORDER_FLOW
    steps = []
    for status in flow:
        event = reached.get(status)
        steps.append(
            {
                "status": status,
                "label": ORDER_STATUS_LABELS[status],
                "done": event is not None,
                "current": status == order.status,
                "at": event.created_at if event else None,
                "note": event.note if event else "",
            }
        )
    return steps
