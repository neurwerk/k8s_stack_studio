# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.12.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.12-slim

LABEL org.opencontainers.image.source="https://github.com/neurwerk/k8s_stack_studio"
LABEL org.opencontainers.image.description="AI Stack Studio API"
LABEL org.opencontainers.image.licenses="MIT"

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY LICENSE /licenses/LICENSE

USER appuser
EXPOSE 4010 4090
CMD ["k8s-stack-studio"]
