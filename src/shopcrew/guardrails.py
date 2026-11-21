"""Task guardrails: validate each agent's output and fix numbers computed in code.

Every task gets ``guardrail_max_retries=1``, so an invalid output is sent back to the
agent once with the validation error before the run fails.

Note: this module deliberately does not use ``from __future__ import annotations``.
CrewAI inspects the guardrail's return annotation at runtime and needs a real
``tuple[bool, Any]``, not a string.
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from crewai import TaskOutput
from pydantic import BaseModel, ValidationError

from shopcrew.claims import collect_text, find_unsupported_claims
from shopcrew.datasource import DataSource
from shopcrew.models import CampaignPlan, PricingReport, ReviewInsights, SEOCopy
from shopcrew.stats import compute_price_stats, compute_review_stats

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
Guardrail = Callable[[TaskOutput], tuple[bool, Any]]

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(raw: str) -> dict[str, Any]:
    """Pull the agent's JSON object out of its raw text.

    Handles plain JSON, Markdown code fences and surrounding chatter. Small local models
    sometimes emit several objects (e.g. a fake "Action Input" then the real answer), so
    every top-level object is decoded and the last (largest on ties) is used.
    """
    text = _FENCE.sub("", raw.strip()).strip()
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    index = text.find("{")
    while index != -1:
        try:
            obj, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        index = text.find("{", end)
    if not found:
        raise ValueError("no JSON object found in the output")
    return max(reversed(found), key=len)


def parse_output(raw: str, model: type[M]) -> M:
    """Parse an agent's raw text into ``model``."""
    return model.model_validate(extract_json(raw))


