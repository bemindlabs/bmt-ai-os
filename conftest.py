"""Root conftest — make ``import bmt_ai_os`` resolve to the ``bmt_ai_os/`` directory."""

import pathlib
import sys

_root = pathlib.Path(__file__).parent

if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
