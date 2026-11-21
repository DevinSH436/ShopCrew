"""Seller / admin panel at ``/admin``: dashboard, orders, catalogue, customers, AI crew."""

from __future__ import annotations

import csv
import io
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from northcart.art import DRAWINGS, product_svg
from northcart.config import get_settings
from northcart.db import get_db
from northcart.models import (
    ORDER_STATUS_LABELS,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    Address,
    Category,
    CompetitorPrice,
    Coupon,
    CrewRun,
    Order,
    OrderItem,
    Product,
    ProductImage,
    Review,
    User,
)
from northcart.services import ai as ai_svc
from northcart.services import analytics
from northcart.services import settings as settings_svc
from northcart.services.catalog import refresh_rating
from northcart.services.orders import TRANSITIONS, OrderError, set_status
from northcart.web.deps import flash, require_admin
from northcart.web.templating import IST, render

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

DB = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_admin)]

PER_PAGE = 25
NEEDS_ACTION = ("placed", "confirmed", "packed", "return_requested")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".webp": b"RIFF",
}
CATEGORY_ICONS = ["headphones", "watch", "bolt", "keyboard", "home", "shirt", "dumbbell",
                  "sparkle", "book", "box", "gift", "leaf"]  # fmt: skip

_status_cache: dict[str, Any] = {"at": 0.0, "value": None}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def ai_status() -> dict[str, Any]:
    """Model status, cached for 30 s so every page load doesn't ping Ollama."""
    if _status_cache["value"] is None or time.time() - _status_cache["at"] > 30:
        _status_cache.update(at=time.time(), value=ai_svc.model_status())
    return _status_cache["value"]


def page(
    request: Request,
    db: Session,
    user: User,
    name: str,
    ctx: dict[str, Any] | None = None,
    section: str = "",
    status_code: int = 200,
) -> Response:
    """Render an admin template with the sidebar context."""
    pending = db.scalar(select(func.count(Order.id)).where(Order.status.in_(NEEDS_ACTION))) or 0
    base = {"section": section, "pending_count": pending, "ai": ai_status()}
    base.update(ctx or {})
    return render(request, db, name, base, status_code=status_code, user=user)


def back(url: str) -> RedirectResponse:
    """303 redirect for the POST/redirect/GET pattern."""
    return RedirectResponse(url, status_code=303)


def slugify(text: str) -> str:
    """URL slug from a name."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:150] or "item"


def to_int(value: Any, default: int | None = None) -> int | None:
    """Parse an int from form/query input (commas allowed)."""
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def parse_day(value: str | None, end: bool = False) -> datetime | None:
    """``YYYY-MM-DD`` in IST -> UTC datetime at the start (or end) of that day."""
    if not value:
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=IST)
    except ValueError:
        return None
    if end:
        d += timedelta(days=1) - timedelta(microseconds=1)
    return d.astimezone(UTC)


def paginate(total: int, page_no: int) -> dict[str, int]:
    """Page maths for templates."""
    pages = max(1, -(-total // PER_PAGE))
    current = min(max(1, page_no), pages)
    return {"page": current, "pages": pages, "total": total, "offset": (current - 1) * PER_PAGE}


def qs(request: Request, **changes: Any) -> str:
    """Current query string with some keys replaced (None removes)."""
    params = dict(request.query_params)
    for k, v in changes.items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = str(v)
    from urllib.parse import urlencode

    return "?" + urlencode(params) if params else "?"


def csv_response(filename: str, header: list[str], rows: list[list[Any]]) -> StreamingResponse:
    """Stream a CSV download."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def get_or_404(db: Session, model: type, ident: int) -> Any:
    """Fetch by primary key or raise 404."""
    obj = db.get(model, ident)
    if obj is None:
        raise HTTPException(404, "Not found")
    return obj


# --------------------------------------------------------------------------------------
# Dashboard & search
# --------------------------------------------------------------------------------------


@router.get("")
def dashboard(
    request: Request,
    db: DB,
    user: Admin,
    days: int = 30,
) -> Response:
    """Overview with KPIs and charts."""
    days = days if days in (7, 30, 90) else 30
    latest_run = db.scalar(
        select(CrewRun).where(CrewRun.status == "done").order_by(CrewRun.id.desc())
    )
    ctx = {
        "days": days,
        "kpis": analytics.kpis(db, days),
        "series": analytics.revenue_by_day(db, days),
        "by_status": analytics.orders_by_status(db, days),
        "by_category": analytics.sales_by_category(db, days),
        "payments": analytics.payment_method_split(db, days),
        "top": analytics.top_products(db, days, 6),
        "low": analytics.low_stock(db, 8),
        "recent": analytics.recent_orders(db, 8),
        "bad_reviews": analytics.reviews_needing_attention(db, 4),
        "latest_run": latest_run,
    }
    return page(request, db, user, "admin/dashboard.html", ctx, "dashboard")


@router.get("/search")
def search(
    request: Request,
    db: DB,
    user: Admin,
    q: str = "",
) -> Response:
    """Global search across orders, products and customers."""
    q = q.strip()
    orders: list[Order] = []
    products: list[Product] = []
    customers: list[User] = []
    if q:
        like = f"%{q.lower()}%"
        order = db.scalar(select(Order).where(func.upper(Order.number) == q.upper()))
        if order:
            return back(f"/admin/orders/{order.number}")
        orders = list(db.scalars(
            select(Order).where(or_(func.lower(Order.number).like(like),
                                    func.lower(Order.ship_name).like(like),
                                    Order.ship_phone.like(like)))
            .order_by(Order.created_at.desc()).limit(20)
        ))  # fmt: skip
        products = list(db.scalars(
            select(Product).where(or_(func.lower(Product.name).like(like),
                                      func.lower(Product.sku).like(like),
                                      func.lower(Product.brand).like(like))).limit(20)
        ))  # fmt: skip
        customers = list(db.scalars(
            select(User).where(or_(func.lower(User.name).like(like),
                                   func.lower(User.email).like(like), User.phone.like(like)))
            .limit(20)
        ))  # fmt: skip
    ctx = {"q": q, "orders": orders, "products": products, "customers": customers}
    return page(request, db, user, "admin/search.html", ctx)


# --------------------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------------------


