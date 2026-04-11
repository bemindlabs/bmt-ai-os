"""Middleware for the OpenAI-compatible API layer.

Provides:
- Optional API key authentication
- CORS configuration for IDE connections
- Request ID injection for log correlation
- Request logging with timing
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


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
# Request ID Injection
# ---------------------------------------------------------------------------

_HEADER_REQUEST_ID = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate a request ID for log correlation.

    Reads ``X-Request-ID`` from the incoming request headers.  If absent,
    a new UUID4 is generated.  The ID is:

    1. Stored in thread-local storage via :func:`bmt_ai_os.logging.set_request_id`
       so that all log records emitted during the request carry it as
       ``trace_id``.
    2. Echoed back in the ``X-Request-ID`` response header.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from bmt_ai_os.logging import clear_request_id, set_request_id

        request_id = request.headers.get(_HEADER_REQUEST_ID) or str(uuid.uuid4())
        set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            clear_request_id()

        response.headers[_HEADER_REQUEST_ID] = request_id
        return response


# ---------------------------------------------------------------------------
# Request Logging
# ---------------------------------------------------------------------------


_MAX_LOG_ENTRIES = 200
_recent_logs: list[dict] = []


def get_recent_logs() -> list[dict]:
    """Return a copy of the recent request log buffer."""
    return list(_recent_logs)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, elapsed time, and request ID."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from bmt_ai_os.logging import get_request_id

        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        request_id = get_request_id()
        logger.info(
            "%s %s %d %.1fms%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            f" [trace_id={request_id}]" if request_id else "",
        )

        entry = {
            "timestamp": time.time(),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "elapsed_ms": round(elapsed_ms, 1),
            "trace_id": request_id,
        }
        _recent_logs.append(entry)
        if len(_recent_logs) > _MAX_LOG_ENTRIES:
            _recent_logs.pop(0)

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
    2. JWT auth + RBAC (when users exist in the store)
    3. API key authentication (legacy fallback when no users are registered)
    4. Request ID injection — assigns/propagates X-Request-ID for log correlation
    5. Request logging (innermost — logs after response)
    """
    from .auth import JWTAuthMiddleware  # local import avoids circular deps at module load

    add_cors(app)
    app.add_middleware(JWTAuthMiddleware)
    app.add_middleware(APIKeyMiddleware, api_key=api_key)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
