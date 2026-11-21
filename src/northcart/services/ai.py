"""AI features: ShopCrew runs on store products, and one-shot LLM helpers.

The model comes from ``MODEL`` in ``.env`` (``ollama/qwen3.5:4b`` by default for this
store), so everything runs on a local Ollama server. ``MODEL=mock`` uses ShopCrew's
deterministic offline agents.

``StoreDataSource`` implements ShopCrew's ``DataSource`` protocol on top of the store
database, so the four agents analyse the store's real reviews and competitor prices.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from northcart import db as dbmod
from northcart.models import CompetitorPrice, CrewRun, Product, Review
from shopcrew.exceptions import NoCompetitorPricesError, NoReviewsError, ProductNotFoundError
from shopcrew.models import CompetitorPrice as CrewCompetitorPrice
from shopcrew.models import Product as CrewProduct
from shopcrew.models import Review as CrewReview

logger = logging.getLogger(__name__)

STAGE_KEYS = ["review_task", "pricing_task", "seo_task", "marketing_task"]
STAGE_LABELS = {
    "review_task": ("Review Analyst", "Reads every review for sentiment, praise and complaints"),
    "pricing_task": ("Price Tracker", "Compares our price with competitors"),
    "seo_task": ("SEO Writer", "Writes the title, meta, bullets and description"),
    "marketing_task": ("Marketer", "Plans the launch campaign from all three"),
}
APPLY_TARGETS = ("seo", "price", "insights")


def configured_model() -> str:
    """Model id the store's AI features use."""
    from shopcrew.llm import configured_model as crew_model

    return crew_model()


def model_status() -> dict[str, Any]:
    """Whether the configured model looks reachable (checks Ollama's API for ollama/*)."""
    model = configured_model()
    info: dict[str, Any] = {"model": model, "provider": model.split("/", 1)[0], "ok": True}
    if model.startswith(("ollama/", "ollama_chat/")):
        import os

        import httpx

        base = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434"
        if not base.startswith("http"):
            base = f"http://{base}"
        name = model.split("/", 1)[1]
        try:
            tags = httpx.get(f"{base}/api/tags", timeout=2).json().get("models", [])
            names = {t.get("name") for t in tags}
            info["ok"] = name in names or f"{name}:latest" in names
            info["detail"] = f"Ollama at {base}" if info["ok"] else f"Run: ollama pull {name}"
        except Exception:  # noqa: BLE001 - any failure means "not reachable"
            info["ok"] = False
            info["detail"] = f"Ollama is not running at {base}. Start it with: ollama serve"
    elif model == "mock":
        info["detail"] = "Offline demo agents (no LLM)"
    return info


# --------------------------------------------------------------------------------------
# ShopCrew data source backed by the store database
# --------------------------------------------------------------------------------------


def features_of(product: Product) -> list[str]:
    """The feature list agents may claim: highlights plus specs."""
    feats = list(product.highlights or [])
    feats += [f"{k}: {v}" for k, v in (product.specs or {}).items()]
    return feats or [product.short_description or product.name]


class StoreDataSource:
    """ShopCrew ``DataSource`` reading products, reviews and competitor prices from the DB.

    Product ids are store slugs. Each call opens its own short session, so the source is
    safe to use from the crew's worker thread.
    """

    def _product(self, s: Session, product_id: str) -> Product:
        product = s.scalar(
            select(Product)
            .where(Product.slug == product_id)
            .options(selectinload(Product.category))
        )
        if product is None:
            slugs = list(s.scalars(select(Product.slug).order_by(Product.slug)))
            raise ProductNotFoundError(product_id, slugs)
        return product

    @staticmethod
    def _to_crew(product: Product) -> CrewProduct:
        return CrewProduct(
            id=product.slug,
            name=product.name,
            category=product.category.name if product.category else "General",
            our_price=float(product.price),
            current_description=product.description or product.short_description or product.name,
            features=features_of(product),
        )

    def list_products(self) -> list[CrewProduct]:
        """All products as ShopCrew products."""
        with dbmod.SessionLocal() as s:
            rows = s.scalars(select(Product).options(selectinload(Product.category)))
            return [self._to_crew(p) for p in rows]

    def get_product(self, product_id: str) -> CrewProduct:
        """One product, or ``ProductNotFoundError``."""
        with dbmod.SessionLocal() as s:
            return self._to_crew(self._product(s, product_id))

    def get_reviews(self, product_id: str) -> list[CrewReview]:
        """Published reviews, or ``NoReviewsError``."""
        with dbmod.SessionLocal() as s:
            product = self._product(s, product_id)
            rows = s.scalars(
                select(Review)
                .where(Review.product_id == product.id, Review.status == "published")
                .order_by(Review.created_at.desc())
            ).all()
            if not rows:
                raise NoReviewsError(product_id)
            return [
                CrewReview(
                    product_id=product_id,
                    rating=r.rating,
                    text=r.body,
                    date=r.created_at.date().isoformat(),
                )
                for r in rows
            ]

    def get_competitor_prices(self, product_id: str) -> list[CrewCompetitorPrice]:
        """Competitor listings, or ``NoCompetitorPricesError``."""
        with dbmod.SessionLocal() as s:
            product = self._product(s, product_id)
            rows = s.scalars(
                select(CompetitorPrice).where(CompetitorPrice.product_id == product.id)
            ).all()
            if not rows:
                raise NoCompetitorPricesError(product_id)
            return [
                CrewCompetitorPrice(
                    product_id=product_id,
                    competitor=r.competitor,
                    price=float(r.price),
                    in_stock=r.in_stock,
                    last_checked=r.last_checked.date().isoformat(),
                )
                for r in rows
            ]


