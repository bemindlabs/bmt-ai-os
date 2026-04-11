"""Provider CRUD API — dynamic provider configuration with SQLite persistence.

Endpoints
---------
GET    /api/v1/providers/config            — list all configured providers (API keys masked)
POST   /api/v1/providers/config            — register a new provider
PUT    /api/v1/providers/config/{name}     — update a provider's config
DELETE /api/v1/providers/config/{name}     — remove a provider
POST   /api/v1/providers/config/{name}/test — test provider connectivity

Providers are persisted to SQLite so they survive controller restarts.
On registration the provider is also dynamically instantiated and added
to the global ProviderRegistry.
"""

from __future__ import annotations

import importlib
import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from bmt_ai_os.providers.base import ProviderHealth
from bmt_ai_os.providers.registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/providers/config", tags=["provider-config"])

# ---------------------------------------------------------------------------
# Provider type → (module, class) map
# ---------------------------------------------------------------------------

PROVIDER_TYPES: dict[str, tuple[str, str]] = {
    "ollama": ("bmt_ai_os.providers.ollama", "OllamaProvider"),
    "openai": ("bmt_ai_os.providers.openai_provider", "OpenAIProvider"),
    "anthropic": ("bmt_ai_os.providers.anthropic_provider", "AnthropicProvider"),
    "gemini": ("bmt_ai_os.providers.gemini_provider", "GeminiProvider"),
    "groq": ("bmt_ai_os.providers.groq_provider", "GroqProvider"),
    "mistral": ("bmt_ai_os.providers.mistral_provider", "MistralProvider"),
    "vllm": ("bmt_ai_os.providers.vllm", "VLLMProvider"),
    "llamacpp": ("bmt_ai_os.providers.llamacpp", "LlamaCppProvider"),
}

# Default base URLs per provider type
PROVIDER_DEFAULT_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "vllm": "http://localhost:8000/v1",
    "llamacpp": "http://localhost:8080",
}

# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/var/lib/bmt/provider_configs.db"
_ENV_DB_PATH = "BMT_PROVIDER_CONFIG_DB"
_db_lock = threading.Lock()


def _resolve_db_path() -> str:
    from_env = os.environ.get(_ENV_DB_PATH)
    if from_env:
        return from_env
    import pathlib

    target = pathlib.Path(_DEFAULT_DB_PATH)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        test = target.parent / ".bmt-provconf-write-test"
        test.touch()
        test.unlink()
        return str(target)
    except OSError:
        fd, tmp_path = tempfile.mkstemp(prefix="bmt-provconf-", suffix=".db")
        os.close(fd)
        logger.warning(
            "Provider config DB %s not writable; using temp file %s",
            _DEFAULT_DB_PATH,
            tmp_path,
        )
        return tmp_path


_DB_PATH: str | None = None


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        with _db_lock:
            if _DB_PATH is None:
                _DB_PATH = _resolve_db_path()
    return _DB_PATH


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_db() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_configs (
                name          TEXT PRIMARY KEY,
                provider_type TEXT NOT NULL,
                base_url      TEXT NOT NULL DEFAULT '',
                api_key       TEXT NOT NULL DEFAULT '',
                default_model TEXT NOT NULL DEFAULT '',
                enabled       INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )


