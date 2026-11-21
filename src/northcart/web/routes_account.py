"""Sign in / register, account pages, orders, addresses, wishlist and reviews."""

# FastAPI's Depends()/Query() defaults are the framework idiom.

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from northcart.catalog_data import INDIAN_STATES
from northcart.config import get_settings
from northcart.db import get_db
from northcart.models import (
    Address,
    Order,
    OrderItem,
    Product,
    Review,
    User,
    WishlistItem,
)
from northcart.security import hash_password, verify_password
from northcart.services import cart as cart_svc
from northcart.services import catalog
from northcart.services import orders as order_svc
from northcart.services import settings as settings_svc
from northcart.web.deps import current_user, flash, login, logout, require_user
from northcart.web.templating import render

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
CANCEL_REASONS = [
    "Ordered by mistake",
    "Found a better price elsewhere",
    "Delivery is taking too long",
    "Need to change the delivery address",
    "Other",
]
RETURN_REASONS = [
    "Item is defective or doesn't work",
    "Received a different item",
    "Item doesn't match the description",
    "Size or fit issue",
    "No longer needed",
]
IN_PROGRESS = ["placed", "confirmed", "packed", "shipped", "out_for_delivery", "return_requested"]


def is_fetch(request: Request) -> bool:
    """True for requests made by store.js (they expect JSON)."""
    return request.headers.get("x-requested-with") == "fetch"


def safe_next(url: str | None) -> str:
    """Only allow same-site relative redirects."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/"


def clean_phone(raw: str) -> str:
    """Strip spaces, dashes and a leading +91 / 0 from an Indian mobile number."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def _demo_login() -> dict[str, str]:
    return {
        "email": os.getenv("DEMO_CUSTOMER_EMAIL", "customer@northcart.test"),
        "password": os.getenv("DEMO_CUSTOMER_PASSWORD", "shop1234"),
    }


# ----------------------------------------------------------------------------- auth


