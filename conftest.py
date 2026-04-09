"""Root conftest — make ``import bmt_ai_os`` resolve to the ``bmt-ai-os/`` directory."""

import pathlib
import sys

_root = pathlib.Path(__file__).parent

# Create a symlink-like mapping: ``bmt_ai_os`` -> ``bmt-ai-os``
# by inserting the repo root into sys.path and creating a package alias.
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Register the hyphenated directory as the underscore package name so that
# ``from bmt_ai_os.providers import ...`` works without renaming the dir.
import importlib

_pkg_dir = _root / "bmt-ai-os"
if _pkg_dir.is_dir():
    spec = importlib.util.spec_from_file_location(
        "bmt_ai_os",
        _pkg_dir / "__init__.py",
        submodule_search_locations=[str(_pkg_dir)],
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bmt_ai_os"] = mod
        spec.loader.exec_module(mod)
