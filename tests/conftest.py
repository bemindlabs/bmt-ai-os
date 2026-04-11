"""Shared test fixtures and path setup."""

import sys
from pathlib import Path

import pytest

# Make the rag package importable from tests.
_BMT_ROOT = str(Path(__file__).resolve().parent.parent / "bmt_ai_os")
if _BMT_ROOT not in sys.path:
    sys.path.insert(0, _BMT_ROOT)


@pytest.fixture(autouse=True)
def _reset_auth_singleton():
    """Save and restore the auth module-level default store after every test.

    Prevents test_auth.py from leaving a store-with-users in place that breaks
    tests expecting open/unauthenticated access (e.g. test_conversation_routes).
    """
    try:
        import bmt_ai_os.controller.auth as auth_mod

        orig = getattr(auth_mod, "_default_store", None)
    except ImportError:
        yield
        return

    yield

    try:
        auth_mod._default_store = orig
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_fleet_singleton():
    """Save and restore the fleet registry module-level singleton after every test."""
    try:
        import bmt_ai_os.fleet.registry as reg_mod

        orig = getattr(reg_mod, "_registry", None)
    except ImportError:
        yield
        return

    yield

    try:
        reg_mod._registry = orig
    except Exception:
        pass