def _order_query(request: Request):  # type: ignore[no-untyped-def]
    p = request.query_params
    stmt = select(Order)
    if p.get("status"):
        stmt = stmt.where(Order.status == p["status"])
    if p.get("payment"):
        stmt = stmt.where(Order.payment_method == p["payment"])
    if start := parse_day(p.get("from")):
        stmt = stmt.where(Order.created_at >= start)
    if end := parse_day(p.get("to"), end=True):
        stmt = stmt.where(Order.created_at <= end)
    if q := (p.get("q") or "").strip().lower():
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                func.lower(Order.number).like(like),
                func.lower(Order.ship_name).like(like),
                Order.ship_phone.like(like),
                Order.user.has(func.lower(User.email).like(like)),
            )
        )
    return stmt


@router.get("/orders")
def orders_list(
    request: Request,
    db: DB,
    user: Admin,
) -> Response:
    """Order list with status tabs and filters."""
    page_no = to_int(request.query_params.get("page"), 1) or 1
    stmt = _order_query(request)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pg = paginate(total, page_no)
    orders = list(db.scalars(
        stmt.options(selectinload(Order.user), selectinload(Order.items))
        .order_by(Order.created_at.desc()).offset(pg["offset"]).limit(PER_PAGE)
    ))  # fmt: skip
    counts = analytics.orders_by_status(db)
    ctx = {
        "orders": orders, "pg": pg, "counts": counts, "all_count": sum(counts.values()),
        "statuses": ORDER_STATUSES, "filters": dict(request.query_params),
        "qs": lambda **kw: qs(request, **kw),
    }  # fmt: skip
    return page(request, db, user, "admin/orders.html", ctx, "orders")


@router.get("/orders/export.csv")
def orders_export(request: Request, db: DB) -> StreamingResponse:
    """Download the filtered order list."""
    orders = db.scalars(
        _order_query(request)
        .options(selectinload(Order.items), selectinload(Order.user))
        .order_by(Order.created_at.desc())
    )
    rows = [
        [o.number, analytics.aware(o.created_at).astimezone(IST).strftime("%Y-%m-%d %H:%M"),  # type: ignore[union-attr]
         o.ship_name, o.user.email, o.ship_city, o.ship_state, o.ship_pincode, o.item_count,
         o.subtotal, o.discount, o.coupon_code, o.shipping_fee + o.cod_fee, o.total,
         o.payment_label, o.payment_status, o.status_label, o.courier, o.tracking_number]
        for o in orders
    ]  # fmt: skip
    header = ["Order", "Placed (IST)", "Customer", "Email", "City", "State", "PIN", "Units",
              "Subtotal", "Discount", "Coupon", "Fees", "Total", "Payment", "Payment status",
              "Status", "Courier", "AWB"]  # fmt: skip
    stamp = datetime.now(IST).strftime("%Y%m%d")
    return csv_response(f"northcart-orders-{stamp}.csv", header, rows)


@router.post("/orders/bulk")
async def orders_bulk(request: Request, db: DB) -> RedirectResponse:
    """Move several orders to 'confirmed' or 'packed'."""
    form = await request.form()
    target = str(form.get("action", ""))
    numbers = [str(n) for n in form.getlist("numbers")]
    if target not in {"confirmed", "packed"} or not numbers:
        flash(request, "Select some orders and an action first.", "warn")
        return back(str(form.get("next") or "/admin/orders"))
    ok = skipped = 0
    for order in db.scalars(select(Order).where(Order.number.in_(numbers))):
        try:
            set_status(db, order, target)
            ok += 1
        except OrderError:
            db.rollback()
            skipped += 1
    msg = f"{ok} order(s) marked {ORDER_STATUS_LABELS[target].lower()}."
    if skipped:
        msg += f" {skipped} skipped (status didn't allow it)."
    flash(request, msg, "success" if ok else "warn")
    return back(str(form.get("next") or "/admin/orders"))


def _order_or_404(db: Session, number: str) -> Order:
    order = db.scalar(
        select(Order).where(Order.number == number)
        .options(selectinload(Order.items).selectinload(OrderItem.product),
                 selectinload(Order.events), selectinload(Order.user))
    )  # fmt: skip
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


@router.get("/orders/{number}")
def order_detail(
    request: Request,
    number: str,
    db: DB,
    user: Admin,
) -> Response:
    """One order with timeline and actions."""
    order = _order_or_404(db, number)
    customer_orders = db.scalar(select(func.count(Order.id)).where(Order.user_id == order.user_id))
    ctx = {
        "order": order,
        "next_statuses": TRANSITIONS.get(order.status, []),
        "customer_orders": customer_orders,
        "gst": analytics.split_gst(order.total, order.ship_state == "Maharashtra"),
    }
    return page(request, db, user, "admin/order_detail.html", ctx, "orders")


@router.post("/orders/{number}/status")
async def order_status(request: Request, number: str, db: DB) -> Response:
    """Advance an order's status."""
    order = _order_or_404(db, number)
    form = await request.form()
    try:
        set_status(db, order, str(form.get("status", "")), str(form.get("note", "")).strip())
        flash(request, f"Order {number} is now {order.status_label.lower()}.")
    except OrderError as err:
        db.rollback()
        flash(request, str(err), "error")
    return back(f"/admin/orders/{number}")


@router.post("/orders/{number}/shipping")
async def order_shipping(request: Request, number: str, db: DB) -> Response:
    """Edit courier and tracking number."""
    order = _order_or_404(db, number)
    form = await request.form()
    order.courier = str(form.get("courier", "")).strip()[:60]
    order.tracking_number = str(form.get("tracking_number", "")).strip()[:40]
    db.commit()
    flash(request, "Shipping details saved.")
    return back(f"/admin/orders/{number}")


@router.post("/orders/{number}/note")
async def order_note(request: Request, number: str, db: DB) -> Response:
    """Save the internal note."""
    order = _order_or_404(db, number)
    form = await request.form()
    order.admin_note = str(form.get("admin_note", "")).strip()[:2000]
    db.commit()
    flash(request, "Internal note saved.")
    return back(f"/admin/orders/{number}")


@router.get("/orders/{number}/invoice")
def order_invoice(
    request: Request,
    number: str,
    db: DB,
    user: Admin,
) -> Response:
    """Printable GST tax invoice and packing slip."""
    order = _order_or_404(db, number)
    intra = order.ship_state == "Maharashtra"
    lines = []
    for item in order.items:
        g = analytics.split_gst(item.line_total, intra)
        lines.append({"item": item, **g})
    fees = order.shipping_fee + order.cod_fee
    ctx = {
        "order": order,
        "lines": lines,
        "intra": intra,
        "fees": fees,
        "fees_gst": analytics.split_gst(fees, intra) if fees else None,
        "discount_gst": analytics.split_gst(order.discount, intra) if order.discount else None,
        "totals": analytics.split_gst(order.total, intra),
        "invoice_no": "INV-" + order.number.removeprefix("HT-"),
    }
    return render(request, db, "admin/invoice.html", ctx, user=user)


