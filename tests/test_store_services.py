"""Tests for the Northcart store's business logic (no web layer, no LLM)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from northcart import db as dbmod
from northcart import seed
from northcart.art import DRAWINGS, product_svg
from northcart.models import Address, CompetitorPrice, Order, Product, Review, User
from northcart.security import hash_password, verify_password
from northcart.services import cart as cart_svc
from northcart.services import catalog
from northcart.services import orders as order_svc
from northcart.web.templating import usd


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Seed one database per test session; each test gets a fresh copy of it."""
    path = tmp_path_factory.mktemp("store") / "template.db"
    dbmod.configure(f"sqlite:///{path}")
    seed.run(reset=True)
    dbmod.engine().dispose()
    return path


@pytest.fixture
def db(seeded_template: Path, tmp_path: Path) -> Iterator[Session]:
    """A session on a private copy of the seeded store database."""
    path = tmp_path / "store.db"
    shutil.copy(seeded_template, path)
    dbmod.configure(f"sqlite:///{path}")
    session = dbmod.SessionLocal()
    try:
        yield session
    finally:
        session.close()
        dbmod.engine().dispose()


def _customer(db: Session) -> User:
    return db.scalar(select(User).where(User.email == "customer@northcart.test"))  # type: ignore[return-value]


def _product(db: Session, slug: str) -> Product:
    return db.scalar(select(Product).where(Product.slug == slug))  # type: ignore[return-value]


# ---------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (999, "999"), (1000, "1,000"), (123456, "123,456"), (12345678, "12,345,678")],
)
def test_usd_uses_us_grouping(value: int, expected: str) -> None:
    assert usd(value) == expected


def test_password_hash_roundtrip() -> None:
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "not-a-hash")


@pytest.mark.parametrize("kind", sorted(DRAWINGS))
def test_every_art_kind_renders_valid_svg(kind: str) -> None:
    for view in range(4):
        svg = product_svg(kind, "#1e3a8a", view, "Brand")
        assert svg.startswith("<svg") and svg.endswith("</svg>")


# ---------------------------------------------------------------------------- seed


def test_seed_creates_a_complete_catalogue(db: Session) -> None:
    products = db.scalars(select(Product)).all()
    assert len(products) >= 25
    for p in products:
        assert p.rating_count > 0, f"{p.slug} has no reviews"
        assert len(p.competitor_prices) >= 4, f"{p.slug} needs competitor prices for the crew"
        assert p.mrp >= p.price > 0
        assert p.art_kind in DRAWINGS
    assert db.scalar(select(func.count(Order.id))) > 300
    assert db.scalar(select(User).where(User.is_admin.is_(True))) is not None


def test_seed_keeps_shopcrew_sample_reviews(db: Session) -> None:
    earbuds = _product(db, "pulsebeat-pro-wireless-earbuds")
    texts = {r.body for r in earbuds.reviews}
    assert any("Battery life is insane" in t for t in texts)


# ---------------------------------------------------------------------------- catalogue


def test_search_matches_name_brand_and_category(db: Session) -> None:
    by_name = catalog.search_products(db, catalog.SearchParams(q="earbuds"))
    assert "pulsebeat-pro-wireless-earbuds" in [p.slug for p in by_name.items]
    by_brand = catalog.search_products(db, catalog.SearchParams(q="voltra"))
    assert by_brand.total >= 3 and all(p.brand == "Voltra" for p in by_brand.items)


def test_search_filters_and_sorts(db: Session) -> None:
    params = catalog.SearchParams(min_price=500, max_price=2000, sort="price_asc", per_page=50)
    result = catalog.search_products(db, params)
    prices = [p.price for p in result.items]
    assert prices == sorted(prices)
    assert all(500 <= p <= 2000 for p in prices)
    audio = catalog.search_products(db, catalog.SearchParams(category="audio"))
    assert audio.total == 4
    assert {b for b, _ in audio.brands} == {"PulseBeat", "Nimbus", "Voltra"}


def test_search_pagination(db: Session) -> None:
    page2 = catalog.search_products(db, catalog.SearchParams(per_page=10, page=2))
    assert page2.page == 2 and len(page2.items) == 10 and page2.pages >= 3


def test_rating_histogram_matches_rating_count(db: Session) -> None:
    p = _product(db, "fitpulse-active-smartwatch")
    hist = catalog.rating_histogram(db, p.id)
    assert sum(hist.values()) == p.rating_count


# ---------------------------------------------------------------------------- cart


