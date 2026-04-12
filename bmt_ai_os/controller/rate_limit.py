"""In-memory sliding-window rate limiter for BMT AI OS controller.

Provides per-IP rate limiting as a FastAPI dependency — no Redis required,
suitable for edge device deployments.

Configuration via environment variables:
    BMT_LOGIN_RATE_LIMIT      — "attempts:window_seconds" for login endpoint
                                (default: "5:300"  →  5 per 5 minutes)
    BMT_INFERENCE_RATE_LIMIT  — "requests:window_seconds" for inference endpoints
                                (default: "60:60"  →  60 per minute)
    BMT_SENSITIVE_RATE_LIMIT  — "requests:window_seconds" for sensitive endpoints
                                (default: "20:60"  →  20 per minute)
"""

from __future__ import annotations

import os
import time
from collections import deque
from threading import Lock
from typing import Deque

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Sliding-window rate limiter core
# ---------------------------------------------------------------------------


class SlidingWindowRateLimiter:
    """Thread-safe, in-memory sliding-window rate limiter.

    Tracks request timestamps per key (typically client IP).
    Old entries outside the window are evicted on each check.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        """Initialise with *limit* requests allowed per *window_seconds*."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self.limit = limit
        self.window_seconds = window_seconds

        # key → deque of float timestamps (monotonic)
        self._buckets: dict[str, Deque[float]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, key: str) -> tuple[bool, int, float]:
        """Check whether *key* is within the rate limit.

        Returns a tuple of:
            allowed (bool)      — True when the request is permitted
            remaining (int)     — requests remaining in the current window
            reset_at (float)    — Unix timestamp when the window resets

        The timestamp of the current request is recorded only when *allowed*
        is True (rejected requests do not consume a slot).
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            bucket = self._buckets.setdefault(key, deque())

            # Evict timestamps outside the current window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            count = len(bucket)

            if count >= self.limit:
                # Oldest timestamp in window tells us when a slot frees up
                oldest = bucket[0] if bucket else now
                reset_at = time.time() + (oldest - cutoff)
                return False, 0, reset_at

            # Record this request
            bucket.append(now)
            remaining = self.limit - count - 1
            # Window resets relative to the oldest recorded request
            if bucket:
                oldest = bucket[0]
                reset_at = time.time() + (oldest - cutoff)
            else:
                reset_at = time.time() + self.window_seconds

            return True, remaining, reset_at

    def evict_expired(self) -> None:
        """Remove all fully-expired buckets (optional housekeeping call)."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            empty_keys = [
                k for k, bucket in self._buckets.items() if not bucket or bucket[-1] <= cutoff
            ]
            for k in empty_keys:
                del self._buckets[k]


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_DEFAULT_LOGIN_RATE = "5:300"  # 5 attempts per 5 minutes
_DEFAULT_INFERENCE_RATE = "60:60"  # 60 requests per minute
_DEFAULT_SENSITIVE_RATE = "20:60"  # 20 requests per minute


def _parse_rate(env_value: str) -> tuple[int, int]:
    """Parse "limit:window_seconds" string into (limit, window_seconds).

    Raises ValueError when the format or values are invalid.
    """
    parts = env_value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Rate limit must be 'limit:window_seconds', got: {env_value!r}")
    limit = int(parts[0])
    window = int(parts[1])
    if limit <= 0 or window <= 0:
        raise ValueError("Both limit and window_seconds must be positive integers")
    return limit, window


def _build_limiter(env_var: str, default: str) -> SlidingWindowRateLimiter:
    raw = os.environ.get(env_var, default)
    try:
        limit, window = _parse_rate(raw)
    except ValueError:
        # Fall back to the default when the env var is malformed
        limit, window = _parse_rate(default)
    return SlidingWindowRateLimiter(limit=limit, window_seconds=window)


# ---------------------------------------------------------------------------
# Module-level limiter singletons (lazy-initialised per env var)
# ---------------------------------------------------------------------------

_login_limiter: SlidingWindowRateLimiter | None = None
_inference_limiter: SlidingWindowRateLimiter | None = None
_sensitive_limiter: SlidingWindowRateLimiter | None = None
_singleton_lock = Lock()


