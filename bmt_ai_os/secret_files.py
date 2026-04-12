"""Secrets resolution utility for BMT AI OS.

Resolution order for every secret:
1. /run/secrets/{name}  — Docker / OS secrets file (preferred)
2. os.environ[name]     — environment variable fallback
3. default              — caller-supplied default value

A WARNING is logged whenever the env-var fallback is used, signalling
that the deployment should be migrated to proper secrets files.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SECRETS_DIR = Path("/run/secrets")


def read_secret(name: str, default: str | None = None) -> str | None:
    """Return the value of *name* using the secrets resolution order.

    Parameters
    ----------
    name:
        Secret name (e.g. ``"BMT_JWT_SECRET"``).  Used both as the
        filename under ``/run/secrets/`` and as the environment variable
        name.
    default:
        Value returned when neither the file nor the env var is present.

    Returns
    -------
    str | None
        The secret value, or *default* if not found anywhere.
    """
    # 1. Try /run/secrets/<name>
    secret_file = _SECRETS_DIR / name
    if secret_file.is_file():
        try:
            value = secret_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            logger.warning("Could not read secret file for '%s'", name)

    # 2. Env-var fallback — warn in production contexts
    env_value = os.environ.get(name)
    if env_value is not None:
        logger.warning(
            "Secret '%s' resolved from environment variable — "
            "mount as /run/secrets/ in production.",
            name,
        )
        return env_value

    # 3. Caller-supplied default
    return default
