"""Offline demo mode: a fake LLM that drives the real crew without an API key.

``DemoLLM`` plugs into CrewAI like any other LLM. It goes through the real agent loop:
each specialist calls its real tool first, then answers with a templated, data-driven
JSON output built from the same sample data. In hierarchical mode it also plays the
Store Manager and delegates each task to the right coworker.

It exists so the dashboard and Docker image work out of the box (``MODEL=mock``) and so
the smoke test can run the full crew in CI. Outputs are deterministic and clearly less
creative than a real model.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

from crewai.llms.base_llm import BaseLLM

from shopcrew.datasource import DataSource, default_source
from shopcrew.models import (
    CampaignPlan,
    PricePosition,
    PricingReport,
    Product,
    ReviewInsights,
    SEOCopy,
)
from shopcrew.stats import compute_price_stats, compute_review_stats

# ---- which agent / task is being asked --------------------------------------------------

ROLE_TOOL = {
    "Review Analyst": "review_loader",
    "Price Tracker": "competitor_prices",
    "SEO Writer": "product_info",
    "Marketer": "product_info",
}
TASK_ROLE = {
    "TASK: Review analysis": "Review Analyst",
    "TASK: Pricing analysis": "Price Tracker",
    "TASK: SEO copywriting": "SEO Writer",
    "TASK: Launch campaign": "Marketer",
}
MANAGER_ROLE = "Store Manager"
_PRODUCT_ID = re.compile(r"Product ID: ([\w-]+)")
_ROLE_IN_PROMPT = re.compile(
    r"You are (Review Analyst|Price Tracker|SEO Writer|Marketer|Store Manager)"
)


# ---- text helpers ---------------------------------------------------------------------


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _clean(sentence: str) -> str:
    sentence = sentence.strip().rstrip(".!")
    return sentence[0].upper() + sentence[1:] if sentence else sentence


def _phrase(sentence: str, max_words: int = 6) -> str:
    """Short verbatim phrase: first clause of a sentence, at most ``max_words`` words."""
    clause = re.split(r"[,.;!]", sentence)[0]
    return " ".join(clause.lower().split()[:max_words])


def _fit(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` characters at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:-|&")
    return cut[:limit]


def _charm(price: float) -> int:
    """Round down to a whole-dollar price."""
    return max(1, int(math.floor(price)))


def _dollars(value: float) -> str:
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


# ---- deterministic "agents" -----------------------------------------------------------


def demo_review_insights(source: DataSource, product_id: str) -> ReviewInsights:
    """Rank recurring praise/complaint sentences straight from the reviews."""
    reviews = source.get_reviews(product_id)
    stats = compute_review_stats(reviews)
    praise: Counter[str] = Counter()
    complaints: Counter[str] = Counter()
    for review in reviews:
        for sentence in _sentences(review.text):
            if sentence.lower().startswith("only issue:"):
                complaints[_clean(sentence.split(":", 1)[1])] += 1
            elif review.rating >= 4:
                praise[_clean(sentence)] += 1
            elif review.rating <= 2:
                complaints[_clean(sentence)] += 1
    top_praises = [s for s, _ in praise.most_common(4)] or ["Customers are broadly satisfied"]
    top_complaints = [s for s, _ in complaints.most_common(4)] or ["No recurring complaints"]
    phrases = list(dict.fromkeys(_phrase(s) for s, _ in praise.most_common(8)))[:6]
    while len(phrases) < 3:
        phrases.append(_phrase(top_praises[0]))
    summary = (
        f"{stats.review_count} reviews average {stats.average_rating}/5 with "
        f"{stats.positive_pct:.0f}% positive and {stats.negative_pct:.0f}% negative. "
        f"Customers keep coming back to: {top_praises[0].lower()}. "
        f"The most common complaint is: {top_complaints[0].lower()}, which the listing "
        "and campaign should address directly."
    )
    return ReviewInsights(
        average_rating=stats.average_rating,
        sentiment_breakdown={
            "positive": stats.positive_pct,
            "neutral": stats.neutral_pct,
            "negative": stats.negative_pct,
        },
        top_praises=top_praises,
        top_complaints=top_complaints,
        customer_phrases=phrases,
        summary=summary,
    )


def demo_pricing_report(source: DataSource, product_id: str) -> PricingReport:
    """Rule-based price recommendation on top of the computed stats."""
    product = source.get_product(product_id)
    rows = source.get_competitor_prices(product_id)
    stats = compute_price_stats(product.our_price, rows)
    out_of_stock = [r.competitor for r in rows if not r.in_stock]
    our, avg, low, high = (
        stats.our_price,
        stats.competitor_avg,
        stats.competitor_min,
        stats.competitor_max,
    )
    if stats.position == "cheapest":
        target = min(low - 0.01, our * 1.08)
        why = (
            f"We are the cheapest at {_dollars(our)}, {abs(stats.diff_vs_avg_pct):.0f}% under the "
            f"{_dollars(avg)} average and below the lowest competitor ({_dollars(low)}). "
            "We can stay the cheapest option and compete on value instead of cutting further."
        )
    elif stats.position == "below_avg":
        target = min(avg * 0.97, our * 1.05)
        why = (
            f"At {_dollars(our)} we are {abs(stats.diff_vs_avg_pct):.0f}% below the "
            f"{_dollars(avg)} market average. A small increase captures margin while still "
            f"undercutting most listings (range {_dollars(low)}-{_dollars(high)})."
        )
    elif stats.position == "above_avg":
        target = max(avg, our * 0.95)
        why = (
            f"At {_dollars(our)} we are {stats.diff_vs_avg_pct:.0f}% above the {_dollars(avg)} "
            f"average. Moving to the average removes price as an objection, or the price can "
            "be held if a bundle adds clear value."
        )
    else:
        target = (avg + high) / 2
        why = (
            f"At {_dollars(our)} we are the most expensive listing, {stats.diff_vs_avg_pct:.0f}% "
            f"above the {_dollars(avg)} average and above the highest competitor "
            f"({_dollars(high)}). "
            "Moving between the average and the top of the market keeps a premium feel "
            "without losing price-sensitive shoppers."
        )
    if out_of_stock:
        why += (
            f" {', '.join(out_of_stock)} {'is' if len(out_of_stock) == 1 else 'are'} out of stock."
        )
    return PricingReport(
        our_price=our,
        competitor_min=low,
        competitor_max=high,
        competitor_avg=avg,
        position=stats.position,
        recommended_price=_charm(target),
        reasoning=why,
    )


def demo_seo_copy(source: DataSource, product_id: str) -> SEOCopy:
    """Template SEO copy that only uses real features and real customer phrases."""
    product = source.get_product(product_id)
    insights = demo_review_insights(source, product_id)
    praise = insights.top_praises[0].rstrip(".")
    phrases = insights.customer_phrases
    noun = product.category.split("/")[-1].strip()
    short_feature = re.split(r"[(,:]| with ", product.features[0])[0].strip()

    title = _fit(f"{product.name} | {short_feature}", 70)
    meta = _fit(
        f"{product.name}: {short_feature.lower()}. Rated {insights.average_rating}/5 by "
        f'real buyers - "{phrases[0]}". Shop now at {_dollars(product.our_price)}.',
        160,
    )
    bullets = [_fit(f, 120) for f in (product.features + product.features)[:5]]

    pool = [
        f"Meet the {product.name}, the {noun.lower()} customers can't stop talking about.",
        f"Buyers rate it {insights.average_rating} out of 5, and the reason comes up again and "
        f"again: {praise.lower()}.",
        f'In their own words: "{phrases[0]}".',
    ]
    pool += [f"It offers {f[0].lower() + f[1:]}." for f in product.features]
    if len(phrases) > 1:
        pool.append(f'Another shopper put it simply: "{phrases[1]}".')
    pool += [
        f"Whether you use it every day or only on the weekend, the {product.name} is built "
        "to keep up with real everyday routines, from long commutes to hot summers.",
        f"At {_dollars(product.our_price)}, it is priced to make the decision easy.",
        "Every order ships with a simple setup guide and our support team is one message "
        "away if you need help getting started.",
        f"Add the {product.name} to your cart today and see why so many buyers recommend it "
        "to friends and family.",
        "Check the feature list above, compare it with what you pay elsewhere, and you will "
        "see why this is one of the most reviewed products in its category on our store.",
        "If it is not right for you, our hassle-free returns make trying it risk-free.",
    ]
    words: list[str] = []
    for sentence in pool:
        if len(words) + len(sentence.split()) > 240:
            break
        words += sentence.split()
    filler = (
        f"Thousands of shoppers searching for a reliable {noun.lower()} end up choosing this "
        "one, and the reviews explain why better than we can."
    )
    while len(words) < 160:
        words += filler.split()
    keywords = list(
        dict.fromkeys(
            [
                product.name.lower(),
                noun.lower(),
                f"best {noun.lower()} 2026",
                f"{noun.lower()} under {_dollars(math.ceil(product.our_price / 500) * 500)}",
                *phrases[:3],
            ]
        )
    )
    return SEOCopy(
        title=title,
        meta_description=meta,
        bullet_points=bullets,
        long_description=" ".join(words),
        keywords=keywords,
    )


_AUDIENCE = {
    "audio": "Commuters, students and gym-goers aged 18-35 who want all-day wireless audio "
    "without paying flagship prices",
    "wearables": "Health-conscious young professionals aged 22-40 who want fitness tracking "
    "and calls on the wrist",
    "home & kitchen": "Office-goers, travellers and fitness enthusiasts who carry water all day",
    "bags": "College students and young professionals who commute daily with a laptop",
}
_PRICE_ANGLE: dict[PricePosition, str] = {
    "cheapest": "at the lowest price online",
    "below_avg": "at a better price than most stores",
    "above_avg": "with extra value that justifies every dollar",
    "most_expensive": "now at a limited-time launch price",
}


_HEADLINE_ANGLE: dict[PricePosition, str] = {
    "cheapest": "Lowest Price",
    "below_avg": "Better Price",
    "above_avg": "Worth Every Dollar",
    "most_expensive": "Launch Deal",
}


def _offer(pricing: PricingReport) -> str:
    if pricing.position == "cheapest":
        return (
            "No discount needed: we are already the lowest price "
            f"({_dollars(pricing.our_price)} vs "
            f"{_dollars(pricing.competitor_min)} elsewhere). Add value instead with free "
            "shipping and a free gift-wrap option during launch week."
        )
    if pricing.position == "below_avg":
        return (
            f"Launch week: extra 5% off with code LAUNCH5, on top of a price that is already "
            f"below the {_dollars(pricing.competitor_avg)} market average. Moves to "
            f"{_dollars(pricing.recommended_price)} after launch."
        )
    if pricing.position == "above_avg":
        return (
            "Value bundle instead of a price cut: free shipping, easy 30-day returns and a "
            f"bundled accessory, so {_dollars(pricing.our_price)} beats the "
            f"{_dollars(pricing.competitor_avg)} average on total value."
        )
    return (
        f"Limited-time 72-hour launch price of {_dollars(pricing.recommended_price)} (down from "
        f"{_dollars(pricing.our_price)}) to close the gap with competitors, plus free shipping."
    )


def demo_campaign_plan(source: DataSource, product_id: str) -> CampaignPlan:
    """Combine the other three demo outputs into one campaign, like the real Marketer."""
    product: Product = source.get_product(product_id)
    insights = demo_review_insights(source, product_id)
    pricing = demo_pricing_report(source, product_id)
    seo = demo_seo_copy(source, product_id)
    praise = insights.top_praises[0].rstrip(".")
    phrase = insights.customer_phrases[0]
    angle = _PRICE_ANGLE[pricing.position]
    category_key = product.category.split("/")[0].strip().lower()
    audience = _AUDIENCE.get(category_key, f"Online shoppers looking for a {product.category}")
    complaints = insights.top_complaints[:2]
    headline = _fit(f"{product.name.split()[0]} - {_HEADLINE_ANGLE[pricing.position]}", 30)
    hashtag = "#" + re.sub(r"\W", "", product.name.split()[0])
    return CampaignPlan.model_validate(
        {
            "target_audience": audience,
            "positioning_statement": (
                f"For {audience.split(' who ')[0].lower()}, the {product.name} is the "
                f"{product.category.split('/')[-1].strip().lower()} that real buyers love because "
                f'"{phrase}" - {angle}.'
            ),
            "key_message": f"{praise} - {angle}.",
            "offer": _offer(pricing),
            "instagram_caption": (
                f'"{phrase}" - that\'s what our customers say. {praise}. '
                f"Rated {insights.average_rating}/5. {_dollars(pricing.our_price)} with free "
                f"shipping. Link in bio. {hashtag} #LaunchWeek"
            ),
            "google_ad": {
                "headline": headline,
                "description": _fit(f"{praise}. Rated {insights.average_rating}/5. Shop now.", 90),
            },
            "email": {
                "subject": _fit(f"{phrase.capitalize()} - meet the {product.name}", 80),
                "body": (
                    f"Hi there,\n\nOur customers rate the {product.name} "
                    f'{insights.average_rating}/5, and one line keeps coming up: "{phrase}".\n\n'
                    + "\n".join(f"- {b}" for b in seo.bullet_points[:3])
                    + f"\n\n{_offer(pricing)}\n\nShop now and see for yourself.\n\nTeam ShopCrew"
                ),
            },
            "7_day_schedule": [
                {
                    "day": 1,
                    "channel": "Instagram",
                    "action": f'Launch reel built around "{phrase}"',
                },
                {
                    "day": 2,
                    "channel": "Email",
                    "action": "Send launch email with the offer to subscribers",
                },
                {
                    "day": 3,
                    "channel": "Google Ads",
                    "action": f"Start search ads on '{seo.keywords[2]}'",
                },
                {
                    "day": 4,
                    "channel": "Instagram Stories",
                    "action": "Share 3 real customer reviews as stories",
                },
                {"day": 5, "channel": "WhatsApp", "action": "Broadcast the offer to past buyers"},
                {
                    "day": 6,
                    "channel": "YouTube Shorts",
                    "action": "Post an honest FAQ video on the top complaint",
                },
                {
                    "day": 7,
                    "channel": "Email + Instagram",
                    "action": "Last-chance reminder before the offer ends",
                },
            ],
            "how_we_address_complaints": " ".join(
                f'"{c}": we answer this upfront in the FAQ and the day-6 video, show how to '
                "avoid or fix it, and point buyers to our easy returns."
                for c in complaints
            ),
        }
    )


DEMO_BUILDERS = {
    "Review Analyst": demo_review_insights,
    "Price Tracker": demo_pricing_report,
    "SEO Writer": demo_seo_copy,
    "Marketer": demo_campaign_plan,
}


# ---- the fake LLM ---------------------------------------------------------------------


class DemoLLM(BaseLLM):
    """Deterministic stand-in for a real LLM, speaking CrewAI's ReAct format."""

    def __init__(self, source: DataSource | None = None, **kwargs: Any) -> None:
        """Create the demo LLM. ``source`` defaults to the process-wide data source."""
        super().__init__(model="mock", **kwargs)
        self._source = source

    def supports_function_calling(self) -> bool:
        """Use CrewAI's text (ReAct) tool-calling protocol."""
        return False

    def get_input_tokens_count(self, messages: Any, *args: Any, **kwargs: Any) -> int:
        """Approximate tokens as characters / 4 (no warning: this model is fake anyway)."""
        if isinstance(messages, str):
            return len(messages) // 4
        return sum(len(str(m.get("content", ""))) for m in messages) // 4

    def call(
        self,
        messages: str | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any | None = None,
        from_agent: Any | None = None,
        response_model: Any | None = None,
        **kwargs: Any,
    ) -> str:
        """Return the next ReAct step for whichever agent is asking."""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        text = "\n".join(str(m.get("content", "")) for m in messages)
        role = getattr(from_agent, "role", None) or self._role_from_prompt(text)
        first_turn = not any(m.get("role") == "assistant" for m in messages)

        if role == MANAGER_ROLE:
            reply = self._manager_step(text, messages, first_turn)
        elif first_turn and role in ROLE_TOOL:
            product_id = self._product_id(text)
            reply = (
                f"Thought: I need the data for {product_id} first.\n"
                f"Action: {ROLE_TOOL[role]}\n"
                f'Action Input: {{"product_id": "{product_id}"}}'
            )
        else:
            reply = self._final_answer(role, text)

        self._track_token_usage_internal(
            {
                "prompt_tokens": len(text) // 4,
                "completion_tokens": len(reply) // 4,
                "total_tokens": (len(text) + len(reply)) // 4,
            }
        )
        return reply

    # -- helpers --

    @staticmethod
    def _role_from_prompt(text: str) -> str | None:
        match = _ROLE_IN_PROMPT.search(text)
        return match.group(1) if match else None

    @staticmethod
    def _product_id(text: str) -> str:
        match = _PRODUCT_ID.search(text)
        if not match:
            raise ValueError("DemoLLM could not find 'Product ID: ...' in the prompt")
        return match.group(1)

    def _final_answer(self, role: str | None, text: str) -> str:
        builder = DEMO_BUILDERS.get(role or "")
        if builder is None:
            raise ValueError(f"DemoLLM does not know how to answer as {role!r}")
        output = builder(self._source or default_source(), self._product_id(text))
        payload = json.dumps(output.model_dump(mode="json", by_alias=True), ensure_ascii=False)
        return f"Thought: I now know the final answer\nFinal Answer: {payload}"

    def _manager_step(self, text: str, messages: list[dict[str, Any]], first_turn: bool) -> str:
        if first_turn:
            marker = next((m for m in TASK_ROLE if m in text), None)
            if marker is None:
                raise ValueError("DemoLLM manager could not identify the task")
            coworker = TASK_ROLE[marker]
            product_id = self._product_id(text)
            task_text = text[text.index(marker) :].split("This is the expected criteria")[0]
            action_input = json.dumps(
                {
                    "task": task_text.strip(),
                    "context": f"Product ID: {product_id}",
                    "coworker": coworker,
                }
            )
            return (
                f"Thought: This is work for the {coworker}.\n"
                f"Action: Delegate work to coworker\nAction Input: {action_input}"
            )
        # Second turn: the coworker's answer is the last observation; pass it through.
        observation = ""
        for message in messages:
            content = str(message.get("content", ""))
            if "Observation:" in content:
                observation = content.rsplit("Observation:", 1)[1]
        start, end = observation.find("{"), observation.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("DemoLLM manager did not receive a JSON answer from its coworker")
        return "Thought: I now know the final answer\nFinal Answer: " + observation[start : end + 1]
