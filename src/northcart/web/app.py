"""FastAPI application factory for the Northcart store.

Run with ``uv run uvicorn northcart.web.app:app --reload`` (or ``uv run northcart``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from northcart import db as dbmod
from northcart.art import product_svg
from northcart.config import PACKAGE_DIR, get_settings
from northcart.models import Product
from northcart.web import routes_account, routes_admin, routes_cart, routes_shop
from northcart.web.deps import LoginRequired, verify_csrf
from northcart.web.templating import render

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    """Create tables, seed an empty database, and clean up interrupted AI runs."""
    from northcart import seed
    from northcart.services.ai import recover_interrupted_runs

    if seed.run():
        logger.info("Seeded an empty store database with demo data.")
    recover_interrupted_runs()
    yield


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.url.path.startswith("/api/") or (
        "application/json" in accept and "text/html" not in accept
    )


def create_app() -> FastAPI:
    """Build the FastAPI app."""
    settings = get_settings()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(
        title=f"{settings.store_name} Store",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        dependencies=[Depends(verify_csrf)],
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="northcart_session",
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
        https_only=False,
    )
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    app.mount("/media", StaticFiles(directory=str(settings.media_dir)), name="media")

    @app.get("/art/{slug}.svg", include_in_schema=False)
    def product_art(slug: str, v: int = 0) -> Response:
        with dbmod.SessionLocal() as db:
            row = db.execute(
                select(Product.art_kind, Product.color, Product.brand).where(Product.slug == slug)
            ).first()
        if row is None:
            return Response(status_code=404)
        svg = product_svg(row.art_kind, row.color, v, row.brand)
        return Response(
            svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"}
        )

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict:
        return {"ok": True}

    app.include_router(routes_shop.router)
    app.include_router(routes_account.router)
    app.include_router(routes_cart.router)
    app.include_router(routes_admin.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):  # type: ignore[no-untyped-def]
        if _wants_json(request) or request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"error": "Please sign in to continue.", "login": True}, 401)
        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        if _wants_json(request) or request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"error": exc.detail}, exc.status_code)
        with dbmod.SessionLocal() as db:
            return render(
                request,
                db,
                "error.html",
                {"status": exc.status_code, "detail": exc.detail},
                status_code=exc.status_code,
            )

    app.add_exception_handler(FastAPIHTTPException, _http_error)  # type: ignore[arg-type]
    return app


app = create_app()


def main() -> None:
    """``uv run northcart``: serve the store on http://127.0.0.1:8000."""
    import os

    import uvicorn

    uvicorn.run(
        "northcart.web.app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() in {"1", "true"},
    )
