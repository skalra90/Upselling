# One image, two roles:
#   API:    default CMD (uvicorn)
#   Worker: command override `python -m upsell_poc.worker`

ARG PYTHON_VERSION=3.12

# ---------- build: resolve dependencies from uv.lock ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (their own layer, so a code-only change does not reinstall them), project code second.
# Plain COPY/RUN only - no BuildKit cache or bind mounts - so every builder (Docker, Railway, Render) accepts it.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app config ./config
# Sample data, copied into /app/data by the entrypoint the first time that folder is empty.
COPY --chown=app:app sample_data/store ./seed
COPY docker/entrypoint.sh /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MODELS_CONFIG_PATH=/app/config/models.yaml \
    LOCAL_STORAGE_DIR=/app/data \
    WORK_DIR=/tmp/upsell-poc \
    PORT=8000 \
    WEB_CONCURRENCY=1

RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data /tmp/upsell-poc && chown -R app:app /app/data /tmp/upsell-poc
# Starts as root only to make a mounted disk writable (hosts mount it root-owned), then runs everything as `app`.
ENTRYPOINT ["/app/entrypoint.sh"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# --proxy-headers: correct client IP/scheme behind a load balancer or platform proxy (AWS ALB, Render, Railway).
# One web process by default: accounts live in a file and analysis runs inside the web process.
CMD ["sh", "-c", "exec uvicorn upsell_poc.api.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
