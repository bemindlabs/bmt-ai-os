"""Middleware for the OpenAI-compatible API layer.

Provides:
- Optional API key authentication
- CORS configuration for IDE connections
- Request logging with timing
- In-memory rate limiting per IP
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

# Sliding-window rate limit rules: path prefix → (max_requests, window_seconds)
_RATE_LIMIT_RULES: list[tuple[str, int, int]] = [
    ("/api/v1/auth/login", 5, 60),  # 5 requests per minute per IP
    ("/v1/chat/completions", 30, 60),  # 30 requests per minute per IP
]


class _RateLimitBucket:
    """Sliding-window token bucket for a single IP + path pair."""

    __slots__ = ("timestamps", "lock")

    def __init__(self) -> None:
        self.timestamps: list[float] = []
        self.lock = Lock()

    def is_allowed(self, max_requests: int, window: int) -> bool:
        """Return True if the request is allowed under the limit."""
        now = time.monotonic()
        cutoff = now - window
        with self.lock:
            # Evict timestamps outside the sliding window
            self.timestamps = [t for t in self.timestamps if t > cutoff]
            if len(self.timestamps) >= max_requests:
                return False
            self.timestamps.append(now)
            return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory per-IP rate limiter.

    Enforces sliding-window limits for sensitive endpoints:
    - /api/v1/auth/login: 5 requests per minute per IP
    - /v1/chat/completions: 30 requests per minute per IP

    The client IP is taken from the ``X-Forwarded-For`` header when present
    (for reverse-proxy deployments), falling back to the direct connection IP.

    State is stored in-memory and is not shared across processes. For
    multi-process deployments, replace the in-memory store with Redis.
    """

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        # buckets[(ip, path_prefix)] → _RateLimitBucket
        self._buckets: dict[tuple[str, str], _RateLimitBucket] = defaultdict(_RateLimitBucket)

    def _client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        ip = self._client_ip(request)

        for prefix, max_req, window in _RATE_LIMIT_RULES:
            if path.startswith(prefix):
                bucket = self._buckets[(ip, prefix)]
                if not bucket.is_allowed(max_req, window):
                    logger.warning(
                        "Rate limit exceeded: ip=%s path=%s limit=%d/%ds",
                        ip,
                        prefix,
                        max_req,
                        window,
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "message": (
                                    f"Rate limit exceeded. Maximum {max_req} requests "
                                    f"per {window} seconds for this endpoint."
                                ),
                                "type": "rate_limit_error",
                                "code": "too_many_requests",
                            }
                        },
                        headers={"Retry-After": str(window)},
                    )
                break  # Only apply the first matching rule

        return await call_next(request)


# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------

_ENV_API_KEY = "BMT_API_KEY"


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <key>`` when *BMT_API_KEY* is set.

    If the environment variable is **not** set the middleware is a no-op,
    making authentication opt-in for local / air-gapped deployments.

    Endpoints under ``/healthz`` and ``/docs`` are always exempt.
    """

    _EXEMPT_PREFIXES = ("/healthz", "/docs", "/openapi.json", "/redoc")

    def __init__(self, app: FastAPI, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = api_key or os.environ.get(_ENV_API_KEY)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._api_key is None:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in self._EXEMPT_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = ""

        if token != self._api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Invalid API key.",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Request Logging
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, and elapsed time."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


# ---------------------------------------------------------------------------
# CORS setup
# ---------------------------------------------------------------------------


_DEFAULT_CORS_ORIGINS = [
    "http://localhost:*",
    "http://127.0.0.1:*",
    "https://localhost:*",
    "vscode-webview://*",
    "cursor://*",
    "app://*",
    "tauri://*",
]

_ENV_CORS_ORIGINS = "BMT_CORS_ORIGINS"


def add_cors(app: FastAPI) -> None:
    """Configure CORS for IDE and local access.

    IDE plugins (Cursor, VS Code extensions for Copilot/Cody) connect from
    various origins. Allowed origins are configurable via ``BMT_CORS_ORIGINS``
    (comma-separated). Defaults to localhost + IDE schemes.
    """
    env_origins = os.environ.get(_ENV_CORS_ORIGINS)
    if env_origins:
        origins = [o.strip() for o in env_origins.split(",")]
    else:
        origins = _DEFAULT_CORS_ORIGINS

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )


# ---------------------------------------------------------------------------
# Convenience: apply all middleware
# ---------------------------------------------------------------------------


def apply_middleware(app: FastAPI, *, api_key: str | None = None) -> None:
    """Apply all middleware to the FastAPI application.

    Order matters: outermost middleware runs first.

    1. CORS (outermost — must run before auth to handle preflight)
    2. Rate limiting (applied before auth to protect login endpoint)
    3. JWT auth + RBAC (when users exist in the store)
    4. API key authentication (legacy fallback when no users are registered)
    5. Request logging (innermost — logs after response)
    """
    from .auth import JWTAuthMiddleware  # local import avoids circular deps at module load

    add_cors(app)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(JWTAuthMiddleware)
    app.add_middleware(APIKeyMiddleware, api_key=api_key)
    app.add_middleware(RequestLoggingMiddleware)
