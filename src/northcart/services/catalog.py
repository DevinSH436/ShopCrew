"""Catalogue queries: search, filters, facets, related products, rating stats."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from northcart.models import Category, Product, Review

SORTS = {
    "relevance": "Relevance",
    "popular": "Popularity",
    "price_asc": "Price: Low to High",
    "price_desc": "Price: High to Low",
    "rating": "Avg. Customer Rating",
    "newest": "Newest Arrivals",
    "discount": "Discount",
}
PRICE_BUCKETS = [(0, 10), (10, 25), (25, 50), (50, 100), (100, None)]


@dataclass
class SearchParams:
    """Everything the listing page can filter and sort by."""

    q: str = ""
    category: str = ""
    brands: list[str] = field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = None
    min_rating: int | None = None
    in_stock: bool = False
    discount: int | None = None
    sort: str = "relevance"
    page: int = 1
    per_page: int = 12


@dataclass
class SearchResult:
    """A page of products plus the facets for the sidebar."""

    items: list[Product]
    total: int
    page: int
    pages: int
    brands: list[tuple[str, int]]
    categories: list[tuple[Category, int]]


def _base_query(params: SearchParams):  # type: ignore[no-untyped-def]
    stmt = select(Product).where(Product.is_active.is_(True))
    if params.q:
        terms = [t for t in params.q.lower().split() if t]
        for term in terms:
            like = f"%{term}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.name).like(like),
                    func.lower(Product.brand).like(like),
                    func.lower(Product.short_description).like(like),
                    func.lower(Product.description).like(like),
                    Product.category.has(func.lower(Category.name).like(like)),
                )
            )
    if params.category:
        stmt = stmt.where(Product.category.has(Category.slug == params.category))
    return stmt


def search_products(db: Session, params: SearchParams) -> SearchResult:
    """Filter, sort and paginate the catalogue."""
    base = _base_query(params)

    # Facets are computed before brand/price filters so the sidebar keeps its options.
    brand_rows = db.execute(
        select(Product.brand, func.count(Product.id))
        .where(Product.id.in_(select(base.subquery().c.id)))
        .group_by(Product.brand)
        .order_by(Product.brand)
    ).all()
    no_cat = SearchParams(q=params.q)
    cat_rows = db.execute(
        select(Category, func.count(Product.id))
        .join(Product, Product.category_id == Category.id)
        .where(Product.id.in_(select(_base_query(no_cat).subquery().c.id)))
        .group_by(Category.id)
        .order_by(Category.sort_order)
    ).all()

    stmt = base
    if params.brands:
        stmt = stmt.where(Product.brand.in_(params.brands))
    if params.min_price is not None:
        stmt = stmt.where(Product.price >= params.min_price)
    if params.max_price is not None:
        stmt = stmt.where(Product.price <= params.max_price)
    if params.min_rating:
        stmt = stmt.where(Product.rating_avg >= params.min_rating)
    if params.in_stock:
        stmt = stmt.where(Product.stock > 0)
    if params.discount:
        stmt = stmt.where((Product.mrp - Product.price) * 100 >= Product.mrp * params.discount)

    order = {
        "popular": [Product.sold_count.desc()],
        "price_asc": [Product.price.asc()],
        "price_desc": [Product.price.desc()],
        "rating": [Product.rating_avg.desc(), Product.rating_count.desc()],
        "newest": [Product.created_at.desc()],
        "discount": [((Product.mrp - Product.price) * 1.0 / Product.mrp).desc()],
    }.get(params.sort, [Product.is_featured.desc(), Product.sold_count.desc()])

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pages = max(1, -(-total // params.per_page))
    page = min(max(1, params.page), pages)
    items = list(
        db.scalars(
            stmt.options(selectinload(Product.images), selectinload(Product.category))
            .order_by(*order, Product.id)
            .offset((page - 1) * params.per_page)
            .limit(params.per_page)
        )
    )
    return SearchResult(
        items=items,
        total=total,
        page=page,
        pages=pages,
        brands=[(b, n) for b, n in brand_rows],
        categories=[(c, n) for c, n in cat_rows],
    )


def suggest(db: Session, q: str, limit: int = 6) -> list[Product]:
    """Autocomplete suggestions for the search box."""
    if len(q.strip()) < 2:
        return []
    result = search_products(db, SearchParams(q=q, per_page=limit, sort="popular"))
    return result.items


def get_by_slug(db: Session, slug: str) -> Product | None:
    """Active product by slug, with images and category loaded."""
    return db.scalar(
        select(Product)
        .where(Product.slug == slug, Product.is_active.is_(True))
        .options(selectinload(Product.images), selectinload(Product.category))
    )


def related(db: Session, product: Product, limit: int = 8) -> list[Product]:
    """Other products in the same category, best sellers first."""
    return list(
        db.scalars(
            select(Product)
            .where(
                Product.category_id == product.category_id,
                Product.id != product.id,
                Product.is_active.is_(True),
            )
            .order_by(Product.sold_count.desc())
            .limit(limit)
        )
    )


def featured(db: Session, limit: int = 8) -> list[Product]:
    """Featured products for the home page."""
    return list(
        db.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.is_featured.is_(True))
            .order_by(Product.sold_count.desc())
            .limit(limit)
        )
    )


def best_sellers(db: Session, limit: int = 10) -> list[Product]:
    """Most sold products."""
    return list(
        db.scalars(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.sold_count.desc())
            .limit(limit)
        )
    )


def top_deals(db: Session, limit: int = 10) -> list[Product]:
    """Biggest discounts off MRP."""
    return list(
        db.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.stock > 0)
            .order_by(((Product.mrp - Product.price) * 1.0 / Product.mrp).desc())
            .limit(limit)
        )
    )


def categories(db: Session) -> list[Category]:
    """All categories in display order."""
    return list(db.scalars(select(Category).order_by(Category.sort_order, Category.name)))


def rating_histogram(db: Session, product_id: int) -> dict[int, int]:
    """Count of published reviews per star (5..1)."""
    rows = db.execute(
        select(Review.rating, func.count())
        .where(Review.product_id == product_id, Review.status == "published")
        .group_by(Review.rating)
    ).all()
    counts = {star: 0 for star in range(5, 0, -1)}
    for rating, n in rows:
        counts[int(rating)] = n
    return counts


def refresh_rating(db: Session, product: Product) -> None:
    """Recompute ``rating_avg`` and ``rating_count`` from published reviews."""
    avg, count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.product_id == product.id, Review.status == "published"
        )
    ).one()
    product.rating_avg = round(float(avg or 0), 2)
    product.rating_count = int(count or 0)
