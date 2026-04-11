"""Unit tests for the BMT AI OS plugin system."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo
from bmt_ai_os.plugins.loader import Plugin, discover_plugins, load_plugin
from bmt_ai_os.plugins.manager import PluginManager

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_plugin_cls(
    name: str = "test-plugin",
    version: str = "1.0.0",
    hook_type: PluginHook = PluginHook.PROVIDER,
    module: str = "test_module",
) -> type:
    """Return a concrete class that satisfies the Plugin protocol."""

    class _TestPlugin:
        def initialize(self) -> None:
            pass

    _TestPlugin.name = name  # type: ignore[attr-defined]
    _TestPlugin.version = version  # type: ignore[attr-defined]
    _TestPlugin.hook_type = hook_type  # type: ignore[attr-defined]
    _TestPlugin.__module__ = module

    return _TestPlugin


def _make_ep(name: str, plugin_cls: type) -> MagicMock:
    """Return a mock entry point that loads *plugin_cls*."""
    ep = MagicMock()
    ep.name = name
    ep.value = f"{plugin_cls.__module__}:{plugin_cls.__name__}"
    ep.load.return_value = plugin_cls
    return ep


# ---------------------------------------------------------------------------
# PluginHook
# ---------------------------------------------------------------------------


class TestPluginHook:
    def test_values_are_strings(self):
        assert PluginHook.PROVIDER.value == "provider"
        assert PluginHook.RAG_PROCESSOR.value == "rag_processor"
        assert PluginHook.CLI_COMMAND.value == "cli_command"

    def test_str_enum(self):
        # PluginHook inherits from str so it works in comparisons
        assert PluginHook.PROVIDER == "provider"


# ---------------------------------------------------------------------------
# PluginInfo
# ---------------------------------------------------------------------------


class TestPluginInfo:
    def _make(self, **kw) -> PluginInfo:
        defaults = dict(
            name="p",
            version="0.1.0",
            hook_type=PluginHook.PROVIDER,
            module="pkg.mod",
            enabled=True,
        )
        defaults.update(kw)
        return PluginInfo(**defaults)

    def test_to_dict_round_trip(self):
        info = self._make(hook_type=PluginHook.RAG_PROCESSOR, enabled=False)
        d = info.to_dict()
        assert d["hook_type"] == "rag_processor"
        assert d["enabled"] is False
        restored = PluginInfo.from_dict(d)
        assert restored.hook_type == PluginHook.RAG_PROCESSOR
        assert restored.enabled is False

    def test_from_dict_defaults_enabled(self):
        d = {"name": "x", "version": "1.0", "hook_type": "cli_command", "module": "m"}
        info = PluginInfo.from_dict(d)
        assert info.enabled is True

    def test_invalid_hook_type_raises(self):
        with pytest.raises(ValueError):
            PluginInfo.from_dict(
                {"name": "x", "version": "1.0", "hook_type": "bad_hook", "module": "m"}
            )


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_empty_when_no_entry_points(self):
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[]):
            result = discover_plugins()
        assert result == []

    def test_returns_plugin_info_per_entry_point(self):
        cls = _make_plugin_cls("my-plugin", "2.0.0", PluginHook.RAG_PROCESSOR)
        ep = _make_ep("my-plugin", cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins()

        assert len(result) == 1
        info = result[0]
        assert info.name == "my-plugin"
        assert info.version == "2.0.0"
        assert info.hook_type == PluginHook.RAG_PROCESSOR
        assert info.enabled is True

    def test_skips_entry_point_that_fails_to_load(self):
        bad_ep = MagicMock()
        bad_ep.name = "broken"
        bad_ep.load.side_effect = ImportError("missing dep")

        good_cls = _make_plugin_cls("good-plugin")
        good_ep = _make_ep("good-plugin", good_cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[bad_ep, good_ep]):
            result = discover_plugins()

        assert len(result) == 1
        assert result[0].name == "good-plugin"

    def test_unknown_hook_type_falls_back_to_provider(self):
        cls = _make_plugin_cls()
        cls.hook_type = "unknown_hook"  # type: ignore[attr-defined]
        ep = _make_ep("plug", cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins()

        assert result[0].hook_type == PluginHook.PROVIDER

    def test_uses_ep_name_when_class_has_no_name(self):
        cls = _make_plugin_cls()
        del cls.name  # type: ignore[attr-defined]
        ep = _make_ep("fallback-name", cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins()

        assert result[0].name == "fallback-name"


# ---------------------------------------------------------------------------
# load_plugin
# ---------------------------------------------------------------------------


class TestLoadPlugin:
    def test_load_and_initialize(self):
        calls: list[str] = []

        class _P:
            name = "my-ep"
            version = "1.0.0"
            hook_type = PluginHook.CLI_COMMAND

            def initialize(self) -> None:
                calls.append("init")

        ep = _make_ep("my-ep", _P)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            plugin = load_plugin("my-ep")

        assert isinstance(plugin, Plugin)
        assert calls == ["init"]

    def test_raises_key_error_for_unknown_name(self):
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[]):
            with pytest.raises(KeyError, match="no-such"):
                load_plugin("no-such")

    def test_raises_type_error_when_protocol_not_satisfied(self):
        class _Bad:
            """Missing required Protocol attributes."""

            pass

        ep = _make_ep("bad-ep", _Bad)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            with pytest.raises(TypeError, match="Plugin protocol"):
                load_plugin("bad-ep")


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class TestPluginManager:
    @pytest.fixture
    def state_file(self, tmp_path: Path) -> str:
        return str(tmp_path / "plugins.json")

    @pytest.fixture
    def mock_discover(self):
        """Patch discover_plugins at the manager level."""
        infos = [
            PluginInfo("alpha", "1.0.0", PluginHook.PROVIDER, "pkg.alpha"),
            PluginInfo("beta", "0.5.0", PluginHook.RAG_PROCESSOR, "pkg.beta"),
        ]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            yield infos

    # -- list ----------------------------------------------------------------

    def test_list_returns_discovered_plugins(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        plugins = mgr.list_plugins()
        assert len(plugins) == 2
        names = {p.name for p in plugins}
        assert names == {"alpha", "beta"}

    def test_list_reflects_persisted_disabled_state(self, state_file, mock_discover):
        Path(state_file).write_text(json.dumps({"alpha": False}))
        mgr = PluginManager(state_file=state_file)
        plugins = {p.name: p for p in mgr.list_plugins()}
        assert plugins["alpha"].enabled is False
        assert plugins["beta"].enabled is True

    # -- enable / disable ----------------------------------------------------

    def test_enable_sets_state_and_persists(self, state_file, mock_discover):
        Path(state_file).write_text(json.dumps({"alpha": False}))
        mgr = PluginManager(state_file=state_file)
        mgr.enable("alpha")

        assert mgr.is_enabled("alpha") is True
        saved = json.loads(Path(state_file).read_text())
        assert saved["alpha"] is True

    def test_disable_sets_state_and_persists(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        mgr.disable("beta")

        assert mgr.is_enabled("beta") is False
        saved = json.loads(Path(state_file).read_text())
        assert saved["beta"] is False

    def test_enable_unknown_plugin_raises_key_error(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError, match="gamma"):
            mgr.enable("gamma")

    def test_disable_unknown_plugin_raises_key_error(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError, match="gamma"):
            mgr.disable("gamma")

    # -- state file edge cases -----------------------------------------------

    def test_missing_state_file_is_handled_gracefully(self, state_file):
        infos = [PluginInfo("x", "1.0", PluginHook.PROVIDER, "m")]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            mgr = PluginManager(state_file=state_file)
            assert mgr.is_enabled("x") is True

    def test_corrupted_state_file_is_handled_gracefully(self, state_file):
        Path(state_file).write_text("not valid json {{{{")
        infos = [PluginInfo("x", "1.0", PluginHook.PROVIDER, "m")]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            mgr = PluginManager(state_file=state_file)
            assert mgr.is_enabled("x") is True

    # -- register_provider_plugin --------------------------------------------

    def test_register_provider_plugin_calls_registry(self, state_file):
        registry_mock = MagicMock()

        class _ProvPlugin:
            name = "my-provider"
            version = "1.0.0"
            hook_type = PluginHook.PROVIDER

            def initialize(self):
                pass

        plugin_instance = _ProvPlugin()

        with patch("bmt_ai_os.plugins.manager.get_registry", return_value=registry_mock):
            mgr = PluginManager(state_file=state_file)
            mgr.register_provider_plugin(plugin_instance)  # type: ignore[arg-type]

        registry_mock.register.assert_called_once_with("my-provider", plugin_instance)

    def test_register_provider_plugin_ignores_non_provider_hooks(self, state_file):
        registry_mock = MagicMock()

        class _RagPlugin:
            name = "my-rag"
            version = "1.0.0"
            hook_type = PluginHook.RAG_PROCESSOR

            def initialize(self):
                pass

        plugin_instance = _RagPlugin()

        with patch("bmt_ai_os.plugins.manager.get_registry", return_value=registry_mock):
            mgr = PluginManager(state_file=state_file)
            mgr.register_provider_plugin(plugin_instance)  # type: ignore[arg-type]

        registry_mock.register.assert_not_called()

    def test_provider_plugin_with_provider_attr_registers_provider(self, state_file):
        """If plugin exposes .provider, register that instead of the plugin itself."""
        registry_mock = MagicMock()
        inner_provider = MagicMock()

        class _WrappedPlugin:
            name = "wrapped"
            version = "1.0.0"
            hook_type = PluginHook.PROVIDER
            provider = inner_provider

            def initialize(self):
                pass

        plugin_instance = _WrappedPlugin()

        with patch("bmt_ai_os.plugins.manager.get_registry", return_value=registry_mock):
            mgr = PluginManager(state_file=state_file)
            mgr.register_provider_plugin(plugin_instance)  # type: ignore[arg-type]

        registry_mock.register.assert_called_once_with("wrapped", inner_provider)


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestPluginCLI:
    """Smoke-tests for the `bmt-ai-os plugin` Click commands."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def cli(self):
        from bmt_ai_os.cli import main

        return main

    def test_plugin_list_empty(self, runner, cli, tmp_path):
        sf = str(tmp_path / "p.json")
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=[]):
            result = runner.invoke(cli, ["plugin", "list", "--state-file", sf])
        assert result.exit_code == 0
        assert "No plugins discovered" in result.output

    def test_plugin_list_shows_plugins(self, runner, cli, tmp_path):
        sf = str(tmp_path / "p.json")
        infos = [PluginInfo("demo", "1.0.0", PluginHook.PROVIDER, "demo_mod")]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            result = runner.invoke(cli, ["plugin", "list", "--state-file", sf])
        assert result.exit_code == 0
        assert "demo" in result.output
        assert "provider" in result.output

    def test_plugin_enable_success(self, runner, cli, tmp_path):
        sf = str(tmp_path / "p.json")
        infos = [PluginInfo("demo", "1.0.0", PluginHook.PROVIDER, "demo_mod")]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            result = runner.invoke(cli, ["plugin", "enable", "demo", "--state-file", sf])
        assert result.exit_code == 0
        assert "enabled" in result.output

    def test_plugin_disable_success(self, runner, cli, tmp_path):
        sf = str(tmp_path / "p.json")
        infos = [PluginInfo("demo", "1.0.0", PluginHook.PROVIDER, "demo_mod")]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            result = runner.invoke(cli, ["plugin", "disable", "demo", "--state-file", sf])
        assert result.exit_code == 0
        assert "disabled" in result.output

    def test_plugin_enable_unknown_exits_nonzero(self, runner, cli, tmp_path):
        sf = str(tmp_path / "p.json")
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=[]):
            result = runner.invoke(cli, ["plugin", "enable", "no-such-plugin", "--state-file", sf])
        assert result.exit_code != 0

    def test_plugin_disable_unknown_exits_nonzero(self, runner, cli, tmp_path):
        sf = str(tmp_path / "p.json")
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=[]):
            result = runner.invoke(cli, ["plugin", "disable", "no-such-plugin", "--state-file", sf])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Atomicity and thread safety (BMTOS-67)
