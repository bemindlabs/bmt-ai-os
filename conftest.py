"""Root conftest — make ``import bmt_ai_os`` resolve to the ``bmt_ai_os/`` directory."""

import os
import pathlib
import sys

_root = pathlib.Path(__file__).parent

if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Ensure a JWT secret is available for all tests that import auth middleware.
os.environ.setdefault("BMT_JWT_SECRET", "test-jwt-secret-for-ci-32-chars-ok!")
