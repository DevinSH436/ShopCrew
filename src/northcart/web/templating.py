"""Jinja environment, filters and the shared page context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from northcart.config import PACKAGE_DIR, get_settings
from northcart.models import ORDER_STATUS_LABELS, PAYMENT_METHODS, User, WishlistItem
from northcart.services import cart as cart_svc
from northcart.services import catalog
from northcart.services import settings as settings_svc
from northcart.web.deps import cart_owner, csrf_token, pop_flashes

IST = timezone(timedelta(hours=5, minutes=30))
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def usd(value: float | int | None, decimals: bool = False) -> str:
    """Format dollars with US digit grouping: 1234567 -> '1,234,567'."""
    if value is None:
        return "–"
    return f"{value:,.2f}" if decimals else f"{int(value):,}"


def to_ist(value: datetime | None) -> datetime | None:
    """Convert a stored UTC timestamp to India time."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(IST)


def fmt_date(value: datetime | None, fmt: str = "%d %b %Y") -> str:
    """Date in IST, e.g. '20 Nov 2026'."""
    v = to_ist(value)
    return v.strftime(fmt) if v else ""


def fmt_datetime(value: datetime | None) -> str:
    """Date and time in IST, e.g. '20 Nov 2026, 4:05 PM'."""
    v = to_ist(value)
    return v.strftime("%d %b %Y, %I:%M %p").replace(" 0", " ") if v else ""


def ago(value: datetime | None) -> str:
    """Relative time: '3 hours ago'."""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    secs = int((datetime.now(UTC) - value).total_seconds())
    for unit, size in (("year", 31536000), ("month", 2592000), ("day", 86400),
                       ("hour", 3600), ("minute", 60)):  # fmt: skip
        if secs >= size:
            n = secs // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def compact(value: int | float) -> str:
    """Short number: 1250 -> '1.2K', 1500000 -> '1.5M'."""
    v = float(value)
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1000, "K")):
        if v >= size:
            return f"{v / size:.1f}{suffix}".replace(f".0{suffix}", suffix)
    return str(int(v))


templates.env.filters.update(
    usd=usd, date=fmt_date, datetime=fmt_datetime, ago=ago, compact=compact, ist=to_ist
)
templates.env.globals.update(
    ORDER_STATUS_LABELS=ORDER_STATUS_LABELS,
    PAYMENT_METHODS=PAYMENT_METHODS,
    now=lambda: datetime.now(IST),
)


def render(
    request: Request,
    db: Session,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    user: User | None = None,
) -> HTMLResponse:
    """Render a template with the shared context every page needs.

    Shared context: ``user``, ``settings`` (env), ``store`` (admin-editable settings),
    ``categories``, ``cart_count``, ``csrf_token``, ``flashes``.
    """
    if user is None and request.session.get("user_id"):
        user = db.get(User, request.session["user_id"])
    owner = cart_owner(request, user)
    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "settings": get_settings(),
        "store": settings_svc.all_settings(db),
        "categories": catalog.categories(db),
        "cart_count": cart_svc.count(db, owner),
        "csrf_token": csrf_token(request),
        "flashes": pop_flashes(request),
        "wishlist_ids": list(
            db.scalars(select(WishlistItem.product_id).where(WishlistItem.user_id == user.id))
        )
        if user
        else [],
    }
    ctx.update(context or {})
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