def test_cart_add_merges_lines_and_caps_quantity(db: Session) -> None:
    owner = cart_svc.CartOwner(session_key="guest-1")
    p = _product(db, "kraftwork-braided-usb-c-cable")
    cart_svc.add(db, owner, p.id, 3)
    cart_svc.add(db, owner, p.id, 20)
    summary = cart_svc.summarize(db, owner)
    assert len(summary.lines) == 1
    assert summary.lines[0].quantity == cart_svc.MAX_QTY_PER_LINE


def test_cart_rejects_out_of_stock(db: Session) -> None:
    p = _product(db, "kagaz-co-gel-pen-set")
    p.stock = 0
    db.commit()
    with pytest.raises(cart_svc.CartError, match="out of stock"):
        cart_svc.add(db, cart_svc.CartOwner(session_key="g"), p.id)


def test_shipping_fee_below_threshold_and_cod_fee(db: Session) -> None:
    owner = cart_svc.CartOwner(session_key="g2")
    cart_svc.add(db, owner, _product(db, "kagaz-co-gel-pen-set").id)  # $4
    s = cart_svc.summarize(db, owner, payment_method="cod")
    assert s.subtotal == 4
    assert s.shipping_fee == 5 and s.cod_fee == 2
    assert s.total == 4 + 5 + 2
    assert s.free_shipping_gap == 35 - 4


def test_coupon_rules(db: Session) -> None:
    owner = cart_svc.CartOwner(session_key="g3")
    cart_svc.add(db, owner, _product(db, "kagaz-co-gel-pen-set").id)  # $4
    s = cart_svc.summarize(db, owner, coupon_code="WELCOME10")
    assert s.coupon_discount == 0 and "more to use WELCOME10" in s.coupon_error
    assert "not a valid coupon" in cart_svc.summarize(db, owner, coupon_code="NOPE").coupon_error
    assert "no longer active" in cart_svc.summarize(db, owner, coupon_code="SUMMER15").coupon_error

    cart_svc.add(db, owner, _product(db, "nimbus-anc-over-ear-headphones").id, 2)  # 2 x $86
    s = cart_svc.summarize(db, owner, coupon_code="welcome10")
    assert s.coupon_discount == 15  # 10% capped at $15
    assert s.total == s.subtotal - 15


def test_guest_cart_merges_into_user_cart(db: Session) -> None:
    user = _customer(db)
    p = _product(db, "voltra-boom-portable-speaker")
    cart_svc.add(db, cart_svc.CartOwner(session_key="guest-merge"), p.id, 2)
    cart_svc.merge_guest_cart(db, "guest-merge", user.id)
    lines = cart_svc.summarize(db, cart_svc.CartOwner(user_id=user.id)).lines
    assert [(line.product_id, line.quantity) for line in lines] == [(p.id, 2)]


# ---------------------------------------------------------------------------- orders


def _place(db: Session, payment: str = "upi", coupon: str = "") -> tuple[Order, Product, int]:
    user = _customer(db)
    p = _product(db, "pulsebeat-pro-wireless-earbuds")
    stock_before = p.stock
    cart_svc.add(db, cart_svc.CartOwner(user_id=user.id), p.id, 2)
    address = db.scalar(select(Address).where(Address.user_id == user.id))
    assert address is not None
    order = order_svc.place_order(db, user, address, payment, coupon)
    return order, p, stock_before


def test_place_order_reserves_stock_and_clears_cart(db: Session) -> None:
    order, p, stock_before = _place(db, coupon="WELCOME10")
    db.refresh(p)
    assert p.stock == stock_before - 2
    assert order.number.startswith("HT-")
    assert order.total == 2 * 36 - 7  # WELCOME10: 10% of $72
    assert order.payment_status == "paid" and order.payment_ref.startswith("pay_")
    assert [e.status for e in order.events] == ["placed"]
    assert order.expected_delivery is not None
    user = _customer(db)
    assert cart_svc.count(db, cart_svc.CartOwner(user_id=user.id)) == 0


def test_cod_order_is_pending_until_delivered(db: Session) -> None:
    order, _, _ = _place(db, payment="cod")
    assert order.payment_status == "pending" and order.cod_fee == 2
    for status in ["confirmed", "packed", "shipped", "out_for_delivery", "delivered"]:
        order_svc.set_status(db, order, status)
    assert order.payment_status == "paid"
    assert order.tracking_number and order.courier
    assert order.delivered_at is not None


def test_invalid_transition_is_rejected(db: Session) -> None:
    order, _, _ = _place(db)
    with pytest.raises(order_svc.OrderError):
        order_svc.set_status(db, order, "delivered")