# --------------------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------------------


@router.get("/products")
def products_list(request: Request, db: DB, user: Admin) -> Response:
    """Product table with filters."""
    p = request.query_params
    stmt = select(Product)
    if q := (p.get("q") or "").strip().lower():
        like = f"%{q}%"
        stmt = stmt.where(or_(func.lower(Product.name).like(like),
                              func.lower(Product.sku).like(like),
                              func.lower(Product.brand).like(like)))  # fmt: skip
    if p.get("category"):
        stmt = stmt.where(Product.category.has(Category.slug == p["category"]))
    status = p.get("status", "")
    if status == "active":
        stmt = stmt.where(Product.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(Product.is_active.is_(False))
    elif status == "low":
        stmt = stmt.where(Product.stock > 0, Product.stock <= Product.low_stock_threshold)
    elif status == "out":
        stmt = stmt.where(Product.stock <= 0)
    order = {
        "name": Product.name.asc(), "price": Product.price.desc(), "stock": Product.stock.asc(),
        "sold": Product.sold_count.desc(), "rating": Product.rating_avg.desc(),
        "newest": Product.created_at.desc(),
    }.get(p.get("sort", ""), Product.created_at.desc())  # fmt: skip
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pg = paginate(total, to_int(p.get("page"), 1) or 1)
    products = list(db.scalars(
        stmt.options(selectinload(Product.images), selectinload(Product.category))
        .order_by(order, Product.id).offset(pg["offset"]).limit(PER_PAGE)
    ))  # fmt: skip
    cats = list(db.scalars(select(Category).order_by(Category.sort_order)))
    ctx = {"products": products, "pg": pg, "cats": cats, "filters": dict(p),
           "qs": lambda **kw: qs(request, **kw)}  # fmt: skip
    return page(request, db, user, "admin/products.html", ctx, "products")


@router.post("/products/bulk")
async def products_bulk(request: Request, db: DB) -> Response:
    """Activate or deactivate several products."""
    form = await request.form()
    ids = [to_int(i) for i in form.getlist("ids")]
    action = str(form.get("action", ""))
    if action not in {"activate", "deactivate", "feature", "unfeature"} or not ids:
        flash(request, "Select some products and an action first.", "warn")
        return back("/admin/products")
    n = 0
    for product in db.scalars(select(Product).where(Product.id.in_(ids))):
        if action in {"activate", "deactivate"}:
            product.is_active = action == "activate"
        else:
            product.is_featured = action == "feature"
        n += 1
    db.commit()
    flash(request, f"Updated {n} product(s).")
    return back(str(form.get("next") or "/admin/products"))


@router.post("/products/{product_id}/toggle")
def product_toggle(product_id: int, db: DB) -> JSONResponse:
    """Flip a product's active flag (fetch)."""
    product = get_or_404(db, Product, product_id)
    product.is_active = not product.is_active
    db.commit()
    return JSONResponse({"ok": True, "active": product.is_active})


@router.get("/art-preview")
def art_preview(kind: str = "box", color: str = "#4f46e5", v: int = 0, label: str = "") -> Response:
    """Live preview of generated product artwork for the product form."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#4f46e5"
    return Response(product_svg(kind, color, v, label[:20]), media_type="image/svg+xml")


@router.post("/products/ai-describe")
async def product_ai_describe(request: Request) -> JSONResponse:
    """Draft listing copy with the configured LLM (Ollama)."""
    form = await request.form()
    name = str(form.get("name", "")).strip()
    facts = [ln.strip("-• ").strip() for ln in str(form.get("facts", "")).splitlines()]
    facts = [f for f in facts if f]
    if not name or not facts:
        return JSONResponse(
            {"error": "Add a product name and at least one highlight or spec first."}, 400
        )
    try:
        data = ai_svc.write_description(
            name, str(form.get("brand", "")), str(form.get("category", "")), facts
        )
    except Exception as err:  # noqa: BLE001 - shown to the admin
        status = ai_svc.model_status()
        hint = "" if status.get("ok") else f" ({status.get('detail', '')})"
        return JSONResponse({"error": f"AI writer failed: {err}{hint}"}, 502)
    return JSONResponse({"ok": True, "model": ai_svc.configured_model(), **data})


def _product_form_ctx(db: Session, product: Product | None, errors: dict[str, str],
                      values: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    return {
        "product": product,
        "errors": errors,
        "v": values,
        "cats": list(db.scalars(select(Category).order_by(Category.sort_order))),
        "art_kinds": sorted(DRAWINGS),
        "has_orders": bool(
            product and db.scalar(select(exists().where(OrderItem.product_id == product.id)))
        ),
    }


def _values_from_product(p: Product) -> dict[str, Any]:
    return {
        "name": p.name, "slug": p.slug, "sku": p.sku, "brand": p.brand,
        "category_id": p.category_id, "price": p.price, "mrp": p.mrp, "cost_price": p.cost_price,
        "stock": p.stock, "low_stock_threshold": p.low_stock_threshold,
        "short_description": p.short_description, "description": p.description,
        "highlights": "\n".join(p.highlights or []),
        "specs": "\n".join(f"{k}: {v}" for k, v in (p.specs or {}).items()),
        "tags": ", ".join(p.tags or []), "art_kind": p.art_kind, "color": p.color,
        "is_active": p.is_active, "is_featured": p.is_featured, "seo_title": p.seo_title,
        "seo_meta": p.seo_meta, "keywords": ", ".join(p.keywords or []),
    }  # fmt: skip


def _parse_product_form(
    db: Session, form: Any, product: Product | None
) -> tuple[dict[str, Any], dict[str, str]]:
    v: dict[str, Any] = {k: str(form.get(k, "")).strip() for k in (
        "name", "slug", "sku", "brand", "short_description", "description", "highlights",
        "specs", "tags", "art_kind", "color", "seo_title", "seo_meta", "keywords")}  # fmt: skip
    for k in ("category_id", "price", "mrp", "cost_price", "stock", "low_stock_threshold"):
        v[k] = to_int(form.get(k))
    v["is_active"] = form.get("is_active") == "on"
    v["is_featured"] = form.get("is_featured") == "on"
    v["slug"] = slugify(v["slug"] or v["name"])
    errors: dict[str, str] = {}
    if len(v["name"]) < 3:
        errors["name"] = "Enter a product name (3+ characters)."
    if not v["sku"]:
        errors["sku"] = "SKU is required."
    if not v["brand"]:
        errors["brand"] = "Brand is required."
    if not v["category_id"] or db.get(Category, v["category_id"]) is None:
        errors["category_id"] = "Choose a category."
    if not v["price"] or v["price"] <= 0:
        errors["price"] = "Price must be more than $0."
    if not v["mrp"] or v["mrp"] <= 0:
        v["mrp"] = v["price"]
    elif v["price"] and v["mrp"] < v["price"]:
        errors["mrp"] = "MRP can't be lower than the selling price."
    if v["stock"] is None or v["stock"] < 0:
        errors["stock"] = "Stock must be 0 or more."
    v["cost_price"] = max(0, v["cost_price"] or 0)
    v["low_stock_threshold"] = max(0, v["low_stock_threshold"] or 10)
    if len(v["seo_title"]) > 70:
        errors["seo_title"] = "Keep the SEO title within 70 characters."
    if len(v["seo_meta"]) > 160:
        errors["seo_meta"] = "Keep the meta description within 160 characters."
    if v["art_kind"] not in DRAWINGS:
        v["art_kind"] = "box"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", v["color"]):
        v["color"] = "#4f46e5"
    pid = product.id if product else -1
    if db.scalar(select(Product.id).where(Product.slug == v["slug"], Product.id != pid)):
        errors["slug"] = "Another product already uses this URL slug."
    if v["sku"] and db.scalar(select(Product.id).where(Product.sku == v["sku"], Product.id != pid)):
        errors["sku"] = "Another product already uses this SKU."
    return v, errors


def _apply_product_values(p: Product, v: dict[str, Any]) -> None:
    for k in ("name", "slug", "sku", "brand", "category_id", "price", "mrp", "cost_price",
              "stock", "low_stock_threshold", "short_description", "description", "art_kind",
              "color", "is_active", "is_featured", "seo_title", "seo_meta"):  # fmt: skip
        setattr(p, k, v[k])
    p.highlights = [h.strip("-• ").strip() for h in v["highlights"].splitlines() if h.strip()]
    specs: dict[str, str] = {}
    for line in v["specs"].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            if key.strip():
                specs[key.strip()] = val.strip()
    p.specs = specs
    p.tags = [t.strip().lower() for t in v["tags"].split(",") if t.strip()]
    p.keywords = [t.strip() for t in v["keywords"].split(",") if t.strip()]


@router.get("/products/new")
def product_new(request: Request, db: DB, user: Admin) -> Response:
    """Blank product form."""
    values = {"is_active": True, "art_kind": "box", "color": "#2563eb", "stock": 0,
              "low_stock_threshold": 10}  # fmt: skip
    return page(request, db, user, "admin/product_form.html",
                _product_form_ctx(db, None, {}, values), "products")  # fmt: skip


@router.post("/products/new")
async def product_create(request: Request, db: DB, user: Admin) -> Response:
    """Create a product."""
    form = await request.form()
    v, errors = _parse_product_form(db, form, None)
    if errors:
        return page(request, db, user, "admin/product_form.html",
                    _product_form_ctx(db, None, errors, v), "products", 422)  # fmt: skip
    product = Product()
    _apply_product_values(product, v)
    db.add(product)
    db.commit()
    await _save_uploads(request, db, product, form)
    flash(request, f"Created “{product.name}”.")
    return back(f"/admin/products/{product.id}")


@router.get("/products/{product_id}")
def product_edit(
    request: Request,
    product_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Edit form."""
    product = get_or_404(db, Product, product_id)
    ctx = _product_form_ctx(db, product, {}, _values_from_product(product))
    return page(request, db, user, "admin/product_form.html", ctx, "products")


@router.post("/products/{product_id}")
async def product_update(
    request: Request,
    product_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Save product edits (and any uploaded images)."""
    product = get_or_404(db, Product, product_id)
    form = await request.form()
    v, errors = _parse_product_form(db, form, product)
    if errors:
        return page(request, db, user, "admin/product_form.html",
                    _product_form_ctx(db, product, errors, v), "products", 422)  # fmt: skip
    _apply_product_values(product, v)
    db.commit()
    await _save_uploads(request, db, product, form)
    flash(request, "Product saved.")
    return back(f"/admin/products/{product.id}")


async def _save_uploads(request: Request, db: Session, product: Product, form: Any) -> None:
    files = [f for f in form.getlist("images") if getattr(f, "filename", "")]
    if not files:
        return
    folder = get_settings().media_dir / "products"
    folder.mkdir(parents=True, exist_ok=True)
    order = len(product.images)
    saved, rejected = 0, []
    for upload in files:
        ext = "." + upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        data = await upload.read(MAX_IMAGE_BYTES + 1)
        magic = IMAGE_TYPES.get(ext)
        ok_magic = magic is not None and data.startswith(magic)
        if ext == ".webp":
            ok_magic = ok_magic and data[8:12] == b"WEBP"
        if not ok_magic or len(data) > MAX_IMAGE_BYTES:
            rejected.append(upload.filename)
            continue
        name = f"{uuid.uuid4().hex}{'.jpg' if ext == '.jpeg' else ext}"
        (folder / name).write_bytes(data)
        product.images.append(ProductImage(path=f"products/{name}", alt=product.name,
                                           sort_order=order))  # fmt: skip
        order += 1
        saved += 1
    db.commit()
    if saved:
        flash(request, f"Uploaded {saved} image(s).")
    if rejected:
        flash(request, "Skipped (PNG/JPG/WebP up to 5 MB only): " + ", ".join(rejected), "error")


@router.post("/products/{product_id}/images/{image_id}/delete")
def product_image_delete(request: Request, product_id: int, image_id: int, db: DB) -> Response:
    """Remove an uploaded image."""
    img = db.get(ProductImage, image_id)
    if img is None or img.product_id != product_id:
        raise HTTPException(404, "Image not found")
    path = get_settings().media_dir / img.path
    db.delete(img)
    db.commit()
    path.unlink(missing_ok=True)
    flash(request, "Image removed.")
    return back(f"/admin/products/{product_id}#images")


@router.post("/products/{product_id}/delete")
def product_delete(request: Request, product_id: int, db: DB) -> Response:
    """Delete a product, or deactivate it if it appears in orders."""
    product = get_or_404(db, Product, product_id)
    if db.scalar(select(exists().where(OrderItem.product_id == product.id))):
        product.is_active = False
        db.commit()
        flash(request, f"“{product.name}” has orders, so it was hidden from the store instead.",
              "warn")  # fmt: skip
        return back(f"/admin/products/{product.id}")
    name = product.name
    db.delete(product)
    db.commit()
    flash(request, f"Deleted “{name}”.")
    return back("/admin/products")


@router.post("/products/{product_id}/competitors")
async def competitor_save(request: Request, product_id: int, db: DB) -> Response:
    """Add (no id) or update (with id) a competitor price row."""
    product = get_or_404(db, Product, product_id)
    form = await request.form()
    name = str(form.get("competitor", "")).strip()[:80]
    price = to_int(form.get("price"))
    if not name or not price or price <= 0:
        flash(request, "Enter a competitor name and a price.", "error")
        return back(f"/admin/products/{product_id}#competitors")
    row_id = to_int(form.get("id"))
    row = db.get(CompetitorPrice, row_id) if row_id else None
    if row is None or row.product_id != product.id:
        row = CompetitorPrice(product_id=product.id)
        db.add(row)
    row.competitor, row.price = name, price
    row.in_stock = form.get("in_stock") == "on"
    row.last_checked = datetime.now(UTC)
    db.commit()
    flash(request, f"Saved {name} price.")
    return back(f"/admin/products/{product_id}#competitors")


@router.post("/products/{product_id}/competitors/{row_id}/delete")
def competitor_delete(request: Request, product_id: int, row_id: int, db: DB) -> Response:
    """Delete a competitor price row."""
    row = db.get(CompetitorPrice, row_id)
    if row is None or row.product_id != product_id:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    flash(request, "Competitor price removed.")
    return back(f"/admin/products/{product_id}#competitors")


# --------------------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------------------


@router.get("/inventory")
def inventory(request: Request, db: DB, user: Admin) -> Response:
    """Stock levels with quick adjust."""
    f = request.query_params.get("filter", "")
    stmt = select(Product).options(selectinload(Product.category))
    if f == "low":
        stmt = stmt.where(Product.stock > 0, Product.stock <= Product.low_stock_threshold)
    elif f == "out":
        stmt = stmt.where(Product.stock <= 0)
    products = list(db.scalars(stmt.order_by(Product.stock.asc(), Product.name)))
    everything = list(db.scalars(select(Product)))
    ctx = {
        "products": products,
        "filter": f,
        "stock_value": sum(p.stock * p.cost_price for p in everything),
        "retail_value": sum(p.stock * p.price for p in everything),
        "units": sum(p.stock for p in everything),
        "low_count": sum(1 for p in everything if p.is_low_stock),
        "out_count": sum(1 for p in everything if p.stock <= 0),
    }
    return page(request, db, user, "admin/inventory.html", ctx, "inventory")


@router.post("/inventory/{product_id}/stock")
async def inventory_adjust(request: Request, product_id: int, db: DB) -> JSONResponse:
    """Set or adjust stock (fetch). Fields: mode=set|add, value."""
    product = get_or_404(db, Product, product_id)
    form = await request.form()
    value = to_int(form.get("value"))
    if value is None:
        return JSONResponse({"error": "Enter a number."}, 400)
    new = value if form.get("mode") == "set" else product.stock + value
    if new < 0:
        return JSONResponse({"error": "Stock can't go below zero."}, 400)
    product.stock = new
    db.commit()
    state = "out" if new <= 0 else "low" if product.is_low_stock else "ok"
    return JSONResponse({"ok": True, "stock": new, "state": state})


# --------------------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------------------


@router.get("/categories")
def categories(request: Request, db: DB, user: Admin) -> Response:
    """Category list with inline edit."""
    rows = db.execute(
        select(Category, func.count(Product.id))
        .outerjoin(Product, Product.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.sort_order, Category.name)
    ).all()
    ctx = {"rows": rows, "icons": CATEGORY_ICONS}
    return page(request, db, user, "admin/categories.html", ctx, "categories")


@router.post("/categories")
async def category_save(request: Request, db: DB) -> Response:
    """Create (no id) or update a category."""
    form = await request.form()
    name = str(form.get("name", "")).strip()[:80]
    if len(name) < 2:
        flash(request, "Category name is required.", "error")
        return back("/admin/categories")
    slug = slugify(str(form.get("slug", "")) or name)
    cat_id = to_int(form.get("id"))
    cat = db.get(Category, cat_id) if cat_id else None
    clash = db.scalar(
        select(Category.id).where(Category.slug == slug, Category.id != (cat_id or -1))
    )
    if clash:
        flash(request, f"The slug “{slug}” is already used.", "error")
        return back("/admin/categories")
    if cat is None:
        cat = Category()
        db.add(cat)
    cat.name, cat.slug = name, slug
    cat.description = str(form.get("description", "")).strip()[:300]
    cat.icon = str(form.get("icon", "box"))[:40]
    cat.sort_order = to_int(form.get("sort_order"), 0) or 0
    db.commit()
    flash(request, f"Saved category “{name}”.")
    return back("/admin/categories")


@router.post("/categories/{cat_id}/delete")
def category_delete(request: Request, cat_id: int, db: DB) -> Response:
    """Delete an empty category."""
    cat = get_or_404(db, Category, cat_id)
    count = db.scalar(select(func.count(Product.id)).where(Product.category_id == cat.id)) or 0
    if count:
        flash(request, f"“{cat.name}” still has {count} product(s). Move them first.", "error")
    else:
        db.delete(cat)
        db.commit()
        flash(request, f"Deleted “{cat.name}”.")
    return back("/admin/categories")


# --------------------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------------------


def _customer_stats():  # type: ignore[no-untyped-def]
    return (
        select(
            Order.user_id.label("uid"),
            func.count(Order.id).label("orders"),
            func.sum(Order.total).label("spend"),
            func.max(Order.created_at).label("last"),
        )
        .where(Order.status.not_in(analytics.LOST_STATUSES))
        .group_by(Order.user_id)
        .subquery()
    )


@router.get("/customers")
def customers(request: Request, db: DB, user: Admin) -> Response:
    """Customer list with lifetime value."""
    p = request.query_params
    stats = _customer_stats()
    stmt = select(User, stats.c.orders, stats.c.spend, stats.c.last).outerjoin(
        stats, stats.c.uid == User.id
    )
    if q := (p.get("q") or "").strip().lower():
        like = f"%{q}%"
        stmt = stmt.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like),
                              User.phone.like(like)))  # fmt: skip
    if p.get("type") == "staff":
        stmt = stmt.where(User.is_admin.is_(True))
    elif p.get("type") == "blocked":
        stmt = stmt.where(User.is_active.is_(False))
    sort = {"spend": func.coalesce(stats.c.spend, 0).desc(),
            "orders": func.coalesce(stats.c.orders, 0).desc(),
            "name": User.name.asc()}.get(p.get("sort", ""), User.created_at.desc())  # fmt: skip
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pg = paginate(total, to_int(p.get("page"), 1) or 1)
    rows = db.execute(stmt.order_by(sort, User.id).offset(pg["offset"]).limit(PER_PAGE)).all()
    ctx = {"rows": rows, "pg": pg, "filters": dict(p), "qs": lambda **kw: qs(request, **kw)}
    return page(request, db, user, "admin/customers.html", ctx, "customers")


@router.get("/customers/{user_id}")
def customer_detail(
    request: Request,
    user_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Customer profile with orders and reviews."""
    customer = get_or_404(db, User, user_id)
    orders = list(db.scalars(
        select(Order).where(Order.user_id == customer.id)
        .options(selectinload(Order.items)).order_by(Order.created_at.desc())
    ))  # fmt: skip
    reviews = list(db.scalars(
        select(Review).where(Review.user_id == customer.id)
        .options(selectinload(Review.product)).order_by(Review.created_at.desc())
    ))  # fmt: skip
    valid = [o for o in orders if o.status not in analytics.LOST_STATUSES]
    ctx = {
        "customer": customer, "orders": orders, "reviews": reviews,
        "addresses": list(db.scalars(select(Address).where(Address.user_id == customer.id))),
        "spend": sum(o.total for o in valid), "order_count": len(valid),
        "aov": round(sum(o.total for o in valid) / len(valid)) if valid else 0,
    }  # fmt: skip
    return page(request, db, user, "admin/customer_detail.html", ctx, "customers")


@router.post("/customers/{user_id}/toggle-active")
def customer_toggle_active(
    request: Request,
    user_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Block or unblock an account."""
    customer = get_or_404(db, User, user_id)
    if customer.id == user.id:
        flash(request, "You can't block your own account.", "error")
    else:
        customer.is_active = not customer.is_active
        db.commit()
        flash(request, f"{customer.name} is now {'active' if customer.is_active else 'blocked'}.")
    return back(f"/admin/customers/{user_id}")


@router.post("/customers/{user_id}/toggle-admin")
def customer_toggle_admin(
    request: Request,
    user_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Grant or remove staff access."""
    customer = get_or_404(db, User, user_id)
    if customer.id == user.id:
        flash(request, "You can't remove your own staff access.", "error")
    else:
        customer.is_admin = not customer.is_admin
        db.commit()
        flash(request, f"{customer.name} {'now has' if customer.is_admin else 'no longer has'} "
                       "staff access.")  # fmt: skip
    return back(f"/admin/customers/{user_id}")


# --------------------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------------------


@router.get("/reviews")
def reviews(request: Request, db: DB, user: Admin) -> Response:
    """Review moderation."""
    p = request.query_params
    stmt = select(Review).options(selectinload(Review.product))
    if rating := to_int(p.get("rating")):
        stmt = stmt.where(Review.rating == rating)
    if p.get("status") in {"published", "hidden"}:
        stmt = stmt.where(Review.status == p["status"])
    if pid := to_int(p.get("product")):
        stmt = stmt.where(Review.product_id == pid)
    if q := (p.get("q") or "").strip().lower():
        stmt = stmt.where(or_(func.lower(Review.body).like(f"%{q}%"),
                              func.lower(Review.title).like(f"%{q}%")))  # fmt: skip
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pg = paginate(total, to_int(p.get("page"), 1) or 1)
    rows = list(db.scalars(stmt.order_by(Review.created_at.desc()).offset(pg["offset"])
                           .limit(PER_PAGE)))  # fmt: skip
    dist = dict(db.execute(select(Review.rating, func.count()).group_by(Review.rating)).all())
    ctx = {
        "reviews": rows, "pg": pg, "filters": dict(p), "dist": dist,
        "products": list(db.scalars(select(Product).order_by(Product.name))),
        "qs": lambda **kw: qs(request, **kw),
    }  # fmt: skip
    return page(request, db, user, "admin/reviews.html", ctx, "reviews")


@router.post("/reviews/{review_id}/toggle")
async def review_toggle(request: Request, review_id: int, db: DB) -> Response:
    """Hide or publish a review."""
    review = get_or_404(db, Review, review_id)
    review.status = "hidden" if review.status == "published" else "published"
    db.flush()
    refresh_rating(db, review.product)
    db.commit()
    flash(request, f"Review {'hidden' if review.status == 'hidden' else 'published'}.")
    form = await request.form()
    return back(str(form.get("next") or "/admin/reviews"))


@router.post("/reviews/{review_id}/delete")
async def review_delete(request: Request, review_id: int, db: DB) -> Response:
    """Delete a review permanently."""
    review = get_or_404(db, Review, review_id)
    product = review.product
    db.delete(review)
    db.flush()
    refresh_rating(db, product)
    db.commit()
    flash(request, "Review deleted.")
    form = await request.form()
    return back(str(form.get("next") or "/admin/reviews"))


# --------------------------------------------------------------------------------------
# Coupons
# --------------------------------------------------------------------------------------


@router.get("/coupons")
def coupons(request: Request, db: DB, user: Admin) -> Response:
    """Coupon list."""
    rows = list(
        db.scalars(select(Coupon).order_by(Coupon.is_active.desc(), Coupon.created_at.desc()))
    )
    ctx = {"coupons": rows, "now": datetime.now(UTC), "aware": analytics.aware}
    return page(request, db, user, "admin/coupons.html", ctx, "coupons")


def _coupon_values(c: Coupon | None, request: Request | None = None) -> dict[str, Any]:
    if c is None:
        p = request.query_params if request else {}
        return {
            "code": p.get("code", ""),
            "description": p.get("description", ""),
            "kind": p.get("kind", "percent"),
            "value": p.get("value", ""),
            "min_order": 0,
            "max_discount": 0,
            "usage_limit": 0,
            "expires_at": "",
            "is_active": True,
        }
    exp = analytics.aware(c.expires_at)
    return {"code": c.code, "description": c.description, "kind": c.kind, "value": c.value,
            "min_order": c.min_order, "max_discount": c.max_discount,
            "usage_limit": c.usage_limit, "is_active": c.is_active,
            "expires_at": exp.astimezone(IST).strftime("%Y-%m-%d") if exp else ""}  # fmt: skip


def _parse_coupon(db: Session, form: Any, coupon: Coupon | None) -> tuple[dict, dict]:
    v: dict[str, Any] = {
        "code": re.sub(r"[^A-Z0-9]", "", str(form.get("code", "")).upper())[:30],
        "description": str(form.get("description", "")).strip()[:200],
        "kind": "flat" if form.get("kind") == "flat" else "percent",
        "value": to_int(form.get("value")),
        "min_order": max(0, to_int(form.get("min_order"), 0) or 0),
        "max_discount": max(0, to_int(form.get("max_discount"), 0) or 0),
        "usage_limit": max(0, to_int(form.get("usage_limit"), 0) or 0),
        "expires_at": str(form.get("expires_at", "")).strip(),
        "is_active": form.get("is_active") == "on",
    }
    errors: dict[str, str] = {}
    if len(v["code"]) < 3:
        errors["code"] = "Use 3-30 letters or digits."
    elif db.scalar(
        select(Coupon.id).where(
            Coupon.code == v["code"], Coupon.id != (coupon.id if coupon else -1)
        )
    ):
        errors["code"] = "That code already exists."
    if v["value"] is None or v["value"] <= 0:
        errors["value"] = "Enter a discount value."
    elif v["kind"] == "percent" and not 1 <= v["value"] <= 90:
        errors["value"] = "Percent discounts must be between 1 and 90."
    if v["expires_at"] and parse_day(v["expires_at"]) is None:
        errors["expires_at"] = "Use a valid date."
    return v, errors


def _apply_coupon(c: Coupon, v: dict[str, Any]) -> None:
    for k in ("code", "description", "kind", "value", "min_order", "max_discount",
              "usage_limit", "is_active"):  # fmt: skip
        setattr(c, k, v[k])
    c.expires_at = parse_day(v["expires_at"], end=True) if v["expires_at"] else None


@router.get("/coupons/new")
def coupon_new(request: Request, db: DB, user: Admin) -> Response:
    """Blank coupon form (accepts ?code=&value=&kind=&description= prefill)."""
    ctx = {"coupon": None, "v": _coupon_values(None, request), "errors": {}}
    return page(request, db, user, "admin/coupon_form.html", ctx, "coupons")


@router.post("/coupons/new")
async def coupon_create(request: Request, db: DB, user: Admin) -> Response:
    """Create a coupon."""
    form = await request.form()
    v, errors = _parse_coupon(db, form, None)
    if errors:
        ctx = {"coupon": None, "v": v, "errors": errors}
        return page(request, db, user, "admin/coupon_form.html", ctx, "coupons", 422)
    c = Coupon()
    _apply_coupon(c, v)
    db.add(c)
    db.commit()
    flash(request, f"Coupon {c.code} created.")
    return back("/admin/coupons")


@router.get("/coupons/{coupon_id}")
def coupon_edit(
    request: Request,
    coupon_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Edit a coupon."""
    c = get_or_404(db, Coupon, coupon_id)
    ctx = {"coupon": c, "v": _coupon_values(c), "errors": {}}
    return page(request, db, user, "admin/coupon_form.html", ctx, "coupons")


@router.post("/coupons/{coupon_id}")
async def coupon_update(
    request: Request,
    coupon_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Save coupon edits."""
    c = get_or_404(db, Coupon, coupon_id)
    form = await request.form()
    v, errors = _parse_coupon(db, form, c)
    if errors:
        ctx = {"coupon": c, "v": v, "errors": errors}
        return page(request, db, user, "admin/coupon_form.html", ctx, "coupons", 422)
    _apply_coupon(c, v)
    db.commit()
    flash(request, f"Coupon {c.code} saved.")
    return back("/admin/coupons")


@router.post("/coupons/{coupon_id}/delete")
def coupon_delete(request: Request, coupon_id: int, db: DB) -> Response:
    """Delete a coupon (past orders keep the code text)."""
    c = get_or_404(db, Coupon, coupon_id)
    db.delete(c)
    db.commit()
    flash(request, f"Coupon {c.code} deleted.")
    return back("/admin/coupons")


# --------------------------------------------------------------------------------------
# AI crew (ShopCrew on Ollama)
# --------------------------------------------------------------------------------------


def _crew_ready_products(db: Session) -> list[Product]:
    return list(db.scalars(
        select(Product)
        .where(exists().where(Review.product_id == Product.id, Review.status == "published"),
               exists().where(CompetitorPrice.product_id == Product.id))
        .order_by(Product.name)
    ))  # fmt: skip


def _duration(run: CrewRun) -> float | None:
    start = analytics.aware(run.started_at)
    end = analytics.aware(run.finished_at) or (
        datetime.now(UTC) if run.status == "running" else None
    )
    return (end - start).total_seconds() if start and end else None


@router.get("/ai")
def ai_home(request: Request, db: DB, user: Admin) -> Response:
    """AI Crew launcher and run history."""
    _status_cache["value"] = None  # always fresh on this page
    runs = list(db.scalars(
        select(CrewRun).options(selectinload(CrewRun.product))
        .order_by(CrewRun.id.desc()).limit(30)
    ))  # fmt: skip
    ctx = {
        "products": _crew_ready_products(db),
        "runs": runs,
        "duration": _duration,
        "stages": [(k, *ai_svc.STAGE_LABELS[k]) for k in ai_svc.STAGE_KEYS],
        "selected": to_int(request.query_params.get("product")),
    }
    return page(request, db, user, "admin/ai.html", ctx, "ai")


@router.post("/ai/run")
async def ai_run(request: Request, db: DB) -> Response:
    """Queue a crew run."""
    form = await request.form()
    product = db.get(Product, to_int(form.get("product_id")) or -1)
    if product is None:
        flash(request, "Choose a product to analyse.", "error")
        return back("/admin/ai")
    process = "hierarchical" if form.get("process") == "hierarchical" else "sequential"
    try:
        run = ai_svc.start_run(db, product, process)
    except ValueError as err:
        flash(request, str(err), "error")
        return back("/admin/ai")
    return back(f"/admin/ai/runs/{run.id}")


def _run_or_404(db: Session, run_id: int) -> CrewRun:
    run = db.scalar(
        select(CrewRun).where(CrewRun.id == run_id)
        .options(selectinload(CrewRun.product).selectinload(Product.competitor_prices))
    )  # fmt: skip
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/ai/runs/{run_id}")
def ai_run_page(
    request: Request,
    run_id: int,
    db: DB,
    user: Admin,
) -> Response:
    """Live progress and results of one run."""
    run = _run_or_404(db, run_id)
    queued_ahead = 0
    if run.status == "queued":
        queued_ahead = db.scalar(select(func.count(CrewRun.id)).where(
            CrewRun.status.in_(["queued", "running"]), CrewRun.id < run.id)) or 0  # fmt: skip
    ctx = {
        "run": run,
        "r": run.result or {},
        "stages": [(k, *ai_svc.STAGE_LABELS[k]) for k in ai_svc.STAGE_KEYS],
        "icons": {"review_task": "⭐", "pricing_task": "$", "seo_task": "¶", "marketing_task": "↗"},
        "duration": _duration(run),
        "queued_ahead": queued_ahead,
        "competitors": sorted(run.product.competitor_prices, key=lambda c: c.price),
    }
    return page(request, db, user, "admin/ai_run.html", ctx, "ai")


@router.get("/ai/runs/{run_id}/status.json")
def ai_run_status(run_id: int, db: DB) -> JSONResponse:
    """Polling endpoint for the run page."""
    run = db.get(CrewRun, run_id)
    if run is None:
        return JSONResponse({"error": "Run not found"}, 404)
    db.refresh(run)
    return JSONResponse({
        "status": run.status,
        "stages_done": run.stages_done or [],
        "current_stage": run.current_stage,
        "log": (run.log or [])[-40:],
        "error": run.error,
        "elapsed": round(_duration(run) or 0, 1),
    })  # fmt: skip


@router.post("/ai/runs/{run_id}/apply")
async def ai_apply(request: Request, run_id: int, db: DB) -> Response:
    """Copy SEO copy, recommended price or review insights onto the product."""
    run = _run_or_404(db, run_id)
    form = await request.form()
    try:
        flash(request, ai_svc.apply_result(db, run, str(form.get("target", ""))))
    except ValueError as err:
        flash(request, str(err), "error")
    return back(f"/admin/ai/runs/{run_id}#apply")


# --------------------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------------------


def _report_range(request: Request) -> tuple[datetime, datetime, str, str]:
    today = datetime.now(IST).date()
    p = request.query_params
    start_s = p.get("from") or (today - timedelta(days=29)).isoformat()
    end_s = p.get("to") or today.isoformat()
    start = parse_day(start_s) or parse_day((today - timedelta(days=29)).isoformat())
    end = parse_day(end_s, end=True) or datetime.now(UTC)
    return start, end, start_s, end_s  # type: ignore[return-value]


@router.get("/reports")
def reports(request: Request, db: DB, user: Admin) -> Response:
    """Sales and GST reports."""
    start, end, start_s, end_s = _report_range(request)
    ctx = {
        "report": analytics.sales_report(db, start, end),
        "gst": analytics.gst_summary(db),
        "start": start_s,
        "end": end_s,
        "tab": request.query_params.get("tab", "sales"),
    }
    return page(request, db, user, "admin/reports.html", ctx, "reports")


@router.get("/reports/sales.csv")
def reports_sales_csv(request: Request, db: DB) -> StreamingResponse:
    """Download the daily / category / product sales report."""
    start, end, start_s, end_s = _report_range(request)
    rep = analytics.sales_report(db, start, end)
    view = request.query_params.get("view", "daily")
    if view == "category":
        rows = [[c["name"], c["units"], c["revenue"]] for c in rep["categories"]]
        header = ["Category", "Units", "Revenue (USD)"]
    elif view == "product":
        rows = [[p["name"], p["units"], p["revenue"]] for p in rep["products"]]
        header = ["Product", "Units", "Revenue (USD)"]
    else:
        rows = [[r["date"].isoformat(), r["orders"], r["units"], r["gross"], r["discount"],
                 r["shipping"], r["net"]] for r in rep["rows"]]  # fmt: skip
        header = ["Date", "Orders", "Units", "Gross", "Discount", "Shipping & COD", "Net"]
    return csv_response(f"northcart-sales-{view}-{start_s}-to-{end_s}.csv", header, rows)


@router.get("/reports/gst.csv")
def reports_gst_csv(db: DB) -> StreamingResponse:
    """Download the monthly GST summary."""
    rows = [[m["month"], m["orders"], m["gross"], m["taxable"], m["cgst"], m["sgst"], m["igst"]]
            for m in analytics.gst_summary(db)]  # fmt: skip
    header = ["Month", "Orders", "Gross (incl. GST)", "Taxable value", "CGST", "SGST", "IGST"]
    return csv_response("northcart-gst-summary.csv", header, rows)


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------

SETTING_FIELDS = [
    ("announcement", "Announcement bar", "Shown above the header on every store page."),
    ("hero_title", "Home hero title", ""),
    ("hero_subtitle", "Home hero subtitle", ""),
    ("support_email", "Support email", ""),
    ("support_phone", "Support phone", ""),
    ("company_name", "Legal company name", "Printed on invoices and the footer."),
    ("company_address", "Registered address", ""),
    ("gstin", "GSTIN", "15-character GST identification number."),
]


@router.get("/settings")
def settings_page(request: Request, db: DB, user: Admin) -> Response:
    """Store settings."""
    ctx = {"fields": SETTING_FIELDS, "values": settings_svc.all_settings(db),
           "model": ai_svc.configured_model(), "errors": {}}  # fmt: skip
    return page(request, db, user, "admin/settings.html", ctx, "settings")


@router.post("/settings")
async def settings_save(request: Request, db: DB, user: Admin) -> Response:
    """Save store settings."""
    form = await request.form()
    values = {k: str(form.get(k, "")).strip()[:300] for k, _, _ in SETTING_FIELDS}
    errors = {}
    if values["gstin"] and not re.fullmatch(r"[0-9]{2}[A-Z0-9]{13}", values["gstin"].upper()):
        errors["gstin"] = "A GSTIN has 15 characters, starting with a 2-digit state code."
    if values["support_email"] and "@" not in values["support_email"]:
        errors["support_email"] = "Enter a valid email address."
    if errors:
        ctx = {"fields": SETTING_FIELDS, "values": values, "model": ai_svc.configured_model(),
               "errors": errors}  # fmt: skip
        return page(request, db, user, "admin/settings.html", ctx, "settings", 422)
    values["gstin"] = values["gstin"].upper()
    settings_svc.set_many(db, values)
    flash(request, "Settings saved.")
    return back("/admin/settings")


__all__ = ["router", "PAYMENT_METHODS"]
