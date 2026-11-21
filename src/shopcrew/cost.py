"""Token usage and estimated cost for a run."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

# USD per 1M tokens (input, output). Anthropic first-party API rates.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}


@dataclass(frozen=True)
class CostEstimate:
    """Token counts and the estimated USD cost (``None`` if the model's rate is unknown)."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    requests: int
    usd: float | None

    def to_dict(self) -> dict:
        """Plain-dict form for JSON output."""
        return asdict(self)

    def describe(self) -> str:
        """One-line human summary."""
        cost = f"${self.usd:.4f}" if self.usd is not None else "unknown (rate not configured)"
        return (
            f"Tokens: {self.total_tokens:,} ({self.prompt_tokens:,} in / "
            f"{self.completion_tokens:,} out, {self.requests} LLM calls) - "
            f"estimated cost: {cost}"
        )


def _rates(model: str) -> tuple[float, float] | None:
    env_in, env_out = os.getenv("PRICE_INPUT_PER_MTOK"), os.getenv("PRICE_OUTPUT_PER_MTOK")
    if env_in and env_out:
        return float(env_in), float(env_out)
    if model.strip().lower() == "mock" or model.lower().startswith(("ollama/", "ollama_chat/")):
        return (0.0, 0.0)  # offline demo / self-hosted: no API bill
    name = model.split("/")[-1].lower()
    # Longest key first so "claude-sonnet-5-5" wins over "claude-sonnet-5".
    for key in sorted(PRICES_PER_MTOK, key=len, reverse=True):
        if name.startswith(key):
            return PRICES_PER_MTOK[key]
    return None


def estimate_cost(model: str, usage: dict) -> CostEstimate:
    """Build a ``CostEstimate`` from a CrewAI ``UsageMetrics`` dump."""
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    rates = _rates(model)
    usd = None
    if rates is not None:
        usd = round(prompt / 1e6 * rates[0] + completion / 1e6 * rates[1], 6)
    return CostEstimate(
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=int(usage.get("total_tokens", prompt + completion) or 0),
        requests=int(usage.get("successful_requests", 0) or 0),
        usd=usd,
    )
