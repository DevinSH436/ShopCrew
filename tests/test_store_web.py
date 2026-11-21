"""End-to-end tests of the Northcart web app through FastAPI's TestClient (no server, no LLM)."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from northcart.models import Address, Order, Product, User
from tests.test_store_services import db, seeded_template  # noqa: F401 - shared fixtures

CUSTOMER = ("customer@northcart.test", "shop1234")
ADMIN = ("admin@northcart.test", "admin1234")


@pytest.fixture
def client(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:  # noqa: F811
    """A client on a private copy of the seeded DB, with the mock (offline) LLM."""
    monkeypatch.setenv("MODEL", "mock")
    from northcart.web.app import app

    with TestClient(app) as c:
        yield c


def csrf(c: TestClient, path: str = "/") -> str:
    """Read the CSRF token the way a browser would: from the page's forms.

    Every hidden ``csrf_token`` field on the page must carry the session token (an empty
    field means a macro lost its template context and the form would fail with 403).
    """
    html = c.get(path).text
    meta = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert meta, f"no csrf meta on {path}"
    fields = re.findall(r'name="csrf_token" value="([^"]*)"', html)
    assert all(f == meta.group(1) for f in fields), f"form with a missing CSRF token on {path}"
    return fields[0] if fields else meta.group(1)


def sign_in(c: TestClient, email: str, password: str) -> None:
    r = c.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf(c, "/login")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:300]


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/search?q=earbuds",
        "/search?brand=Voltra&sort=price_asc",
        "/c/audio",
        "/deals",
        "/p/pulsebeat-pro-wireless-earbuds",
        "/pages/help",
        "/pages/returns",
        "/cart",
        "/login",
        "/register",
        "/sitemap.xml",
        "/robots.txt",
        "/api/suggest?q=bot",
        "/api/delivery?zip_code=10011",
        "/art/pulsebeat-pro-wireless-earbuds.svg?v=2",
    ],
)
def test_public_pages_load(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200
    if "text/html" in r.headers["content-type"]:
        csrf(client, path)


def test_unknown_pages_are_404(client: TestClient) -> None:
    assert client.get("/p/no-such-product").status_code == 404
    assert client.get("/pages/nope").status_code == 404


def test_product_page_shows_price_and_reviews(client: TestClient) -> None:
    html = client.get("/p/voltra-boom-portable-speaker").text
    assert "Voltra Boom" in html and "$33" in html
    assert "Sales tax included" in html


def test_post_without_csrf_is_rejected(client: TestClient) -> None:
    assert client.post("/cart/add", data={"product_id": 1}).status_code == 403


def test_account_pages_require_sign_in(client: TestClient) -> None:
    r = client.get("/account/orders", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_bad_password_is_refused(client: TestClient) -> None:
    r = client.post(
        "/login",
        data={"email": CUSTOMER[0], "password": "wrong", "csrf_token": csrf(client)},
        follow_redirects=False,
    )
    assert r.status_code != 303


def test_guest_cart_then_checkout_with_cod(client: TestClient, db: Session) -> None:  # noqa: F811
    product = db.scalar(select(Product).where(Product.slug == "ascend-yoga-mat-6mm"))
    assert product is not None
    token = csrf(client)
    headers = {"X-CSRF-Token": token, "X-Requested-With": "fetch", "Accept": "application/json"}
    r = client.post("/cart/add", data={"product_id": product.id, "quantity": 2}, headers=headers)
    assert r.status_code == 200 and r.json()["count"] == 2

    sign_in(client, *CUSTOMER)  # guest cart merges into the account
    assert "Yoga Mat" in client.get("/cart").text
    assert client.get("/checkout").status_code == 200

    user = db.scalar(select(User).where(User.email == CUSTOMER[0]))
    assert user is not None
    address = db.scalar(select(Address).where(Address.user_id == user.id))
    assert address is not None
    r = client.post(
        "/checkout/place",
        data={
            "address_id": address.id,
            "payment_method": "cod",
            "csrf_token": csrf(client, "/checkout"),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 and "/success" in r.headers["location"], r.text[:300]
    number = r.headers["location"].split("/")[2]
    assert client.get(r.headers["location"]).status_code == 200
    assert number in client.get("/account/orders").text
    assert client.get(f"/account/orders/{number}/invoice").status_code == 200
    for path in [
        "/account",
        "/account/orders",
        f"/account/orders/{number}",
        "/account/addresses",
        "/account/addresses/new",
        "/account/profile",
        "/wishlist",
    ]:
        csrf(client, path)  # every form on the page carries the token

    db.expire_all()
    order = db.scalar(select(Order).where(Order.number == number))
    assert order is not None and order.total == 2 * 13 + 5 + 2  # $13 mat: shipping and COD fees


def test_customers_cannot_open_admin(client: TestClient) -> None:
    sign_in(client, *CUSTOMER)
    assert client.get("/admin").status_code == 403


def test_admin_pages_and_mock_crew_run(client: TestClient, db: Session) -> None:  # noqa: F811
    sign_in(client, *ADMIN)
    for path in [
        "/admin",
        "/admin/orders",
        "/admin/products",
        "/admin/inventory",
        "/admin/customers",
        "/admin/reviews",
        "/admin/coupons",
        "/admin/reports",
        "/admin/settings",
        "/admin/ai",
    ]:
        assert client.get(path).status_code == 200, path
        csrf(client, path)  # every form on the page carries the token

    product = db.scalar(select(Product).where(Product.slug == "ironside-cast-iron-griddle"))
    assert product is not None
    token = csrf(client, "/admin/ai")
    r = client.post(
        "/admin/ai/run",
        data={"product_id": product.id, "process": "sequential", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    run_url = r.headers["location"]
    status: dict = {}
    for _ in range(150):
        status = client.get(f"{run_url}/status.json").json()
        if status["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert status["status"] == "done", status
    assert client.get(run_url).status_code == 200