# Initialise on module import
_init_db()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ProviderConfigIn(BaseModel):
    name: str
    provider_type: str
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    enabled: bool = True

    @field_validator("provider_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in PROVIDER_TYPES:
            raise ValueError(
                f"Unknown provider type '{v}'. Must be one of: {', '.join(PROVIDER_TYPES)}"
            )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Provider name must not be empty")
        return v


class ProviderConfigUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_key(key: str) -> str:
    """Return a masked API key — show first 4 chars then asterisks."""
    if not key:
        return ""
    visible = key[:4]
    return f"{visible}{'*' * min(len(key) - 4, 12)}"


def _row_to_dict(row: sqlite3.Row, mask_key: bool = True) -> dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    if mask_key:
        d["api_key"] = _mask_key(d.get("api_key", ""))
    return d


def _instantiate_provider(
    provider_type: str,
    base_url: str,
    api_key: str,
    default_model: str,
) -> Any:
    """Dynamically import and instantiate a provider class."""
    module_path, class_name = PROVIDER_TYPES[provider_type]
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    kwargs: dict[str, Any] = {}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if default_model:
        kwargs["default_model"] = default_model

    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_provider_configs() -> dict:
    """Return all configured providers with API keys masked."""
    with _conn() as con:
        rows = con.execute("SELECT * FROM provider_configs ORDER BY name").fetchall()
    return {"providers": [_row_to_dict(r) for r in rows]}


@router.post("", status_code=201)
async def create_provider_config(body: ProviderConfigIn) -> dict:
    """Register a new provider and add it to the live registry."""
    now = datetime.now(timezone.utc).isoformat()

    # Fill default base_url if not supplied
    effective_base_url = body.base_url or PROVIDER_DEFAULT_URLS.get(body.provider_type, "")

    with _conn() as con:
        existing = con.execute(
            "SELECT name FROM provider_configs WHERE name = ?", (body.name,)
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Provider '{body.name}' already exists. Use PUT to update.",
            )
        con.execute(
            """
            INSERT INTO provider_configs
                (name, provider_type, base_url, api_key,
                 default_model, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                body.name,
                body.provider_type,
                effective_base_url,
                body.api_key,
                body.default_model,
                int(body.enabled),
                now,
                now,
            ),
        )

    # Instantiate and register in the live registry when enabled
    if body.enabled:
        try:
            provider = _instantiate_provider(
                body.provider_type,
                effective_base_url,
                body.api_key,
                body.default_model,
            )
            get_registry().register(body.name, provider)
            logger.info(
                "Provider '%s' (%s) registered in live registry.",
                body.name,
                body.provider_type,
            )
        except Exception as exc:
            logger.warning(
                "Provider '%s' persisted but could not be instantiated: %s",
                body.name,
                exc,
            )

    return {
        "name": body.name,
        "provider_type": body.provider_type,
        "base_url": effective_base_url,
        "api_key": _mask_key(body.api_key),
        "default_model": body.default_model,
        "enabled": body.enabled,
        "created_at": now,
        "updated_at": now,
    }


@router.put("/{name}")
async def update_provider_config(name: str, body: ProviderConfigUpdate) -> dict:
    """Update one or more fields of an existing provider config."""
    with _conn() as con:
        row = con.execute("SELECT * FROM provider_configs WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")

        current = dict(row)
        updated_base_url = body.base_url if body.base_url is not None else current["base_url"]
        updated_api_key = body.api_key if body.api_key is not None else current["api_key"]
        updated_model = (
            body.default_model if body.default_model is not None else current["default_model"]
        )
        updated_enabled = int(body.enabled) if body.enabled is not None else current["enabled"]
        now = datetime.now(timezone.utc).isoformat()

        con.execute(
            """
            UPDATE provider_configs
            SET base_url = ?, api_key = ?, default_model = ?, enabled = ?, updated_at = ?
            WHERE name = ?
            """,
            (updated_base_url, updated_api_key, updated_model, updated_enabled, now, name),
        )

    # Re-instantiate in live registry
    registry = get_registry()
    if updated_enabled:
        try:
            provider = _instantiate_provider(
                current["provider_type"],
                updated_base_url,
                updated_api_key,
                updated_model,
            )
            registry.register(name, provider)
            logger.info("Provider '%s' updated and re-registered.", name)
        except Exception as exc:
            logger.warning("Provider '%s' updated in DB but re-instantiation failed: %s", name, exc)
    else:
        registry.unregister(name)
        logger.info("Provider '%s' disabled and removed from live registry.", name)

    return {
        "name": name,
        "provider_type": current["provider_type"],
        "base_url": updated_base_url,
        "api_key": _mask_key(updated_api_key),
        "default_model": updated_model,
        "enabled": bool(updated_enabled),
        "updated_at": now,
    }


@router.delete("/{name}", status_code=204)
async def delete_provider_config(name: str) -> None:
    """Remove a provider from the config store and live registry."""
    with _conn() as con:
        row = con.execute("SELECT name FROM provider_configs WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")
        con.execute("DELETE FROM provider_configs WHERE name = ?", (name,))

    get_registry().unregister(name)
    logger.info("Provider '%s' deleted.", name)


@router.post("/{name}/test")
async def test_provider_connection(name: str) -> dict:
    """Run a health check against the named provider.

    The provider must be registered in the live registry (i.e. enabled).
    """
    registry = get_registry()

    # Verify the config exists
    with _conn() as con:
        row = con.execute("SELECT * FROM provider_configs WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")

    # Attempt to get from live registry; if not there, try instantiating now
    try:
        provider = registry.get(name)
    except Exception:
        cfg = dict(row)
        if not cfg["enabled"]:
            return {
                "name": name,
                "healthy": False,
                "latency_ms": 0.0,
                "error": "Provider is disabled.",
            }
        try:
            provider = _instantiate_provider(
                cfg["provider_type"],
                cfg["base_url"],
                cfg["api_key"],
                cfg["default_model"],
            )
        except Exception as exc:
            return {
                "name": name,
                "healthy": False,
                "latency_ms": 0.0,
                "error": f"Failed to instantiate provider: {exc}",
            }

    try:
        result = await provider.health_check()
    except Exception as exc:
        return {
            "name": name,
            "healthy": False,
            "latency_ms": 0.0,
            "error": str(exc),
        }

    if isinstance(result, ProviderHealth):
        return {
            "name": name,
            "healthy": result.healthy,
            "latency_ms": result.latency_ms,
            "error": result.error,
        }
    return {
        "name": name,
        "healthy": bool(result),
        "latency_ms": 0.0,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Startup helper — restore persisted providers into live registry
# ---------------------------------------------------------------------------


def restore_persisted_providers() -> None:
    """Re-instantiate all enabled providers from SQLite into the live registry.

    Call this once during controller startup (after the registry is initialised).
    """
    try:
        with _conn() as con:
            rows = con.execute("SELECT * FROM provider_configs WHERE enabled = 1").fetchall()
    except Exception as exc:
        logger.warning("Could not load persisted provider configs: %s", exc)
        return

    registry = get_registry()
    for row in rows:
        cfg = dict(row)
        name = cfg["name"]
        # Skip if already registered (e.g. Ollama auto-registered at startup)
        if name in registry.list():
            continue
        try:
            provider = _instantiate_provider(
                cfg["provider_type"],
                cfg["base_url"],
                cfg["api_key"],
                cfg["default_model"],
            )
            registry.register(name, provider)
            logger.info("Restored provider '%s' (%s) from config DB.", name, cfg["provider_type"])
        except Exception as exc:
            logger.warning("Could not restore provider '%s': %s", name, exc)
