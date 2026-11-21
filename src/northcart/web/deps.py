"""Request helpers: current user, CSRF, flash messages, cart owner, admin guard."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from northcart.db import get_db
from northcart.models import User
from northcart.security import new_token, tokens_match
from northcart.services.cart import CartOwner


class LoginRequired(Exception):
    """Raised when a page needs a signed-in user; handled by redirecting to /login."""

    def __init__(self, next_url: str = "/") -> None:
        self.next_url = next_url


def csrf_token(request: Request) -> str:
    """The session's CSRF token (created on first use)."""
    token = request.session.get("csrf")
    if not token:
        token = new_token()
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Reject state-changing requests without a matching CSRF token."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    sent = request.headers.get("x-csrf-token")
    if not sent:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            form = await request.form()
            sent = str(form.get("csrf_token") or "")
    if not tokens_match(sent, request.session.get("csrf")):
        raise HTTPException(
            status_code=403,
            detail="Your session expired. Please refresh the page and try again.",
        )


def flash(request: Request, message: str, kind: str = "success") -> None:
    """Queue a message shown on the next rendered page."""
    messages = list(request.session.get("flash", []))
    messages.append({"kind": kind, "text": message})
    request.session["flash"] = messages[-5:]


def pop_flashes(request: Request) -> list[dict]:
    """Take all queued flash messages."""
    return list(request.session.pop("flash", []))


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The signed-in user, or None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.pop("user_id", None)
        return None
    return user


def require_user(request: Request, user: User | None = Depends(current_user)) -> User:
    """The signed-in user, or redirect to sign in."""
    if user is None:
        next_url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired(next_url)
    return user


def require_admin(request: Request, user: User | None = Depends(current_user)) -> User:
    """A signed-in staff user, or redirect/403."""
    if user is None:
        raise LoginRequired(request.url.path)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="This area is for store staff only.")
    return user


def cart_owner(request: Request, user: User | None = Depends(current_user)) -> CartOwner:
    """Cart owner for this request (user, or a guest key stored in the session)."""
    if user is not None:
        return CartOwner(user_id=user.id)
    key = request.session.get("cart_key")
    if not key:
        key = new_token()
        request.session["cart_key"] = key
    return CartOwner(session_key=key)


def login(request: Request, user: User) -> None:
    """Start a session for ``user`` (rotating the CSRF token)."""
    request.session["user_id"] = user.id
    request.session["csrf"] = new_token()


def logout(request: Request) -> None:
    """End the session."""
    request.session.clear()
