"""Storefront browsing: home, listings, search, product pages, info pages, SEO files."""

# FastAPI's Depends()/Query() defaults are the framework idiom.

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from northcart.db import get_db
from northcart.models import Category, Order, OrderItem, Product, Review, User
from northcart.services import catalog
from northcart.services import orders as order_svc
from northcart.web.deps import current_user, flash
from northcart.web.pages import PAGES
from northcart.web.templating import STORE_TZ, render, usd

router = APIRouter()

RECENT_KEY = "recent"
REVIEWS_PER_PAGE = 10

# First three digits of a ZIP code -> city, for friendly delivery messages.
ZIP_CITIES = {
    "100": "New York", "112": "Brooklyn", "021": "Boston", "191": "Philadelphia",
    "200": "Washington", "303": "Atlanta", "331": "Miami", "432": "Columbus",
    "441": "Cleveland", "452": "Cincinnati", "482": "Detroit", "606": "Chicago",
    "554": "Minneapolis", "631": "St. Louis", "750": "Dallas", "770": "Houston",
    "787": "Austin", "802": "Denver", "850": "Phoenix", "891": "Las Vegas",
    "900": "Los Angeles", "921": "San Diego", "941": "San Francisco", "972": "Portland",
    "981": "Seattle", "282": "Charlotte", "372": "Nashville",
}  # fmt: skip


def _remember(request: Request, slug: str) -> None:
    recent = [s for s in request.session.get(RECENT_KEY, []) if s != slug]
    request.session[RECENT_KEY] = [slug, *recent][:12]


def recently_viewed(request: Request, db: Session, exclude: str = "") -> list[Product]:
    """Products the visitor looked at recently (kept in the session)."""
    slugs = [s for s in request.session.get(RECENT_KEY, []) if s != exclude][:8]
    if not slugs:
        return []
    rows = {p.slug: p for p in db.scalars(select(Product).where(Product.slug.in_(slugs)))}
    return [rows[s] for s in slugs if s in rows and rows[s].is_active]


def _buy_again(db: Session, user: User | None) -> list[Product]:
    if user is None:
        return []
    ids = db.scalars(
        select(OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.user_id == user.id, Order.status == "delivered")
        .group_by(OrderItem.product_id)
        .order_by(func.max(Order.created_at).desc())
        .limit(8)
    ).all()
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}
    return [products[i] for i in ids if i in products and products[i].is_active]


@router.get("/")
def home(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    """Home page."""
    top_rated = list(
        db.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.rating_count >= 10)
            .order_by(Product.rating_avg.desc())
            .limit(10)
        )
    )
    brands = db.execute(
        select(Product.brand, func.count(Product.id))
        .where(Product.is_active.is_(True))
        .group_by(Product.brand)
        .order_by(func.sum(Product.sold_count).desc())
    ).all()
    cat_thumbs: dict[int, Product | None] = {}
    for c in catalog.categories(db):
        cat_thumbs[c.id] = db.scalar(
            select(Product)
            .where(Product.category_id == c.id, Product.is_active.is_(True))
            .order_by(Product.sold_count.desc())
            .limit(1)
        )
    deal_ends = datetime.now(STORE_TZ).replace(hour=23, minute=59, second=59, microsecond=0)
    return render(
        request,
        db,
        "shop/home.html",
        {
            "deals": catalog.top_deals(db, 12),
            "featured": catalog.featured(db, 8),
            "best": catalog.best_sellers(db, 10),
            "top_rated": top_rated,
            "brands": brands,
            "cat_thumbs": cat_thumbs,
            "buy_again": _buy_again(db, user),
            "recent": recently_viewed(request, db),
            "deal_ends": deal_ends.isoformat(),
        },
        user=user,
    )


def _url(base: str, items: list[tuple[str, str]]) -> str:
    query = urlencode(items)
    return base + (f"?{query}" if query else "")


