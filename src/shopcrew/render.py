"""Render SEO copy and campaign plans as Markdown files."""

from __future__ import annotations

from shopcrew.models import CampaignPlan, PricingReport, Product, SEOCopy


def seo_markdown(product: Product, seo: SEOCopy) -> str:
    """Markdown for ``seo_copy.md``."""
    bullets = "\n".join(f"- {b}" for b in seo.bullet_points)
    keywords = ", ".join(f"`{k}`" for k in seo.keywords)
    return f"""# SEO Copy: {product.name}

**Product ID:** `{product.id}`

## Title ({len(seo.title)}/70 chars)

{seo.title}

## Meta description ({len(seo.meta_description)}/160 chars)

{seo.meta_description}

## Key features

{bullets}

## Description ({len(seo.long_description.split())} words)

{seo.long_description}

## Keywords

{keywords}
"""


def campaign_markdown(product: Product, plan: CampaignPlan, pricing: PricingReport) -> str:
    """Markdown for ``campaign_plan.md``."""
    schedule = "\n".join(
        f"| {item.day} | {item.channel} | {item.action} |" for item in plan.seven_day_schedule
    )
    email_body = plan.email.body.replace("\n", "\n> ")
    return f"""# Launch Campaign: {product.name}

**Product ID:** `{product.id}` | **Price position:** {pricing.position.replace("_", " ")} \
| **Our price:** ${pricing.our_price:,.0f} | **Recommended:** ${pricing.recommended_price:,.0f}

## Target audience

{plan.target_audience}

## Positioning

{plan.positioning_statement}

## Key message

> **{plan.key_message}**

## Offer

{plan.offer}

## Instagram

{plan.instagram_caption}

## Google ad

- **Headline:** {plan.google_ad.headline}
- **Description:** {plan.google_ad.description}

## Email

**Subject:** {plan.email.subject}

> {email_body}

## 7-day schedule

| Day | Channel | Action |
|-----|---------|--------|
{schedule}

## How we address complaints

{plan.how_we_address_complaints}
"""
