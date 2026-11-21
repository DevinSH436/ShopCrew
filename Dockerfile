# syntax=docker/dockerfile:1.7
# One image for both apps: the ShopCrew dashboard (default CMD, port 8501) and the
# Northcart store (docker-compose 'store' service, port 8000). Defaults to the offline demo (MODEL=mock); pass
# ANTHROPIC_API_KEY and MODEL at runtime for real LLM output.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 1) Dependencies only, so this layer is cached until pyproject/uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) Project code and sample data.
COPY src ./src
COPY app ./app
COPY data ./data
COPY .streamlit ./.streamlit
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 3) Run as an unprivileged user; outputs/, var/ (store DB) and media/ are writable.
RUN useradd --create-home --uid 1000 shopcrew \
    && mkdir -p /app/outputs /app/var /app/media \
    && chown -R shopcrew:shopcrew /app/outputs /app/var /app/media
USER shopcrew

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/app/data \
    OUTPUTS_DIR=/app/outputs \
    STORE_DB=/app/var/store.db \
    STORE_MEDIA_DIR=/app/media \
    MODEL=mock \
    CREWAI_DISABLE_TELEMETRY=true \
    OTEL_SDK_DISABLED=true

EXPOSE 8501 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app/dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