def get_login_limiter() -> SlidingWindowRateLimiter:
    """Return the module-level login rate-limiter singleton."""
    global _login_limiter
    if _login_limiter is None:
        with _singleton_lock:
            if _login_limiter is None:
                _login_limiter = _build_limiter("BMT_LOGIN_RATE_LIMIT", _DEFAULT_LOGIN_RATE)
    return _login_limiter


def get_inference_limiter() -> SlidingWindowRateLimiter:
    """Return the module-level inference rate-limiter singleton."""
    global _inference_limiter
    if _inference_limiter is None:
        with _singleton_lock:
            if _inference_limiter is None:
                _inference_limiter = _build_limiter(
                    "BMT_INFERENCE_RATE_LIMIT", _DEFAULT_INFERENCE_RATE
                )
    return _inference_limiter


def get_sensitive_limiter() -> SlidingWindowRateLimiter:
    """Return the module-level sensitive-endpoint rate-limiter singleton."""
    global _sensitive_limiter
    if _sensitive_limiter is None:
        with _singleton_lock:
            if _sensitive_limiter is None:
                _sensitive_limiter = _build_limiter(
                    "BMT_SENSITIVE_RATE_LIMIT", _DEFAULT_SENSITIVE_RATE
                )
    return _sensitive_limiter


def _reset_singletons() -> None:
    """Reset module-level singletons (test helper only)."""
    global _login_limiter, _inference_limiter, _sensitive_limiter
    _login_limiter = None
    _inference_limiter = None
    _sensitive_limiter = None


def _set_login_limiter(limiter: SlidingWindowRateLimiter) -> None:
    """Override the login limiter singleton (test helper only)."""
    global _login_limiter
    _login_limiter = limiter


def _set_inference_limiter(limiter: SlidingWindowRateLimiter) -> None:
    """Override the inference limiter singleton (test helper only)."""
    global _inference_limiter
    _inference_limiter = limiter


# ---------------------------------------------------------------------------
# Client IP extraction
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Return the best-effort client IP from the request.

    Respects ``X-Forwarded-For`` when present (reverse proxy deployments).
    Falls back to the direct connection address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first (leftmost) address — the originating client
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Rate-limit headers helper
# ---------------------------------------------------------------------------


def _rate_limit_headers(limit: int, remaining: int, reset_at: float) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(int(reset_at)),
    }


# ---------------------------------------------------------------------------
# 429 response builder
# ---------------------------------------------------------------------------


def _too_many_requests(limit: int, reset_at: float) -> JSONResponse:
    headers = _rate_limit_headers(limit, 0, reset_at)
    headers["Retry-After"] = str(max(1, int(reset_at - time.time())))
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "message": "Too many requests. Please try again later.",
                "type": "rate_limit_error",
                "code": "rate_limit_exceeded",
            }
        },
        headers=headers,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency factories
# ---------------------------------------------------------------------------


class RateLimitDep:
    """Callable FastAPI dependency that enforces rate limiting.

    Adds ``X-RateLimit-*`` headers to every response (allowed and denied).
    Returns HTTP 429 when the limit is exceeded.

    Usage::

        from fastapi import Depends
        from .rate_limit import login_rate_limit, inference_rate_limit

        @router.post("/login", dependencies=[Depends(login_rate_limit)])
        async def login(...): ...
    """

    def __init__(self, get_limiter_fn) -> None:
        self._get_limiter = get_limiter_fn

    async def __call__(self, request: Request, response: Response) -> None:
        limiter = self._get_limiter()
        ip = _client_ip(request)
        allowed, remaining, reset_at = limiter.check(ip)

        # Always inject rate-limit headers into the response
        headers = _rate_limit_headers(limiter.limit, remaining, reset_at)
        for name, value in headers.items():
            response.headers[name] = value

        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Too many requests. Please try again later.",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                },
                headers=_rate_limit_headers(limiter.limit, 0, reset_at)
                | {"Retry-After": str(max(1, int(reset_at - time.time())))},
            )


# Singleton dependency instances — import these directly in route modules
login_rate_limit = RateLimitDep(get_login_limiter)
inference_rate_limit = RateLimitDep(get_inference_limiter)
sensitive_rate_limit = RateLimitDep(get_sensitive_limiter)