def test_cancel_restocks_and_refunds(db: Session) -> None:
    order, p, stock_before = _place(db)
    order_svc.cancel_by_customer(db, order, "Ordered by mistake")
    db.refresh(p)
    assert p.stock == stock_before
    assert order.status == "cancelled" and order.payment_status == "refunded"
    with pytest.raises(order_svc.OrderError):
        order_svc.cancel_by_customer(db, order)


def test_empty_cart_cannot_be_ordered(db: Session) -> None:
    user = _customer(db)
    address = user.addresses[0]
    with pytest.raises(order_svc.OrderError, match="empty"):
        order_svc.place_order(db, user, address, "upi")


@pytest.mark.parametrize(
    ("pin", "ok"), [("400076", True), ("110017", True), ("012345", False), ("4000", False)]
)
def test_pincode_validation(pin: str, ok: bool) -> None:
    assert order_svc.valid_pincode(pin) is ok


def test_metro_delivery_is_faster() -> None:
    assert order_svc.delivery_days("400076") < order_svc.delivery_days("795001")


# ------------------------------------------------------------- ShopCrew on store data


def test_store_data_source_feeds_shopcrew(db: Session) -> None:
    from northcart.services.ai import StoreDataSource

    source = StoreDataSource()
    product = source.get_product("voltra-boom-portable-speaker")
    assert product.our_price == 33
    assert any("IPX7" in f for f in product.features)
    assert len(source.get_reviews(product.id)) > 10
    assert len(source.get_competitor_prices(product.id)) >= 4


def test_store_data_source_errors(db: Session) -> None:
    from northcart.services.ai import StoreDataSource
    from shopcrew.exceptions import NoCompetitorPricesError, ProductNotFoundError

    source = StoreDataSource()
    with pytest.raises(ProductNotFoundError):
        source.get_product("does-not-exist")
    p = _product(db, "voltra-boom-portable-speaker")
    for row in list(p.competitor_prices):
        db.delete(row)
    db.commit()
    with pytest.raises(NoCompetitorPricesError):
        source.get_competitor_prices(p.slug)


def test_mock_crew_run_on_store_product_and_apply(db: Session) -> None:
    from northcart.models import CrewRun
    from northcart.services import ai

    p = _product(db, "nimbus-anc-over-ear-headphones")
    run = CrewRun(product_id=p.id, model="mock")
    db.add(run)
    db.commit()
    ai.execute_run(run.id)
    db.expire_all()
    run = db.get(CrewRun, run.id)
    assert run is not None and run.status == "done", run.error
    assert set(run.stages_done) == set(ai.STAGE_KEYS)
    assert run.result["pricing_report"]["our_price"] == 86

    ai.apply_result(db, run, "insights")
    ai.apply_result(db, run, "seo")
    ai.apply_result(db, run, "price")
    db.refresh(p)
    assert p.ai_summary and p.ai_praises
    assert p.seo_title and len(p.highlights) == 5
    assert p.price == int(round(run.result["pricing_report"]["recommended_price"]))
    assert run.applied == ["insights", "price", "seo"]


def test_shopper_summary_never_shows_seller_advice(db: Session) -> None:
    from northcart.models import CrewRun
    from northcart.services import ai

    p = _product(db, "voltra-boom-portable-speaker")
    seller_summary = "Customers love the bass. Focus marketing on outdoor resilience."
    run = CrewRun(
        product_id=p.id,
        status="done",
        result={
            "review_insights": {
                "summary": seller_summary,
                "top_praises": ["Bass is surprisingly deep", "IPX7 rating survives the pool"],
                "top_complaints": [
                    "Strap feels a bit flimsy",
                    "Nothing special",
                    "strap feels a bit flimsy",
                ],
            }
        },
    )
    db.add(run)
    db.commit()
    ai.apply_result(db, run, "insights")
    assert "marketing" not in p.ai_summary.lower()
    assert p.ai_summary == (
        "Most praised: bass is surprisingly deep; IPX7 rating survives the pool. "
        "Common concerns: strap feels a bit flimsy. "
        f"Based on {p.rating_count} customer reviews."
    )
    assert p.ai_complaints == ["Strap feels a bit flimsy"]  # vague + duplicate dropped


def test_crew_run_needs_reviews_and_prices(db: Session) -> None:
    from northcart.services import ai

    p = _product(db, "kagaz-co-gel-pen-set")
    db.query(Review).filter(Review.product_id == p.id).delete()
    db.query(CompetitorPrice).filter(CompetitorPrice.product_id == p.id).delete()
    db.commit()
    db.refresh(p)
    with pytest.raises(ValueError, match="no reviews"):
        ai.start_run(db, p)
