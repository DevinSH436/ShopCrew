"""Deterministic checks for marketing claims the product data does not support.

Runs on the SEO copy and the campaign plan, with no extra LLM call. It catches four kinds
of claim that small and large models alike tend to invent:

* exclusivity / guarantees   - "the only earbuds", "#1", "guaranteed", "100%"
* product-change claims      - "we've optimized the case", "new and improved"
* features the product lacks - ANC, GPS, wireless charging, "waterproof" without IP67/68
* duration figures           - "7 days of battery" when the feature list says 40 hours

Quoting a real customer is allowed: quoted text that appears in a review is skipped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from shopcrew.models import Product


@dataclass(frozen=True)
class ClaimIssue:
    """One unsupported claim."""

    kind: str
    phrase: str
    sentence: str

    def describe(self) -> str:
        """Human-readable one-liner."""
        return f'{self.kind}: "{self.phrase}" in "{self.sentence}"'


_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|‘[^’]*’|(?<!\w)'[^']{3,}'(?!\w)")
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
# Words that turn a feature mention into a denial or an honest discussion ("no ANC",
# "mic in wind vs ANC", "customers miss ANC") rather than a claim that we have it.
_NEGATION = re.compile(
    r"\b(no|not|without|lacks?|lacking|doesn'?t|does not|don'?t|do not|isn'?t|never promise"
    r"|vs\.?|versus|compared (?:to|with)|instead of|missing|miss|absence|honest\w*"
    r"|complain\w*)\b",
    re.I,
)

_EXCLUSIVITY = re.compile(
    r"\b(the only\b|only (?:earbuds|watch|smartwatch|bottle|backpack|product|one)\b"
    r"|world'?s (?:first|best|only)|#1\b|number one|best[- ]selling|guarantee[ds]?\b|100\s?%)",
    re.I,
)
_PRODUCT_CHANGE = re.compile(
    r"\b(we(?:'ve| have)? (?:optimi[sz]ed|improved|upgraded|redesigned|re-?engineered|fixed|"
    r"enhanced|added)|new and improved|new version|now with)\b",
    re.I,
)

# feature claim pattern -> pattern that must appear in the product's features to allow it
_FEATURES: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "active noise cancellation": (
        re.compile(r"\b(active noise[- ]cancel\w*|ANC)\b", re.I),
        re.compile(r"\b(active noise|ANC)\b", re.I),
    ),
    "GPS": (re.compile(r"\b(built[- ]in GPS|GPS)\b", re.I), re.compile(r"\bGPS\b", re.I)),
    "wireless charging": (
        re.compile(r"\bwireless(?:ly)? charg\w*", re.I),
        re.compile(r"\bwireless charg", re.I),
    ),
    "waterproof": (
        re.compile(r"\bwater[- ]?proof\b", re.I),
        # Immersion ratings: IP67/68, IPX7/X8, 5+ ATM (swim-proof). IPX4/IPX5 are only splash.
        re.compile(r"\b(water[- ]?proof|swim[- ]?proof|IP[6X][78]|(?:[5-9]|10)\s?ATM)\b", re.I),
    ),
    "warranty": (
        re.compile(
            r"\b(?:\d+[- ](?:year|yr|month)s?(?:[- ]\w+)?[- ]warranty|extended warranty)\b", re.I
        ),
        re.compile(r"\bwarranty\b", re.I),
    ),
}

_DURATION = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(hours?|hrs?|h|minutes?|mins?|days?|weeks?)\b", re.I
)
_BATTERY_CONTEXT = re.compile(
    r"\b(batter\w*|playtime|playback|charg\w*|lasts?|cold|hot|power)\b", re.I
)
_VAGUE_LONG_DURATION = re.compile(
    r"\b(all week|a week|for days|day \d+ to day \d+|week-long)\b", re.I
)
_MINUTES = {
    "h": 60,
    "hr": 60,
    "hrs": 60,
    "hour": 60,
    "hours": 60,
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "day": 1440,
    "days": 1440,
    "week": 10080,
    "weeks": 10080,
}


def _minutes(value: str, unit: str) -> float:
    return float(value) * _MINUTES[unit.lower()]


def _feature_durations(features: Iterable[str]) -> set[float]:
    return {_minutes(v, u) for f in features for v, u in _DURATION.findall(f)}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCES.split(text) if s.strip()]


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def find_unsupported_claims(
    texts: Iterable[str], product: Product, customer_texts: Iterable[str] = ()
) -> list[ClaimIssue]:
    """Return every claim in ``texts`` that ``product``'s feature list does not back up.

    ``customer_texts`` are the product's reviews. Customer language is not our claim: a
    quoted phrase found in the reviews, or a whole review sentence repeated verbatim, is
    skipped. Other quoted text (a slogan the model invented) is checked like everything else.
    """
    features = " | ".join(product.features)
    allowed_durations = _feature_durations(product.features)
    # "all week", "a week", "day 1 to day 7" are only OK if a feature lasts a week or more
    feature_has_long_duration = any(m >= 7 * 1440 for m in allowed_durations)
    customer_texts = list(customer_texts)
    reviews = " | ".join(_normalise(t) for t in customer_texts)
    review_sentences = sorted(
        {_clause.strip(" .!?") for t in customer_texts for _clause in _sentences(t)},
        key=len,
        reverse=True,
    )
    review_sentences = [s for s in review_sentences if len(s) >= 15]
    issues: list[ClaimIssue] = []

    def drop_customer_quotes(sentence: str) -> str:
        def replace(match: re.Match[str]) -> str:
            inner = _normalise(match.group(0))
            return " " if inner and inner in reviews else match.group(0)

        body = _QUOTED.sub(replace, sentence)
        lowered = body.lower()
        for review_sentence in review_sentences:  # unquoted, verbatim customer sentences
            start = lowered.find(review_sentence.lower())
            if start != -1:
                body = body[:start] + " " + body[start + len(review_sentence) :]
                lowered = body.lower()
        return body

    for text in texts:
        for sentence in _sentences(text):
            body = drop_customer_quotes(sentence)
            negated = bool(_NEGATION.search(body))

            if match := _EXCLUSIVITY.search(body):
                issues.append(ClaimIssue("exclusivity/guarantee", match.group(0), sentence))
            if match := _PRODUCT_CHANGE.search(body):
                issues.append(ClaimIssue("unverified product change", match.group(0), sentence))
            if not negated:
                for name, (claim, support) in _FEATURES.items():
                    if (match := claim.search(body)) and not support.search(features):
                        kind = f"feature not listed ({name})"
                        issues.append(ClaimIssue(kind, match.group(0), sentence))

            if _BATTERY_CONTEXT.search(body):
                for value, unit in _DURATION.findall(body):
                    if _minutes(value, unit) not in allowed_durations:
                        issues.append(
                            ClaimIssue("duration not in features", f"{value} {unit}", sentence)
                        )
                if not feature_has_long_duration and (match := _VAGUE_LONG_DURATION.search(body)):
                    issues.append(ClaimIssue("duration not in features", match.group(0), sentence))

    # de-duplicate (the same claim often repeats across fields)
    unique: dict[tuple[str, str], ClaimIssue] = {}
    for issue in issues:
        unique.setdefault((issue.kind, issue.phrase.lower()), issue)
    return list(unique.values())


def collect_text(value: object) -> list[str]:
    """All string values inside a (nested) dict/list, e.g. a model dump."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in collect_text(v)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in collect_text(v)]
    return []