# --------------------------------------------------------------------------------------
# Background crew runs (one at a time: a local model can only do one job well)
# --------------------------------------------------------------------------------------

_jobs: queue.Queue[int] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _update(run_id: int, **fields: Any) -> None:
    with dbmod.SessionLocal() as s:
        run = s.get(CrewRun, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        s.commit()


def _append_log(run_id: int, line: str, **fields: Any) -> None:
    with dbmod.SessionLocal() as s:
        run = s.get(CrewRun, run_id)
        if run is None:
            return
        run.log = [*(run.log or []), line][-200:]
        for key, value in fields.items():
            setattr(run, key, value)
        s.commit()


def execute_run(run_id: int) -> None:
    """Run the crew for a ``CrewRun`` row and store progress and results on it."""
    from shopcrew.runner import RunEvent, run_crew

    with dbmod.SessionLocal() as s:
        run = s.get(CrewRun, run_id)
        if run is None:
            return
        slug, process, model = run.product.slug, run.process, run.model
    _update(run_id, status="running", started_at=datetime.now(UTC))
    done: list[str] = []

    def on_event(event: RunEvent) -> None:
        extra: dict[str, Any] = {}
        if event.kind == "started" and event.stage:
            extra["current_stage"] = event.stage
        if event.kind == "completed" and event.stage and event.stage not in done:
            done.append(event.stage)
            extra["stages_done"] = list(done)
        _append_log(run_id, event.line(), **extra)

    try:
        result = run_crew(
            slug,
            process=process,  # type: ignore[arg-type]
            model=model or None,
            source=StoreDataSource(),
            on_event=on_event,
            verbose=False,
        )
        summary = json.loads((result.out_dir / "run_summary.json").read_text(encoding="utf-8"))
        _update(
            run_id,
            status="done",
            result=summary,
            stages_done=list(STAGE_KEYS),
            current_stage="",
            out_dir=str(result.out_dir),
            cost_usd=float(result.cost.usd or 0),
            tokens=int(result.cost.total_tokens or 0),
            finished_at=datetime.now(UTC),
        )
    except Exception as err:  # noqa: BLE001 - surface any failure in the admin panel
        logger.exception("Crew run %s failed", run_id)
        _append_log(
            run_id,
            f"ERROR: {err}",
            status="failed",
            error=str(err) or err.__class__.__name__,
            finished_at=datetime.now(UTC),
        )


def _work() -> None:
    while True:
        run_id = _jobs.get()
        try:
            execute_run(run_id)
        finally:
            _jobs.task_done()


def start_run(db: Session, product: Product, process: str = "sequential") -> CrewRun:
    """Queue a crew run for ``product`` and make sure the worker thread is running."""
    global _worker
    if not product.reviews:
        raise ValueError("This product has no reviews yet, so the crew has nothing to analyse.")
    if not product.competitor_prices:
        raise ValueError("Add at least one competitor price before running the crew.")
    run = CrewRun(product_id=product.id, process=process, model=configured_model())
    db.add(run)
    db.commit()
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="shopcrew-worker", daemon=True)
            _worker.start()
    _jobs.put(run.id)
    return run


def recover_interrupted_runs() -> None:
    """Mark runs left 'queued'/'running' by a previous process as failed (on startup)."""
    with dbmod.SessionLocal() as s:
        for run in s.scalars(select(CrewRun).where(CrewRun.status.in_(["queued", "running"]))):
            run.status = "failed"
            run.error = "The server restarted before this run finished."
        s.commit()


