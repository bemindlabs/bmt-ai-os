# BMT AI OS Controller — Single Docker Image
# Packages the controller, providers, and RAG pipeline into one container.
#
# Usage:
#   docker build -t bmt-ai-os:latest .
#   docker run -p 8080:8080 --network bmt-ai-net bmt-ai-os:latest

FROM python:3.12-slim AS base

LABEL maintainer="Bemind Technology Co., Ltd."
LABEL org.opencontainers.image.source="https://github.com/bemindlabs/bmt-ai-os"
LABEL com.bemind.component="controller"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    aiohttp>=3.9 \
    docker>=7.0 \
    pyyaml>=6.0 \
    fastapi>=0.115 \
    uvicorn>=0.34 \
    pydantic>=2.0

# Copy application code
COPY bmt-ai-os/controller/ /app/bmt_ai_os/controller/
COPY bmt-ai-os/providers/ /app/bmt_ai_os/providers/
COPY bmt-ai-os/rag/ /app/bmt_ai_os/rag/
COPY bmt-ai-os/ai-stack/docker-compose.yml /app/ai-stack/docker-compose.yml
RUN touch /app/bmt_ai_os/__init__.py

# Alias so both `controller.*` and `bmt_ai_os.*` imports resolve
RUN ln -sf /app/bmt_ai_os/controller /app/controller \
    && ln -sf /app/bmt_ai_os/providers /app/providers \
    && ln -sf /app/bmt_ai_os/rag /app/rag

ENV PYTHONPATH=/app
ENV BMT_COMPOSE_FILE=/app/ai-stack/docker-compose.yml

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8080/healthz || exit 1

CMD ["python3", "-m", "controller.main"]