@router.get("/login")
def login_page(
    request: Request,
    next: str = "/",
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Sign-in form."""
    if user:
        return RedirectResponse(safe_next(next), status_code=303)
    return render(
        request,
        db,
        "account/login.html",
        {"next": safe_next(next), "email": "", "error": "", "demo": _demo_login()},
    )


@router.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    """Check credentials, merge the guest cart and start a session."""
    form = await request.form()
    email = str(form.get("email") or "").strip().lower()
    password = str(form.get("password") or "")
    next_url = safe_next(str(form.get("next") or "/"))
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return render(
            request,
            db,
            "account/login.html",
            {
                "next": next_url,
                "email": email,
                "error": "That email and password don't match our records.",
                "demo": _demo_login(),
            },
            status_code=400,
        )
    guest_key = request.session.get("cart_key")
    if guest_key:
        cart_svc.merge_guest_cart(db, guest_key, user.id)
    login(request, user)
    flash(request, f"Welcome back, {user.first_name}!")
    if user.is_admin and next_url == "/":
        next_url = "/admin"
    return RedirectResponse(next_url, status_code=303)


@router.get("/register")
def register_page(
    request: Request,
    next: str = "/",
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Create-account form."""
    if user:
        return RedirectResponse("/account", status_code=303)
    return render(
        request, db, "account/register.html", {"next": safe_next(next), "values": {}, "errors": {}}
    )


@router.post("/register")
async def register_submit(request: Request, db: Session = Depends(get_db)):
    """Validate and create a customer account."""
    form = await request.form()
    values = {k: str(form.get(k) or "").strip() for k in ("name", "email", "phone")}
    values["email"] = values["email"].lower()
    password = str(form.get("password") or "")
    confirm = str(form.get("confirm") or "")
    next_url = safe_next(str(form.get("next") or "/"))
    errors: dict[str, str] = {}
    if len(values["name"]) < 2:
        errors["name"] = "Enter your name."
    if not EMAIL_RE.match(values["email"]):
        errors["email"] = "Enter a valid email address."
    elif db.scalar(select(User.id).where(func.lower(User.email) == values["email"])):
        errors["email"] = "An account with this email already exists. Sign in instead."
    phone = clean_phone(values["phone"])
    if not PHONE_RE.match(phone):
        errors["phone"] = "Enter a 10-digit Indian mobile number."
    if len(password) < 8:
        errors["password"] = "Use at least 8 characters."
    elif password != confirm:
        errors["confirm"] = "Passwords don't match."
    if errors:
        return render(
            request,
            db,
            "account/register.html",
            {"next": next_url, "values": values, "errors": errors},
            status_code=400,
        )
    user = User(
        email=values["email"],
        name=values["name"],
        phone=phone,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    guest_key = request.session.get("cart_key")
    if guest_key:
        cart_svc.merge_guest_cart(db, guest_key, user.id)
    login(request, user)
    flash(request, f"Welcome to {get_settings().store_name}, {user.first_name}! 🎉")
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
def logout_submit(request: Request) -> RedirectResponse:
    """End the session."""
    logout(request)
    flash(request, "You've been signed out.", "info")
    return RedirectResponse("/", status_code=303)


# ----------------------------------------------------------------------------- account


@router.get("/account")
def account_home(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Account dashboard."""
    recent = list(
        db.scalars(
            select(Order)
            .where(Order.user_id == user.id)
            .options(selectinload(Order.items).selectinload(OrderItem.product))
            .order_by(Order.created_at.desc())
            .limit(3)
        )
    )
    counts = {
        "orders": db.scalar(select(func.count(Order.id)).where(Order.user_id == user.id)) or 0,
        "wishlist": db.scalar(
            select(func.count(WishlistItem.id)).where(WishlistItem.user_id == user.id)
        )
        or 0,
        "addresses": len(user.addresses),
    }
    return render(request, db, "account/home.html", {"recent": recent, "counts": counts}, user=user)


@router.get("/account/profile")
def profile_page(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Login & security."""
    return render(request, db, "account/profile.html", {"errors": {}}, user=user)


@router.post("/account/profile")
async def profile_submit(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Update name/phone, or change password."""
    form = await request.form()
    errors: dict[str, str] = {}
    if form.get("action") == "password":
        current = str(form.get("current") or "")
        new = str(form.get("new") or "")
        if not verify_password(current, user.password_hash):
            errors["current"] = "Your current password is incorrect."
        elif len(new) < 8:
            errors["new"] = "Use at least 8 characters."
        elif new != str(form.get("confirm") or ""):
            errors["confirm"] = "Passwords don't match."
        if not errors:
            user.password_hash = hash_password(new)
            db.commit()
            flash(request, "Your password has been changed.")
            return RedirectResponse("/account/profile", status_code=303)
    else:
        name = str(form.get("name") or "").strip()
        phone = clean_phone(str(form.get("phone") or ""))
        if len(name) < 2:
            errors["name"] = "Enter your name."
        if not PHONE_RE.match(phone):
            errors["phone"] = "Enter a 10-digit Indian mobile number."
        if not errors:
            user.name, user.phone = name, phone
            db.commit()
            flash(request, "Profile updated.")
            return RedirectResponse("/account/profile", status_code=303)
    return render(
        request, db, "account/profile.html", {"errors": errors}, user=user, status_code=400
    )


# ----------------------------------------------------------------------------- orders


def _own_order(db: Session, user: User, number: str) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.number == number, Order.user_id == user.id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.images),
            selectinload(Order.events),
        )
    )
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


def can_return(order: Order) -> bool:
    """Delivered and still inside the return window."""
    if order.status != "delivered" or order.delivered_at is None:
        return False
    delivered = order.delivered_at
    if delivered.tzinfo is None:
        delivered = delivered.replace(tzinfo=UTC)
    window = timedelta(days=get_settings().return_window_days)
    return datetime.now(UTC) - delivered <= window


@router.get("/account/orders")
def orders_page(
    request: Request,
    status: str = "all",
    q: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Order history."""
    stmt = select(Order).where(Order.user_id == user.id)
    if status == "progress":
        stmt = stmt.where(Order.status.in_(IN_PROGRESS))
    elif status == "delivered":
        stmt = stmt.where(Order.status == "delivered")
    elif status == "cancelled":
        stmt = stmt.where(Order.status.in_(["cancelled", "returned"]))
    q = q.strip()
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Order.number).like(like),
                Order.items.any(func.lower(OrderItem.name).like(like)),
            )
        )
    per_page = 10
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    orders = list(
        db.scalars(
            stmt.options(
                selectinload(Order.items)
                .selectinload(OrderItem.product)
                .selectinload(Product.images)
            )
            .order_by(Order.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    )
    reviewed = set(db.scalars(select(Review.product_id).where(Review.user_id == user.id)).all())
    return render(
        request,
        db,
        "account/orders.html",
        {
            "orders": orders,
            "status": status,
            "q": q,
            "page": page,
            "pages": pages,
            "total": total,
            "can_return": can_return,
            "reviewed": reviewed,
        },
        user=user,
    )


@router.get("/account/orders/{number}")
def order_detail(
    number: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """One order with its tracking timeline."""
    order = _own_order(db, user, number)
    return render(
        request,
        db,
        "account/order_detail.html",
        {
            "order": order,
            "steps": order_svc.progress_steps(order),
            "can_return": can_return(order),
            "cancel_reasons": CANCEL_REASONS,
            "return_reasons": RETURN_REASONS,
        },
        user=user,
    )


@router.post("/account/orders/{number}/cancel")
async def order_cancel(
    number: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> RedirectResponse:
    """Customer cancels an order before it ships."""
    form = await request.form()
    order = _own_order(db, user, number)
    try:
        order_svc.cancel_by_customer(db, order, str(form.get("reason") or ""))
        msg = "Your order has been cancelled."
        if order.payment_status == "refunded":
            msg += f" A refund of ${order.total:,} has been initiated."
        flash(request, msg)
    except order_svc.OrderError as err:
        flash(request, str(err), "error")
    return RedirectResponse(f"/account/orders/{number}", status_code=303)


@router.post("/account/orders/{number}/return")
async def order_return(
    number: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> RedirectResponse:
    """Customer requests a return."""
    form = await request.form()
    order = _own_order(db, user, number)
    try:
        order_svc.request_return(
            db, order, str(form.get("reason") or ""), get_settings().return_window_days
        )
        flash(request, "Return requested. Our courier partner will pick it up in 2 days.")
    except order_svc.OrderError as err:
        flash(request, str(err), "error")
    return RedirectResponse(f"/account/orders/{number}", status_code=303)


@router.post("/account/orders/{number}/buy-again")
def order_buy_again(
    number: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> RedirectResponse:
    """Put every still-available item from an order back in the cart."""
    order = _own_order(db, user, number)
    owner = cart_svc.CartOwner(user_id=user.id)
    added = 0
    for item in order.items:
        if item.product_id is None:
            continue
        try:
            cart_svc.add(db, owner, item.product_id, item.quantity)
            added += 1
        except cart_svc.CartError as err:
            flash(request, str(err), "warn")
    if added:
        flash(request, f"Added {added} item{'s' if added != 1 else ''} to your cart.")
    return RedirectResponse("/cart", status_code=303)


@router.get("/account/orders/{number}/invoice")
def order_invoice(
    number: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Printable GST tax invoice."""
    order = _own_order(db, user, number)
    store = settings_svc.all_settings(db)
    intra_state = order.ship_state.strip().lower() == "maharashtra"
    lines = []
    for item in order.items:
        gross = item.price * item.quantity
        taxable = round(gross / 1.18, 2)
        tax = round(gross - taxable, 2)
        lines.append({"item": item, "gross": gross, "taxable": taxable, "tax": tax})
    charges = order.shipping_fee + order.cod_fee
    totals = {
        "taxable": round(sum(line["taxable"] for line in lines), 2),
        "tax": round(sum(line["tax"] for line in lines), 2),
    }
    return render(
        request,
        db,
        "account/invoice.html",
        {
            "order": order,
            "lines": lines,
            "totals": totals,
            "charges": charges,
            "intra_state": intra_state,
            "store": store,
            "invoice_no": "INV-" + order.number.removeprefix("HT-"),
        },
        user=user,
    )


# ----------------------------------------------------------------------------- addresses


def address_form_errors(values: dict[str, str]) -> dict[str, str]:
    """Validate an address form; returns field -> message."""
    errors: dict[str, str] = {}
    if len(values.get("full_name", "")) < 2:
        errors["full_name"] = "Enter the recipient's full name."
    if not PHONE_RE.match(values.get("phone", "")):
        errors["phone"] = "Enter a 10-digit mobile number."
    if not order_svc.valid_pincode(values.get("pincode", "")):
        errors["pincode"] = "Enter a valid 6-digit PIN code."
    if len(values.get("line1", "")) < 3:
        errors["line1"] = "Enter flat / house number and building."
    if len(values.get("city", "")) < 2:
        errors["city"] = "Enter the town or city."
    if values.get("state") not in INDIAN_STATES:
        errors["state"] = "Choose a state."
    return errors


def read_address_form(form) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Pull address fields out of a submitted form."""
    keys = ("full_name", "phone", "pincode", "line1", "line2", "landmark", "city", "state", "kind")
    values = {k: str(form.get(k) or "").strip() for k in keys}
    values["phone"] = clean_phone(values["phone"])
    values["kind"] = values["kind"] if values["kind"] in {"home", "work"} else "home"
    return values


def save_address(
    db: Session, user: User, values: dict[str, str], make_default: bool, address: Address | None
) -> Address:
    """Create or update an address for ``user``."""
    existing = list(user.addresses)
    if address is None:
        make_default = make_default or not existing
        address = Address(user_id=user.id, **values)
        db.add(address)
    else:
        for key, value in values.items():
            setattr(address, key, value)
    if make_default:
        for other in existing:
            other.is_default = False
        address.is_default = True
    db.commit()
    return address


def _own_address(db: Session, user: User, address_id: int) -> Address:
    address = db.get(Address, address_id)
    if address is None or address.user_id != user.id:
        raise HTTPException(404, "Address not found")
    return address


@router.get("/account/addresses")
def addresses_page(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Saved addresses."""
    return render(request, db, "account/addresses.html", {}, user=user)


@router.get("/account/addresses/new")
@router.get("/account/addresses/{address_id}/edit")
def address_form(
    request: Request,
    address_id: int | None = None,
    next: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Add or edit an address."""
    address = _own_address(db, user, address_id) if address_id else None
    values = {}
    if address:
        values = {
            k: getattr(address, k)
            for k in ("full_name", "phone", "pincode", "line1", "line2", "landmark", "city",
                      "state", "kind")
        }  # fmt: skip
    else:
        values = {"full_name": user.name, "phone": user.phone, "kind": "home"}
    return render(
        request,
        db,
        "account/address_form.html",
        {
            "address": address,
            "values": values,
            "errors": {},
            "states": INDIAN_STATES,
            "next": safe_next(next) if next else "",
        },
        user=user,
    )


@router.post("/account/addresses/new")
@router.post("/account/addresses/{address_id}/edit")
async def address_submit(
    request: Request,
    address_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Save an address."""
    form = await request.form()
    address = _own_address(db, user, address_id) if address_id else None
    values = read_address_form(form)
    errors = address_form_errors(values)
    next_url = safe_next(str(form.get("next") or "")) if form.get("next") else ""
    if errors:
        return render(
            request,
            db,
            "account/address_form.html",
            {
                "address": address,
                "values": values,
                "errors": errors,
                "states": INDIAN_STATES,
                "next": next_url,
            },
            user=user,
            status_code=400,
        )
    save_address(db, user, values, bool(form.get("is_default")), address)
    flash(request, "Address saved.")
    return RedirectResponse(next_url or "/account/addresses", status_code=303)


@router.post("/account/addresses/{address_id}/delete")
def address_delete(
    address_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Delete an address."""
    address = _own_address(db, user, address_id)
    was_default = address.is_default
    db.delete(address)
    db.commit()
    db.refresh(user)
    if was_default and user.addresses:
        user.addresses[0].is_default = True
        db.commit()
    flash(request, "Address removed.", "info")
    return RedirectResponse("/account/addresses", status_code=303)


@router.post("/account/addresses/{address_id}/default")
def address_default(
    address_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> RedirectResponse:
    """Make an address the default."""
    address = _own_address(db, user, address_id)
    for other in user.addresses:
        other.is_default = other.id == address.id
    db.commit()
    flash(request, "Default address updated.")
    return RedirectResponse("/account/addresses", status_code=303)


# ----------------------------------------------------------------------------- wishlist


@router.get("/wishlist")
def wishlist_page(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Saved products."""
    items = list(
        db.scalars(
            select(WishlistItem)
            .where(WishlistItem.user_id == user.id)
            .options(selectinload(WishlistItem.product).selectinload(Product.images))
            .order_by(WishlistItem.created_at.desc())
        )
    )
    return render(request, db, "account/wishlist.html", {"items": items}, user=user)


@router.post("/wishlist/toggle")
async def wishlist_toggle(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Add or remove a product from the wishlist."""
    form = await request.form()
    try:
        product_id = int(str(form.get("product_id") or "0"))
    except ValueError:
        product_id = 0
    if db.get(Product, product_id) is None:
        raise HTTPException(404, "Product not found")
    item = db.scalar(
        select(WishlistItem).where(
            WishlistItem.user_id == user.id, WishlistItem.product_id == product_id
        )
    )
    if item:
        db.delete(item)
        saved = False
    else:
        db.add(WishlistItem(user_id=user.id, product_id=product_id))
        saved = True
    db.commit()
    if is_fetch(request):
        return JSONResponse({"ok": True, "saved": saved})
    flash(request, "Saved to your wishlist" if saved else "Removed from wishlist")
    return RedirectResponse(str(form.get("next") or "/wishlist"), status_code=303)


# ----------------------------------------------------------------------------- reviews


@router.post("/reviews")
async def review_submit(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> RedirectResponse:
    """Create or replace the user's review of a product."""
    form = await request.form()
    try:
        product_id = int(str(form.get("product_id") or "0"))
        rating = int(str(form.get("rating") or "0"))
    except ValueError:
        product_id, rating = 0, 0
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    back = f"/p/{product.slug}#reviews"
    title = str(form.get("title") or "").strip()[:120]
    body = str(form.get("body") or "").strip()
    if not 1 <= rating <= 5 or len(body) < 10:
        flash(request, "Please pick a star rating and write at least 10 characters.", "error")
        return RedirectResponse(back, status_code=303)
    verified = bool(
        db.scalar(
            select(Order.id)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.user_id == user.id,
                Order.status == "delivered",
                OrderItem.product_id == product.id,
            )
            .limit(1)
        )
    )
    parts = user.name.split() or ["Customer"]
    fields = {
        "author_name": parts[0] + (f" {parts[-1][:1]}." if len(parts) > 1 else ""),
        "author_city": user.addresses[0].city if user.addresses else "",
        "rating": rating,
        "title": title,
        "body": body,
        "verified_purchase": verified,
        "status": "published",
        "created_at": datetime.now(UTC),
    }
    review = db.scalar(
        select(Review).where(Review.product_id == product.id, Review.user_id == user.id)
    )
    if review is None:
        review = Review(product_id=product.id, user_id=user.id, helpful_count=0, **fields)
        db.add(review)
    else:
        for key, value in fields.items():
            setattr(review, key, value)
    db.flush()
    catalog.refresh_rating(db, product)
    db.commit()
    flash(request, "Thanks! Your review has been published.")
    return RedirectResponse(back, status_code=303)


@router.post("/reviews/{review_id}/helpful")
def review_helpful(review_id: int, request: Request, db: Session = Depends(get_db)):
    """Count a 'helpful' vote (once per session per review)."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Review not found")
    voted = set(request.session.get("helpful", []))
    if review_id not in voted:
        review.helpful_count += 1
        db.commit()
        voted.add(review_id)
        request.session["helpful"] = sorted(voted)[-200:]
    if is_fetch(request):
        return JSONResponse({"ok": True, "count": review.helpful_count})
    return RedirectResponse(f"/p/{review.product.slug}#reviews", status_code=303)