def _listing(
    request: Request,
    db: Session,
    user: User | None,
    params: catalog.SearchParams,
    title: str,
    category: Category | None = None,
    base_path: str = "/search",
):
    result = catalog.search_products(db, params)
    qp = list(request.query_params.multi_items())

    def without(keys: set[str], value: str | None = None) -> str:
        kept = [
            (k, v)
            for k, v in qp
            if k != "page" and not (k in keys and (value is None or v == value))
        ]
        return _url(base_path, kept)

    def page_url(n: int) -> str:
        return _url(base_path, [(k, v) for k, v in qp if k != "page"] + [("page", str(n))])

    chips: list[tuple[str, str]] = []
    if params.q and base_path == "/search":
        chips.append((f"“{params.q}”", without({"q"})))
    for b in params.brands:
        chips.append((b, without({"brand"}, b)))
    if params.min_price is not None or params.max_price is not None:
        if params.min_price is None:
            label = f"Under ${usd(params.max_price)}"
        elif params.max_price is None:
            label = f"${usd(params.min_price)} & above"
        else:
            label = f"${usd(params.min_price)} – ${usd(params.max_price)}"
        chips.append((label, without({"min_price", "max_price"})))
    if params.min_rating:
        chips.append((f"{params.min_rating}★ & up", without({"rating"})))
    if params.discount and base_path != "/deals":
        chips.append((f"{params.discount}% off or more", without({"discount"})))
    if params.in_stock and base_path != "/deals":
        chips.append(("In stock only", without({"in_stock"})))

    first = (result.page - 1) * params.per_page + 1 if result.total else 0
    last = min(result.page * params.per_page, result.total)
    clear = _url(base_path, [("q", params.q)] if params.q and base_path == "/search" else [])
    return render(
        request,
        db,
        "shop/listing.html",
        {
            "result": result,
            "params": params,
            "title": title,
            "category": category,
            "base_path": base_path,
            "sorts": catalog.SORTS,
            "price_buckets": catalog.PRICE_BUCKETS,
            "chips": chips,
            "clear_url": clear,
            "page_url": page_url,
            "first": first,
            "last": last,
            "suggestions": catalog.best_sellers(db, 6) if not result.total else [],
        },
        user=user,
    )


def _num(v: str) -> int | None:
    v = (v or "").strip().replace(",", "")
    return int(v) if v.isdigit() else None


def _params(
    q: str,
    category: str,
    brand: list[str],
    min_price: str,
    max_price: str,
    rating: str,
    in_stock: str,
    discount: str,
    sort: str,
    page: int,
) -> catalog.SearchParams:
    return catalog.SearchParams(
        q=q.strip()[:100],
        category=category,
        brands=[b for b in brand if b],
        min_price=_num(min_price),
        max_price=_num(max_price),
        min_rating=_num(rating),
        in_stock=in_stock in {"1", "on", "true"},
        discount=_num(discount),
        sort=sort if sort in catalog.SORTS else "relevance",
        page=max(1, page),
    )


