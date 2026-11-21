"""Cart, checkout (simulated payment) and the order confirmation page."""

# FastAPI's Depends()/Query() defaults are the framework idiom.

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from northcart.catalog_data import US_STATES
from northcart.db import get_db
from northcart.models import PAYMENT_METHODS, Address, Order, OrderItem, Product, User
from northcart.services import cart as cart_svc
from northcart.services import catalog
from northcart.services import orders as order_svc
from northcart.web.deps import cart_owner, current_user, flash, require_user
from northcart.web.routes_account import address_form_errors, read_address_form, save_address
from northcart.web.templating import render

router = APIRouter()

PAYPAL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
BANKS = [
    "Chase", "Bank of America", "Wells Fargo", "Citibank", "U.S. Bank", "Capital One",
    "PNC Bank", "Truist", "TD Bank", "Ally Bank",
]  # fmt: skip


def _fetch(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


def _int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def luhn_ok(number: str) -> bool:
    """Luhn checksum for card numbers (13-19 digits)."""
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _back(request: Request, default: str = "/cart") -> str:
    ref = request.headers.get("referer", "")
    host = request.url.netloc
    if ref and host in ref:
        return ref
    return default


# ----------------------------------------------------------------------------- cart


@router.get("/cart")
def cart_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Shopping cart."""
    owner = cart_owner(request, user)
    coupon = request.session.get("coupon", "")
    # A saved coupon that no longer applies stays in the session; the page shows why.
    summary = cart_svc.summarize(db, owner, coupon)
    in_cart = {line.product_id for line in summary.lines}
    recs = [p for p in catalog.best_sellers(db, 12) if p.id not in in_cart][:6]
    return render(
        request,
        db,
        "shop/cart.html",
        {"summary": summary, "coupon_code": coupon, "recs": recs},
        user=user,
    )


@router.post("/cart/add")
async def cart_add(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Add a product to the cart (JSON for fetch, redirect otherwise)."""
    form = await request.form()
    owner = cart_owner(request, user)
    product_id = _int(form.get("product_id"))
    quantity = max(1, min(10, _int(form.get("quantity"), 1)))
    buy_now = bool(form.get("buy_now"))
    try:
        line = cart_svc.add(db, owner, product_id, quantity)
    except cart_svc.CartError as err:
        if _fetch(request):
            return JSONResponse({"error": str(err)}, status_code=400)
        flash(request, str(err), "error")
        return RedirectResponse(_back(request), status_code=303)
    name = line.product.name
    short = name if len(name) <= 48 else name[:45] + "…"
    message = f"Added to cart: {short}"
    if _fetch(request):
        return JSONResponse({"ok": True, "count": cart_svc.count(db, owner), "message": message})
    if buy_now:
        return RedirectResponse("/checkout", status_code=303)
    flash(request, message)
    return RedirectResponse("/cart", status_code=303)


async def _line_action(request: Request, db: Session, user: User | None, action: str):
    form = await request.form()
    owner = cart_owner(request, user)
    line_id = _int(form.get("line_id"))
    try:
        if action == "update":
            cart_svc.set_quantity(db, owner, line_id, _int(form.get("quantity"), 1))
        elif action == "remove":
            cart_svc.remove(db, owner, line_id)
            flash(request, "Item removed from your cart.", "info")
        elif action == "save":
            cart_svc.toggle_saved(db, owner, line_id)
    except cart_svc.CartError as err:
        if _fetch(request):
            return JSONResponse({"error": str(err)}, status_code=400)
        flash(request, str(err), "error")
    if _fetch(request):
        return JSONResponse({"ok": True, "count": cart_svc.count(db, owner)})
    return RedirectResponse("/cart", status_code=303)


@router.post("/cart/update")
async def cart_update(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    """Change a line's quantity."""
    return await _line_action(request, db, user, "update")


@router.post("/cart/remove")
async def cart_remove(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    """Remove a line."""
    return await _line_action(request, db, user, "remove")


@router.post("/cart/save")
async def cart_save(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    """Toggle 'Save for later'."""
    return await _line_action(request, db, user, "save")


@router.post("/cart/coupon")
async def cart_coupon(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
) -> RedirectResponse:
    """Apply (or remove, when empty) a coupon code."""
    form = await request.form()
    code = str(form.get("code") or "").strip().upper()
    back = str(form.get("next") or "/cart")
    back = back if back in {"/cart", "/checkout"} else "/cart"
    if not code:
        request.session.pop("coupon", None)
        flash(request, "Coupon removed.", "info")
        return RedirectResponse(back, status_code=303)
    summary = cart_svc.summarize(db, cart_owner(request, user), code)
    if summary.coupon_error:
        flash(request, summary.coupon_error, "error")
    else:
        request.session["coupon"] = code
        flash(request, f"{code} applied. You save ${summary.coupon_discount:,} on this order.")
    return RedirectResponse(back, status_code=303)


# ----------------------------------------------------------------------------- checkout


@router.get("/checkout")
def checkout_page(
    request: Request,
    payment: str = "card",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Single-page checkout: address, payment, review."""
    owner = cart_svc.CartOwner(user_id=user.id)
    payment = payment if payment in PAYMENT_METHODS else "card"
    coupon = request.session.get("coupon", "")
    summary = cart_svc.summarize(db, owner, coupon, payment)
    if not summary.lines:
        flash(request, "Your cart is empty. Add something first!", "info")
        return RedirectResponse("/cart", status_code=303)
    if summary.coupon_error:
        request.session.pop("coupon", None)
        flash(request, summary.coupon_error, "warn")
        summary = cart_svc.summarize(db, owner, "", payment)
    cod_summary = cart_svc.summarize(db, owner, request.session.get("coupon", ""), "cod")
    addresses = sorted(user.addresses, key=lambda a: (not a.is_default, a.id))
    selected = _int(request.session.get("checkout_address")) or (
        addresses[0].id if addresses else 0
    )
    estimates = {a.id: order_svc.delivery_estimate(a.zip_code) for a in addresses}
    return render(
        request,
        db,
        "shop/checkout.html",
        {
            "summary": summary,
            "cod_total": cod_summary.total,
            "addresses": addresses,
            "selected": selected,
            "estimates": estimates,
            "payment": payment,
            "banks": BANKS,
            "states": US_STATES,
            "coupon_code": request.session.get("coupon", ""),
            "values": {"full_name": user.name, "phone": user.phone, "kind": "home"},
            "errors": {},
        },
        user=user,
    )


@router.post("/checkout/address")
async def checkout_address(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    """Add a new address from the checkout page."""
    form = await request.form()
    values = read_address_form(form)
    errors = address_form_errors(values)
    if errors:
        flash(request, "Please fix the address: " + "; ".join(errors.values()), "error")
        return RedirectResponse("/checkout#address", status_code=303)
    address = save_address(db, user, values, bool(form.get("is_default")), None)
    request.session["checkout_address"] = address.id
    flash(request, "Address added. Delivering to " + address.city + ".")
    return RedirectResponse("/checkout", status_code=303)


@router.post("/checkout/place")
async def checkout_place(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> RedirectResponse:
    """Validate the (simulated) payment details and place the order."""
    form = await request.form()
    method = str(form.get("payment_method") or "")
    address = db.get(Address, _int(form.get("address_id")))
    if address is None or address.user_id != user.id:
        flash(request, "Please choose a delivery address.", "error")
        return RedirectResponse("/checkout", status_code=303)
    request.session["checkout_address"] = address.id
    error = ""
    if method == "paypal":
        if not PAYPAL_RE.match(str(form.get("paypal_email") or "").strip()):
            error = "Enter the email address of your PayPal account."
    elif method == "card":
        number = str(form.get("card_number") or "")
        expiry = str(form.get("card_expiry") or "").strip()
        cvv = str(form.get("card_cvv") or "").strip()
        match = re.match(r"^(0[1-9]|1[0-2])\s*/\s*(\d{2})$", expiry)
        if not luhn_ok(number):
            error = "That card number doesn't look right."
        elif not match:
            error = "Enter the expiry date as MM/YY."
        elif not re.fullmatch(r"\d{3,4}", cvv):
            error = "Enter the 3 or 4 digit CVV."
        elif not str(form.get("card_name") or "").strip():
            error = "Enter the name on the card."
    elif method == "bank":
        if str(form.get("bank") or "") not in BANKS:
            error = "Choose your bank."
    elif method != "cod":
        error = "Please choose a payment method."
    if error:
        flash(request, error, "error")
        return RedirectResponse(f"/checkout?payment={method or 'card'}", status_code=303)
    try:
        order = order_svc.place_order(db, user, address, method, request.session.get("coupon", ""))
    except order_svc.OrderError as err:
        flash(request, str(err), "error")
        return RedirectResponse(f"/checkout?payment={method}", status_code=303)
    request.session.pop("coupon", None)
    request.session.pop("checkout_address", None)
    return RedirectResponse(f"/order/{order.number}/success", status_code=303)


@router.get("/order/{number}/success")
def order_success(
    number: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Order confirmation."""
    order = db.scalar(
        select(Order)
        .where(Order.number == number, Order.user_id == user.id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.images)
        )
    )
    if order is None:
        raise HTTPException(404, "Order not found")
    recs = catalog.best_sellers(db, 6)
    return render(request, db, "shop/order_success.html", {"order": order, "recs": recs}, user=user)
