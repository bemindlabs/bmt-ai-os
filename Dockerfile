# BMT AI OS Controller
# Lightweight AI stack controller with multi-provider LLM support and RAG.
#
# Usage:
#   docker pull bemindlabs/bmt-ai-os
#   docker run -p 8080:8080 --network bmt-ai-net bemindlabs/bmt-ai-os
#
# With AI stack:
#   docker compose -f bmt_ai_os/ai-stack/docker-compose.yml up -d
#   docker run -p 8080:8080 --network bmt-ai-net bemindlabs/bmt-ai-os

# --- Stage 1: Build dependencies ---
# Digest pinned 2026-04-11 — python:3.12-alpine
FROM python:3.12-alpine@sha256:7747d47f92cfca63a6e2b50275e23dba8407c30d8ae929a88ddd49a5d3f2d331 AS builder

RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev cargo

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install \
    aiohttp>=3.9 \
    bcrypt>=4.0 \
    click>=8.0 \
    cryptography>=43.0 \
    docker>=7.0 \
    fastapi>=0.115 \
    prometheus-client>=0.21 \
    pydantic>=2.0 \
    pyjwt>=2.8 \
    pyyaml>=6.0 \
    requests>=2.31 \
    uvicorn>=0.34

# --- Stage 2: Runtime ---
# Digest pinned 2026-04-11 — python:3.12-alpine
FROM python:3.12-alpine@sha256:7747d47f92cfca63a6e2b50275e23dba8407c30d8ae929a88ddd49a5d3f2d331

LABEL maintainer="Bemind Technology Co., Ltd."
LABEL org.opencontainers.image.title="BMT AI OS"
LABEL org.opencontainers.image.description="AI-first OS controller for ARM64 — multi-provider LLM inference, RAG, and OpenAI-compatible API"
LABEL org.opencontainers.image.source="https://github.com/bemindlabs/bmt-ai-os"
LABEL org.opencontainers.image.version="2026.4.10"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.vendor="Bemind Technology Co., Ltd."

# Copy only the installed packages (no pip, no build tools)
COPY --from=builder /install /usr/local

# Minimal runtime deps
RUN apk upgrade --no-cache \
    && apk add --no-cache curl libffi openssl docker-cli docker-cli-compose \
    && adduser -D -s /bin/false bmt

WORKDIR /app

# Copy Python source
COPY bmt_ai_os/__init__.py /app/bmt_ai_os/__init__.py
COPY bmt_ai_os/cli.py /app/bmt_ai_os/cli.py
COPY bmt_ai_os/logging.py /app/bmt_ai_os/logging.py
COPY bmt_ai_os/secret_files.py /app/bmt_ai_os/secret_files.py
COPY bmt_ai_os/controller/ /app/bmt_ai_os/controller/
COPY bmt_ai_os/providers/ /app/bmt_ai_os/providers/
COPY bmt_ai_os/rag/ /app/bmt_ai_os/rag/
COPY bmt_ai_os/ota/ /app/bmt_ai_os/ota/
COPY bmt_ai_os/update/ /app/bmt_ai_os/update/
COPY bmt_ai_os/fleet/ /app/bmt_ai_os/fleet/
COPY bmt_ai_os/plugins/ /app/bmt_ai_os/plugins/
COPY bmt_ai_os/tls/ /app/bmt_ai_os/tls/
COPY bmt_ai_os/persona/ /app/bmt_ai_os/persona/
COPY bmt_ai_os/benchmark/ /app/bmt_ai_os/benchmark/
COPY bmt_ai_os/mcp/ /app/bmt_ai_os/mcp/
COPY bmt_ai_os/memory/ /app/bmt_ai_os/memory/
COPY bmt_ai_os/messaging/ /app/bmt_ai_os/messaging/
COPY bmt_ai_os/training/ /app/bmt_ai_os/training/
COPY bmt_ai_os/ai-stack/docker-compose.yml /app/ai-stack/docker-compose.yml
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -e /app 2>/dev/null || true

ENV PYTHONPATH=/app \
    BMT_COMPOSE_FILE=/app/ai-stack/docker-compose.yml \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8080/healthz || exit 1

USER bmt
CMD ["python3", "-m", "bmt_ai_os.controller.main"]