@router.get("/search")
def search(
    request: Request,
    q: str = "",
    category: str = "",
    brand: list[str] = Query(default=[]),
    min_price: str = "",
    max_price: str = "",
    rating: str = "",
    in_stock: str = "",
    discount: str = "",
    sort: str = "relevance",
    page: int = 1,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Search results with filters."""
    params = _params(
        q, category, brand, min_price, max_price, rating, in_stock, discount, sort, page
    )
    cat = db.scalar(select(Category).where(Category.slug == category)) if category else None
    title = f"Results for “{params.q}”" if params.q else (cat.name if cat else "All products")
    return _listing(request, db, user, params, title, cat)


@router.get("/c/{slug}")
def category_page(
    slug: str,
    request: Request,
    brand: list[str] = Query(default=[]),
    min_price: str = "",
    max_price: str = "",
    rating: str = "",
    in_stock: str = "",
    discount: str = "",
    sort: str = "relevance",
    page: int = 1,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Category listing."""
    cat = db.scalar(select(Category).where(Category.slug == slug))
    if cat is None:
        raise HTTPException(404, "Category not found")
    params = _params("", slug, brand, min_price, max_price, rating, in_stock, discount, sort, page)
    return _listing(request, db, user, params, cat.name, cat, base_path=f"/c/{slug}")


@router.get("/deals")
def deals(
    request: Request,
    brand: list[str] = Query(default=[]),
    rating: str = "",
    sort: str = "discount",
    page: int = 1,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Today's deals: in-stock products at 10%+ off, biggest discount first."""
    params = _params("", "", brand, "", "", rating, "1", "10", sort, page)
    return _listing(request, db, user, params, "Today's Deals", base_path="/deals")


@router.get("/p/{slug}")
def product_page(
    slug: str,
    request: Request,
    star: int = 0,
    rsort: str = "helpful",
    rpage: int = 1,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Product detail page."""
    product = catalog.get_by_slug(db, slug)
    if product is None:
        raise HTTPException(404, "Product not found")
    _remember(request, slug)
    hist = catalog.rating_histogram(db, product.id)
    stmt = select(Review).where(Review.product_id == product.id, Review.status == "published")
    if 1 <= star <= 5:
        stmt = stmt.where(Review.rating == star)
    order = (
        [Review.created_at.desc()]
        if rsort == "newest"
        else [Review.helpful_count.desc(), Review.created_at.desc()]
    )
    total_reviews = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rpages = max(1, -(-total_reviews // REVIEWS_PER_PAGE))
    rpage = min(max(1, rpage), rpages)
    reviews = list(
        db.scalars(
            stmt.order_by(*order).offset((rpage - 1) * REVIEWS_PER_PAGE).limit(REVIEWS_PER_PAGE)
        )
    )
    my_review = None
    if user:
        my_review = db.scalar(
            select(Review).where(Review.product_id == product.id, Review.user_id == user.id)
        )
    related = catalog.related(db, product, 10)
    together = [p for p in related if p.in_stock][:2]
    return render(
        request,
        db,
        "shop/product.html",
        {
            "p": product,
            "hist": hist,
            "hist_total": sum(hist.values()),
            "reviews": reviews,
            "review_total": total_reviews,
            "rpage": rpage,
            "rpages": rpages,
            "star": star,
            "rsort": rsort,
            "my_review": my_review,
            "related": related,
            "together": together,
            "together_total": product.price + sum(p.price for p in together),
            "recent": recently_viewed(request, db, exclude=slug),
            "sold_month": max(0, product.sold_count // 4 // 10 * 10),
            "emi": product.price // 4 if product.price >= 45 else 0,
        },
        user=user,
    )


@router.get("/api/suggest")
def api_suggest(q: str = "", db: Session = Depends(get_db)) -> JSONResponse:
    """Search-box autocomplete."""
    items = [
        {"name": p.name, "url": f"/p/{p.slug}", "thumb": p.thumb, "price": usd(p.price)}
        for p in catalog.suggest(db, q[:80])
    ]
    return JSONResponse({"items": items})


@router.get("/api/delivery")
def api_delivery(zip_code: str = "") -> JSONResponse:
    """Delivery estimate for a ZIP code."""
    zip_code = zip_code.strip()
    if not order_svc.valid_zip(zip_code):
        return JSONResponse(
            {"ok": False, "message": "Please enter a valid 5-digit ZIP code."}, status_code=400
        )
    when = order_svc.delivery_estimate(zip_code).astimezone(STORE_TZ)
    label = when.strftime("%A, %b %d").replace(" 0", " ")
    return JSONResponse(
        {
            "ok": True,
            "city": ZIP_CITIES.get(zip_code[:3], ""),
            "days": order_svc.delivery_days(zip_code),
            "date_label": label,
            "message": f"Delivery by {label}",
            "cod": True,
        }
    )


@router.get("/pages/{slug}")
def info_page(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Static information pages (about, help, policies...)."""
    page = PAGES.get(slug)
    if page is None:
        raise HTTPException(404, "Page not found")
    return render(
        request, db, "shop/page.html", {"page": page, "slug": slug, "pages": PAGES}, user=user
    )


@router.post("/pages/contact")
async def contact_submit(request: Request) -> RedirectResponse:
    """Contact form (demo: acknowledges without sending anything)."""
    form = await request.form()
    name = str(form.get("name") or "").strip()
    message = str(form.get("message") or "").strip()
    if not name or len(message) < 10:
        flash(request, "Please tell us your name and a message of at least 10 characters.", "error")
    else:
        ticket = datetime.now(STORE_TZ).strftime("%y%m%d%H%M")
        flash(
            request,
            f"Thanks {name.split()[0]}! Ticket #{ticket} created. We reply within 24 hours.",
        )
    return RedirectResponse("/pages/contact", status_code=303)


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request) -> PlainTextResponse:
    """robots.txt."""
    base = str(request.base_url).rstrip("/")
    body = (
        "User-agent: *\nDisallow: /admin\nDisallow: /account\nDisallow: /cart\n"
        f"Disallow: /checkout\n\nSitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, db: Session = Depends(get_db)) -> Response:
    """XML sitemap of categories and products."""
    base = str(request.base_url).rstrip("/")
    urls = [f"{base}/", f"{base}/deals"] + [f"{base}/c/{c.slug}" for c in catalog.categories(db)]
    rows = db.execute(
        select(Product.slug, Product.updated_at).where(Product.is_active.is_(True))
    ).all()
    entries = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    entries += "".join(
        f"<url><loc>{escape(base)}/p/{escape(slug)}</loc>"
        f"<lastmod>{(updated or datetime.now(UTC)).date().isoformat()}</lastmod></url>"
        for slug, updated in rows
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
    )
    return Response(xml, media_type="application/xml")
