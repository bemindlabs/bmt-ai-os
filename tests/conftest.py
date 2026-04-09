"""Shared test fixtures and path setup."""

import sys
from pathlib import Path

# Make the rag package importable from tests.
_BMT_ROOT = str(Path(__file__).resolve().parent.parent / "bmt-ai-os")
if _BMT_ROOT not in sys.path:
    sys.path.insert(0, _BMT_ROOT)