# ---------------------------------------------------------------------------


class TestPluginManagerAtomicity:
    """Verify that enable/disable are atomic and roll back on save failure."""

    @pytest.fixture
    def state_file(self, tmp_path: Path) -> str:
        return str(tmp_path / "plugins.json")

    @pytest.fixture
    def mock_discover_alpha(self):
        infos = [PluginInfo("alpha", "1.0.0", PluginHook.PROVIDER, "pkg.alpha")]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            yield

    def test_enable_rolls_back_on_save_failure(self, state_file, mock_discover_alpha):
        """If _save_state raises, in-memory state must revert to pre-call value."""
        Path(state_file).write_text(json.dumps({"alpha": False}))
        mgr = PluginManager(state_file=state_file)

        with patch.object(mgr, "_save_state", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                mgr.enable("alpha")

        # State must still be False (rolled back)
        assert mgr._state["alpha"] is False

    def test_disable_rolls_back_on_save_failure(self, state_file, mock_discover_alpha):
        """If _save_state raises during disable, state reverts to True."""
        mgr = PluginManager(state_file=state_file)
        mgr._state["alpha"] = True

        with patch.object(mgr, "_save_state", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                mgr.disable("alpha")

        assert mgr._state["alpha"] is True

    def test_enable_rolls_back_when_previously_absent(self, state_file, mock_discover_alpha):
        """When a plugin has no prior state entry, rollback removes the key."""
        mgr = PluginManager(state_file=state_file)
        # Ensure 'alpha' is NOT in _state initially
        mgr._state.pop("alpha", None)

        with patch.object(mgr, "_save_state", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                mgr.enable("alpha")

        assert "alpha" not in mgr._state

    def test_lock_exists_on_manager(self, state_file):
        """PluginManager must expose a threading.Lock."""
        mgr = PluginManager(state_file=state_file)
        assert isinstance(mgr._lock, type(threading.Lock()))

    def test_concurrent_enable_disable_does_not_corrupt_state(self, state_file, tmp_path):
        """Concurrent callers must not leave _state in a partially-written state."""
        infos = [PluginInfo(f"p{i}", "1.0.0", PluginHook.PROVIDER, f"m{i}") for i in range(5)]
        errors: list[Exception] = []

        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            mgr = PluginManager(state_file=state_file)

            def _toggle(name: str, value: bool) -> None:
                try:
                    if value:
                        mgr.enable(name)
                    else:
                        mgr.disable(name)
                except Exception as exc:
                    errors.append(exc)

            threads = []
            for i in range(5):
                for val in (True, False, True):
                    threads.append(threading.Thread(target=_toggle, args=(f"p{i}", val)))

            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # No unhandled exceptions
        assert not errors
        # All values must be boolean
        for v in mgr._state.values():
            assert isinstance(v, bool)

    def test_save_is_atomic_via_temp_file(self, state_file, mock_discover_alpha):
        """_save_state must write via a temp file then rename (no partial writes)."""
        mgr = PluginManager(state_file=state_file)

        temp_files_created: list[str] = []
        real_mkstemp = __import__("tempfile").mkstemp

        def _spy_mkstemp(**kwargs):
            fd, path = real_mkstemp(**kwargs)
            temp_files_created.append(path)
            return fd, path

        with patch("bmt_ai_os.plugins.manager.tempfile.mkstemp", side_effect=_spy_mkstemp):
            mgr.enable("alpha")

        # A temp file was created and then replaced (no longer exists)
        assert len(temp_files_created) == 1
        assert not Path(temp_files_created[0]).exists()
        # The final state file exists and is valid JSON
        data = json.loads(Path(state_file).read_text())
        assert data["alpha"] is True