def trim_to(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` characters at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" ,;:-–|&")[:limit]


def _trim_fields(
    data: dict[str, Any], limits: dict[str, int], notes: list[str], who: str
) -> dict[str, Any]:
    """Trim over-long text fields (dotted paths) instead of failing the whole task."""
    for path, limit in limits.items():
        *parents, leaf = path.split(".")
        node: Any = data
        for key in parents:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict) and isinstance(node.get(leaf), str) and len(node[leaf]) > limit:
            node[leaf] = trim_to(node[leaf], limit)
            notes.append(f"{who}: trimmed {path} to {limit} characters")
    return data


def _coerce(output: TaskOutput, model: type[M], limits: dict[str, int], notes: list[str]) -> M:
    if isinstance(output.pydantic, model):
        return output.pydantic
    data = extract_json(output.raw)
    return model.model_validate(_trim_fields(data, limits, notes, model.__name__))


def _error(model: type[BaseModel], err: Exception) -> tuple[bool, Any]:
    if isinstance(err, ValidationError):
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}" for e in err.errors()
        )
    else:
        details = str(err)
    return (
        False,
        f"Output did not match the {model.__name__} schema ({details}). "
        "Return ONLY a valid JSON object that matches the schema exactly.",
    )


def _guardrail(
    model: type[M],
    fix: Callable[[M], M] | None = None,
    check: Callable[[M], str | None] | None = None,
    limits: dict[str, int] | None = None,
    notes: list[str] | None = None,
) -> Guardrail:
    """Build a guardrail: parse (trimming ``limits`` fields), apply ``fix``, then ``check``."""
    limits = limits or {}
    notes = notes if notes is not None else []

    def guardrail(output: TaskOutput) -> tuple[bool, Any]:
        try:
            parsed = _coerce(output, model, limits, notes)
        except (ValidationError, ValueError) as err:
            return _error(model, err)
        if fix is not None:
            parsed = fix(parsed)
        if check is not None and (problem := check(parsed)):
            return False, problem
        return True, parsed

    return guardrail


def review_guardrail(source: DataSource, product_id: str, notes: list[str]) -> Guardrail:
    """Validate ReviewInsights and overwrite rating/sentiment with exact figures."""

    def fix(insights: ReviewInsights) -> ReviewInsights:
        stats = compute_review_stats(source.get_reviews(product_id))
        exact = {
            "average_rating": stats.average_rating,
            "sentiment_breakdown": {
                "positive": stats.positive_pct,
                "neutral": stats.neutral_pct,
                "negative": stats.negative_pct,
            },
        }
        current = insights.model_dump(include=set(exact))
        if current != exact:
            notes.append(f"Review Analyst numbers corrected to computed stats: {exact}")
        return ReviewInsights.model_validate({**insights.model_dump(), **exact})

    return _guardrail(ReviewInsights, fix=fix)


def pricing_guardrail(source: DataSource, product_id: str, notes: list[str]) -> Guardrail:
    """Validate PricingReport, overwrite the maths, and sanity-check the recommendation."""

    def fix(report: PricingReport) -> PricingReport:
        product = source.get_product(product_id)
        stats = compute_price_stats(product.our_price, source.get_competitor_prices(product_id))
        exact = stats.model_dump(
            include={"our_price", "competitor_min", "competitor_max", "competitor_avg", "position"}
        )
        current = report.model_dump(include=set(exact))
        if current != exact:
            notes.append(f"Price Tracker numbers corrected to computed stats: {exact}")
        return report.model_copy(update=exact)

    def check(report: PricingReport) -> str | None:
        low, high = report.our_price * 0.5, report.our_price * 1.5
        if not low <= report.recommended_price <= high:
            return (
                f"recommended_price {report.recommended_price} is unrealistic: keep it within "
                f"50%-150% of our current price ({report.our_price})."
            )
        return None

    return _guardrail(PricingReport, fix=fix, check=check)


SEO_LIMITS = {"title": 70, "meta_description": 160}
CAMPAIGN_LIMITS = {"google_ad.headline": 30, "google_ad.description": 90, "email.subject": 80}


CLAIM_WARNING = "Unsupported claim kept after retry"


def claims_check(
    source: DataSource, product_id: str, notes: list[str], who: str
) -> Callable[[BaseModel], str | None]:
    """Reject unsupported claims once (with the exact sentences), then only warn.

    The spec allows one retry. Failing the whole run over wording would be worse than
    shipping it with a visible warning, so a second offence is recorded in ``notes``
    (run_log.txt and the dashboard) instead of raising.
    """
    rejected = False

    def check(output: BaseModel) -> str | None:
        nonlocal rejected
        product = source.get_product(product_id)
        reviews = [r.text for r in source.get_reviews(product_id)]
        texts = collect_text(output.model_dump(mode="json", by_alias=True))
        issues = find_unsupported_claims(texts, product, reviews)
        if not issues:
            return None
        if not rejected:
            rejected = True
            listed = "\n".join(f"- {i.describe()}" for i in issues)
            return (
                f"Your {who} makes claims the product data does not support:\n{listed}\n"
                "Rewrite those sentences using only the product_info feature list and real "
                "customer quotes. No exclusivity claims ('the only', '#1', 'guaranteed'), no "
                "claims that we changed the product, and no durations the features don't list. "
                "Keep everything else the same."
            )
        notes.extend(f"{CLAIM_WARNING} ({who}): {i.describe()}" for i in issues)
        return None

    return check


def seo_guardrail(source: DataSource, product_id: str, notes: list[str] | None = None) -> Guardrail:
    """Validate SEOCopy: trim title/meta, enforce word count, reject unsupported claims."""
    notes = notes if notes is not None else []
    check = claims_check(source, product_id, notes, "SEO copy")
    return _guardrail(SEOCopy, check=check, limits=SEO_LIMITS, notes=notes)


def campaign_guardrail(
    source: DataSource, product_id: str, notes: list[str] | None = None
) -> Guardrail:
    """Validate CampaignPlan: trim ad/email text, reject unsupported claims."""
    notes = notes if notes is not None else []
    check = claims_check(source, product_id, notes, "campaign")
    return _guardrail(CampaignPlan, check=check, limits=CAMPAIGN_LIMITS, notes=notes)
