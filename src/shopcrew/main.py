"""Command-line entry point.

Examples::

    python -m shopcrew.main --product earbuds-01
    python -m shopcrew.main --all
    python -m shopcrew.main --product earbuds-01 --process hierarchical
    python -m shopcrew.main --list
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from shopcrew.datasource import SOURCES, get_data_source
from shopcrew.exceptions import ShopCrewError
from shopcrew.runner import RunEvent, RunResult, run_crew


def build_parser() -> argparse.ArgumentParser:
    """CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="shopcrew",
        description="Run the ShopCrew multi-agent team for one or all products.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--product", help="Product ID to run, e.g. earbuds-01")
    target.add_argument("--all", action="store_true", help="Run for every product")
    target.add_argument("--list", action="store_true", help="List product IDs and exit")
    parser.add_argument(
        "--process",
        choices=["sequential", "hierarchical"],
        default="sequential",
        help="sequential (default) or hierarchical (a manager agent delegates)",
    )
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default=None,
        help="Data source (default: DATA_SOURCE env var, else local). Only 'local' works.",
    )
    parser.add_argument("--model", default=None, help="Override MODEL, e.g. mock")
    parser.add_argument("--quiet", action="store_true", help="Hide CrewAI's agent trace")
    return parser


def _print_event(event: RunEvent) -> None:
    if event.kind in {"started", "completed", "failed", "tool", "run_started"}:
        print(event.line(), flush=True)


def _print_summary(result: RunResult) -> None:
    pricing, campaign = result.pricing, result.campaign
    print()
    print("=" * 72)
    print(f"{result.product.name} ({result.product.id})")
    print("=" * 72)
    print(
        f"Reviews  : {result.insights.average_rating}/5, "
        f"{result.insights.sentiment_breakdown.positive:.0f}% positive. "
        f"Top praise: {result.insights.top_praises[0]}"
    )
    print(
        f"Pricing  : ${pricing.our_price:,.2f} is {pricing.position.replace('_', ' ')} "
        f"(market ${pricing.competitor_min:,.2f}-${pricing.competitor_max:,.2f}); "
        f"recommend ${pricing.recommended_price:,.2f}"
    )
    print(f"SEO title: {result.seo.title}")
    print(f"Campaign : {campaign.key_message}")
    print(f"Offer    : {campaign.offer}")
    if result.notes:
        print(f"Notes    : {len(result.notes)} guardrail correction(s), see run_log.txt")
    print(f"Saved to : {result.out_dir}")
    print(result.cost.describe())


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        source = get_data_source(args.source)
        products = source.list_products()
        if args.list:
            for product in products:
                print(f"{product.id:<14} {product.name}  (${product.our_price:,.2f})")
            return 0
        ids = [p.id for p in products] if args.all else [args.product]
        total_usd, any_unknown = 0.0, False
        for product_id in ids:
            result = run_crew(
                product_id,
                process=args.process,
                model=args.model,
                source=source,
                on_event=_print_event,
                verbose=False if args.quiet else None,
            )
            _print_summary(result)
            if result.cost.usd is None:
                any_unknown = True
            else:
                total_usd += result.cost.usd
        if len(ids) > 1:
            suffix = " (some rates unknown)" if any_unknown else ""
            print(f"\nTotal estimated cost for {len(ids)} products: ${total_usd:.4f}{suffix}")
    except ShopCrewError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
