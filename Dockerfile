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
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install \
    aiohttp>=3.9 \
    docker>=7.0 \
    pyyaml>=6.0 \
    fastapi>=0.115 \
    uvicorn>=0.34 \
    pydantic>=2.0

# --- Stage 2: Runtime ---
FROM python:3.12-slim

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
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false bmt

WORKDIR /app

# Copy only Python source (no configs, no shell scripts, no kernel)
COPY bmt_ai_os/__init__.py /app/bmt_ai_os/__init__.py
COPY bmt_ai_os/controller/ /app/bmt_ai_os/controller/
COPY bmt_ai_os/providers/ /app/bmt_ai_os/providers/
COPY bmt_ai_os/rag/ /app/bmt_ai_os/rag/
COPY bmt_ai_os/ai-stack/docker-compose.yml /app/ai-stack/docker-compose.yml

ENV PYTHONPATH=/app \
    BMT_COMPOSE_FILE=/app/ai-stack/docker-compose.yml \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8080/healthz || exit 1

USER bmt
CMD ["python3", "-m", "bmt_ai_os.controller.main"]
