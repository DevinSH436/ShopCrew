"""Build the LLM every agent uses, from environment variables.

``MODEL`` takes a LiteLLM-style id (``anthropic/claude-sonnet-5-5``, ``openai/gpt-4o``,
``gemini/gemini-2.0-flash``, ``ollama/llama3.1``...) or ``mock`` for the offline demo.
"""

from __future__ import annotations

import os

from crewai import LLM
from crewai.llms.base_llm import BaseLLM
from dotenv import load_dotenv

from shopcrew.exceptions import ConfigError

DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"
MOCK_MODEL = "mock"

# Provider prefix -> env var holding its API key.
_KEY_FOR_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def configured_model() -> str:
    """Return the model id from ``MODEL`` (after loading ``.env``)."""
    load_dotenv()
    return (os.getenv("MODEL") or DEFAULT_MODEL).strip()


def is_mock(model: str) -> bool:
    """True if ``model`` selects the offline demo LLM."""
    return model.strip().lower() == MOCK_MODEL


def _temperature() -> float | None:
    raw = os.getenv("TEMPERATURE")
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError as err:
        raise ConfigError(f"TEMPERATURE must be a number, got '{raw}'") from err


def build_llm(model: str | None = None, source: object | None = None) -> BaseLLM:
    """Create the LLM for ``model`` (defaults to ``MODEL`` env var).

    ``source`` is only used by the offline demo LLM, which reads the same data as the tools.

    Raises:
        ConfigError: if the provider's API key is missing.
    """
    load_dotenv()
    model = (model or configured_model()).strip()
    if is_mock(model):
        from shopcrew.demo import DemoLLM

        return DemoLLM(source=source)  # type: ignore[arg-type]

    provider = model.split("/", 1)[0].lower() if "/" in model else ""
    key_var = _KEY_FOR_PROVIDER.get(provider)
    if key_var and not os.getenv(key_var):
        raise ConfigError(
            f"{key_var} is not set but MODEL={model} needs it. Add it to .env, "
            "or set MODEL=mock to run the offline demo without an API key."
        )

    kwargs: dict[str, object] = {}
    temperature = _temperature()
    # Current Claude models reject non-default sampling parameters (temperature/top_p)
    # with a 400, so TEMPERATURE only applies to other providers.
    if temperature is not None and provider != "anthropic":
        kwargs["temperature"] = temperature
    if provider in {"ollama", "ollama_chat"}:
        return _ollama_llm(model.split("/", 1)[1], kwargs)
    return LLM(model=model, **kwargs)


def _ollama_llm(name: str, kwargs: dict[str, object]) -> BaseLLM:
    """Self-hosted Ollama model via Ollama's native chat API.

    CrewAI's default Ollama route uses the OpenAI-compatible endpoint, which cannot set
    the context window, so Ollama falls back to its small default (4096 tokens) and
    silently truncates our prompts (36 reviews + output schema). The native API accepts
    ``num_ctx`` per request.
    """
    base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434"
    if not base_url.startswith("http"):
        base_url = f"http://{base_url}"
    try:
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX") or 16384)
        max_tokens = int(os.getenv("OLLAMA_MAX_TOKENS") or 8192)
    except ValueError as err:
        raise ConfigError("OLLAMA_NUM_CTX and OLLAMA_MAX_TOKENS must be integers") from err
    # Reasoning models (qwen3.x, deepseek-r1...) spend most of their output budget
    # "thinking" by default; off is ~5x faster and keeps JSON answers from being cut off.
    think = os.getenv("OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes"}
    return LLM(
        model=f"ollama_chat/{name}",
        is_litellm=True,
        base_url=base_url,
        num_ctx=num_ctx,
        max_tokens=max_tokens,
        context_window_size=num_ctx,  # else CrewAI assumes 8k and trims the context
        think=think,
        timeout=600,
        **kwargs,
    )