# Review points too vague to show shoppers ("Nothing special", "No complaints").
_VAGUE = re.compile(
    r"^(nothing( special| major)?|none|no (major )?(complaints?|issues?)|n/?a)\.?$", re.I
)


def _useful_points(points: list[str]) -> list[str]:
    """Trim, de-duplicate and drop vague praise/complaint points."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in points:
        point = " ".join(str(raw).split()).strip(" .")
        if point and not _VAGUE.match(point) and point.lower() not in seen:
            seen.add(point.lower())
            out.append(point)
    return out


def _sentence_part(point: str) -> str:
    """Lower-case a point's first letter for mid-sentence use, keeping acronyms (IPX7, USB)."""
    if len(point) > 1 and point[0].isupper() and point[1].islower():
        return point[0].lower() + point[1:]
    return point


def shopper_summary(praises: list[str], complaints: list[str], review_count: int) -> str:
    """Customer-facing 'Customers say' text built only from what reviewers said.

    The Review Analyst's own ``summary`` is written for the seller and can include
    marketing advice ("focus marketing on..."), so it is never shown to shoppers.
    Points may be clauses or noun phrases, so they are listed rather than woven into prose.
    """
    parts = []
    if praises:
        parts.append("Most praised: " + "; ".join(_sentence_part(p) for p in praises[:3]) + ".")
    if complaints:
        parts.append(
            "Common concerns: " + "; ".join(_sentence_part(c) for c in complaints[:2]) + "."
        )
    if review_count:
        parts.append(f"Based on {review_count} customer reviews.")
    return " ".join(parts)


def apply_result(db: Session, run: CrewRun, target: str) -> str:
    """Copy part of a finished run onto the product. Returns a confirmation message."""
    if run.status != "done" or not run.result:
        raise ValueError("Only finished runs can be applied.")
    product = run.product
    res = run.result
    if target == "seo":
        seo = res["seo_copy"]
        product.seo_title = seo["title"][:70]
        product.seo_meta = seo["meta_description"][:160]
        product.highlights = list(seo["bullet_points"])
        product.description = seo["long_description"]
        product.keywords = list(seo["keywords"])
        message = "SEO title, meta description, highlights and description updated."
    elif target == "price":
        new_price = int(round(res["pricing_report"]["recommended_price"]))
        old = product.price
        product.price = new_price
        product.mrp = max(product.mrp, new_price)
        message = f"Price changed from ${old:,} to ${new_price:,}."
    elif target == "insights":
        ins = res["review_insights"]
        praises = _useful_points(ins["top_praises"])[:5]
        complaints = _useful_points(ins["top_complaints"])[:5]
        product.ai_summary = shopper_summary(praises, complaints, product.rating_count)
        product.ai_praises = praises
        product.ai_complaints = complaints
        message = "'Customers say' summary is now live on the product page."
    else:
        raise ValueError(f"Unknown target '{target}'.")
    run.applied = sorted({*(run.applied or []), target})
    db.commit()
    return message


# --------------------------------------------------------------------------------------
# One-shot helpers (product description writer)
# --------------------------------------------------------------------------------------


def _complete(prompt: str) -> str:
    """Single LLM completion with the configured model."""
    from shopcrew.llm import build_llm, is_mock

    model = configured_model()
    if is_mock(model):
        raise RuntimeError("MODEL=mock has no free-text generation. Set MODEL=ollama/qwen3.5:4b.")
    llm = build_llm(model)
    reply = llm.call([{"role": "user", "content": prompt}])
    text = reply if isinstance(reply, str) else str(reply)
    # Strip any <think> block some reasoning models emit.
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def write_description(name: str, brand: str, category: str, features: list[str]) -> dict:
    """Ask the model for a short description, highlights and SEO fields as JSON."""
    prompt = (
        "You write product listings for an American online store. Use only the facts given; "
        "never invent features, certifications or numbers.\n\n"
        f"Product: {name}\nBrand: {brand}\nCategory: {category}\nFacts:\n"
        + "\n".join(f"- {f}" for f in features)
        + "\n\nReturn ONLY a JSON object with keys: short_description (max 150 chars), "
        "description (80-120 words, friendly, American English), highlights (list of 4-5 short "
        "bullet strings), seo_title (max 70 chars), seo_meta (max 160 chars)."
    )
    text = _complete(prompt)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise RuntimeError("The model did not return JSON. Try again.")
    data = json.loads(match.group(0))
    return {
        "short_description": str(data.get("short_description", ""))[:300],
        "description": str(data.get("description", "")),
        "highlights": [str(h) for h in data.get("highlights", [])][:6],
        "seo_title": str(data.get("seo_title", ""))[:70],
        "seo_meta": str(data.get("seo_meta", ""))[:160],
    }
