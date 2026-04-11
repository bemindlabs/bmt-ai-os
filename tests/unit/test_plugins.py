"""Unit tests for the BMT AI OS plugin system."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo, PluginManifest
from bmt_ai_os.plugins.loader import (
    Plugin,
    _load_from_manifest,
    discover_manifests,
    discover_plugins,
    load_manifest,
    load_plugin,
)
from bmt_ai_os.plugins.manager import PluginManager, _sandboxed_call

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


def _make_manifest(
    name: str = "test-manifest-plugin",
    version: str = "1.0.0",
    hook_type: str = "provider",
    module: str = "test_module",
    entry_class: str = "Plugin",
    **extra,
) -> dict:
    return {
        "name": name,
        "version": version,
        "description": "A test plugin",
        "hook_type": hook_type,
        "module": module,
        "entry_class": entry_class,
        **extra,
    }


# ---------------------------------------------------------------------------
# PluginHook
# ---------------------------------------------------------------------------


class TestPluginHook:
    def test_values_are_strings(self):
        assert PluginHook.PROVIDER.value == "provider"
        assert PluginHook.RAG_PROCESSOR.value == "rag_processor"
        assert PluginHook.CLI_COMMAND.value == "cli_command"
        assert PluginHook.PRE_REQUEST.value == "pre_request"
        assert PluginHook.POST_REQUEST.value == "post_request"
        assert PluginHook.MIDDLEWARE.value == "middleware"
        assert PluginHook.TOOL.value == "tool"

    def test_str_enum(self):
        assert PluginHook.PROVIDER == "provider"
        assert PluginHook.MIDDLEWARE == "middleware"


# ---------------------------------------------------------------------------
# PluginManifest
# ---------------------------------------------------------------------------


class TestPluginManifest:
    def test_from_dict_minimal(self):
        data = _make_manifest()
        m = PluginManifest.from_dict(data)
        assert m.name == "test-manifest-plugin"
        assert m.hook_type == PluginHook.PROVIDER
        assert m.dependencies == []
        assert m.config == {}

    def test_from_dict_full(self):
        data = _make_manifest(
            author="Jane Dev",
            dependencies=["requests>=2.28"],
            hooks=["pre_request"],
            config={"timeout": 30},
        )
        m = PluginManifest.from_dict(data)
        assert m.author == "Jane Dev"
        assert m.dependencies == ["requests>=2.28"]
        assert m.hooks == ["pre_request"]
        assert m.config["timeout"] == 30

    def test_to_dict_round_trip(self):
        data = _make_manifest(author="Dev", dependencies=["pyyaml"])
        m = PluginManifest.from_dict(data)
        out = m.to_dict()
        assert out["name"] == "test-manifest-plugin"
        assert out["hook_type"] == "provider"
        assert out["dependencies"] == ["pyyaml"]

    def test_invalid_hook_type_raises(self):
        data = _make_manifest(hook_type="nonexistent_hook")
        with pytest.raises(ValueError):
            PluginManifest.from_dict(data)


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

    def test_from_manifest(self):
        data = _make_manifest(name="mani-plugin", version="2.0.0", hook_type="tool")
        manifest = PluginManifest.from_dict(data)
        info = PluginInfo.from_manifest(manifest, enabled=False)
        assert info.name == "mani-plugin"
        assert info.version == "2.0.0"
        assert info.hook_type == PluginHook.TOOL
        assert info.enabled is False
        assert info.manifest is manifest

    def test_to_dict_includes_description_and_author(self):
        info = self._make(description="A test plugin", author="Dev")
        d = info.to_dict()
        assert d["description"] == "A test plugin"
        assert d["author"] == "Dev"


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_valid_manifest_file(self, tmp_path: Path):
        yml = tmp_path / "plugin.yml"
        yml.write_text(
            "name: my-plugin\nversion: 1.0.0\ndescription: test\n"
            "hook_type: provider\nmodule: pkg\nentry_class: P\n"
        )
        result = load_manifest(yml)
        assert result is not None
        assert result.name == "my-plugin"

    def test_missing_file_returns_none(self, tmp_path: Path):
        result = load_manifest(tmp_path / "nonexistent.yml")
        assert result is None

    def test_invalid_yaml_returns_none(self, tmp_path: Path):
        yml = tmp_path / "bad.yml"
        yml.write_text(": not: valid: yaml: {{{{")
        result = load_manifest(yml)
        assert result is None

    def test_non_dict_yaml_returns_none(self, tmp_path: Path):
        yml = tmp_path / "list.yml"
        yml.write_text("- item1\n- item2\n")
        result = load_manifest(yml)
        assert result is None


# ---------------------------------------------------------------------------
# discover_manifests
# ---------------------------------------------------------------------------


class TestDiscoverManifests:
    def test_empty_dir(self, tmp_path: Path):
        result = discover_manifests(tmp_path)
        assert result == []

    def test_nonexistent_dir(self, tmp_path: Path):
        result = discover_manifests(tmp_path / "does_not_exist")
        assert result == []

    def test_top_level_yml(self, tmp_path: Path):
        yml = tmp_path / "alpha.yml"
        yml.write_text(
            "name: alpha\nversion: 1.0.0\ndescription: A\n"
            "hook_type: provider\nmodule: alpha_mod\nentry_class: Alpha\n"
        )
        result = discover_manifests(tmp_path)
        assert len(result) == 1
        assert result[0].name == "alpha"

    def test_subdirectory_plugin_yml(self, tmp_path: Path):
        sub = tmp_path / "beta-plugin"
        sub.mkdir()
        (sub / "plugin.yml").write_text(
            "name: beta\nversion: 2.0.0\ndescription: B\n"
            "hook_type: tool\nmodule: beta_mod\nentry_class: Beta\n"
        )
        result = discover_manifests(tmp_path)
        assert len(result) == 1
        assert result[0].name == "beta"

    def test_deduplicates_same_name(self, tmp_path: Path):
        """A top-level yml and a subdirectory with the same plugin name — only one entry."""
        (tmp_path / "dup.yml").write_text(
            "name: dup\nversion: 1.0.0\ndescription: D\n"
            "hook_type: provider\nmodule: m\nentry_class: C\n"
        )
        sub = tmp_path / "dup-dir"
        sub.mkdir()
        (sub / "plugin.yml").write_text(
            "name: dup\nversion: 2.0.0\ndescription: D2\n"
            "hook_type: provider\nmodule: m\nentry_class: C\n"
        )
        result = discover_manifests(tmp_path)
        assert len(result) == 1

    def test_skips_malformed_yml(self, tmp_path: Path):
        (tmp_path / "bad.yml").write_text("not valid: {{{{")
        (tmp_path / "good.yml").write_text(
            "name: good\nversion: 1.0.0\ndescription: G\n"
            "hook_type: provider\nmodule: g\nentry_class: G\n"
        )
        result = discover_manifests(tmp_path)
        assert len(result) == 1
        assert result[0].name == "good"


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_empty_when_no_entry_points_and_no_dir(self, tmp_path: Path):
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[]):
            result = discover_plugins(plugin_dir=tmp_path / "no_dir")
        assert result == []

    def test_returns_plugin_info_per_entry_point(self):
        cls = _make_plugin_cls("my-plugin", "2.0.0", PluginHook.RAG_PROCESSOR)
        ep = _make_ep("my-plugin", cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins(plugin_dir="/nonexistent")

        assert len(result) == 1
        info = result[0]
        assert info.name == "my-plugin"
        assert info.version == "2.0.0"
        assert info.hook_type == PluginHook.RAG_PROCESSOR
        assert info.enabled is True

    def test_skips_entry_point_that_fails_to_load(self, tmp_path: Path):
        bad_ep = MagicMock()
        bad_ep.name = "broken"
        bad_ep.load.side_effect = ImportError("missing dep")

        good_cls = _make_plugin_cls("good-plugin")
        good_ep = _make_ep("good-plugin", good_cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[bad_ep, good_ep]):
            result = discover_plugins(plugin_dir=tmp_path)

        assert len(result) == 1
        assert result[0].name == "good-plugin"

    def test_unknown_hook_type_falls_back_to_provider(self, tmp_path: Path):
        cls = _make_plugin_cls()
        cls.hook_type = "unknown_hook"  # type: ignore[attr-defined]
        ep = _make_ep("plug", cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins(plugin_dir=tmp_path)

        assert result[0].hook_type == PluginHook.PROVIDER

    def test_uses_ep_name_when_class_has_no_name(self, tmp_path: Path):
        cls = _make_plugin_cls()
        del cls.name  # type: ignore[attr-defined]
        ep = _make_ep("fallback-name", cls)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins(plugin_dir=tmp_path)

        assert result[0].name == "fallback-name"

    def test_discovers_manifest_plugins(self, tmp_path: Path):
        (tmp_path / "mani.yml").write_text(
            "name: mani\nversion: 1.0.0\ndescription: M\n"
            "hook_type: tool\nmodule: mani_mod\nentry_class: M\n"
        )
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[]):
            result = discover_plugins(plugin_dir=tmp_path)
        assert len(result) == 1
        assert result[0].name == "mani"
        assert result[0].hook_type == PluginHook.TOOL

    def test_deduplicates_ep_and_manifest_same_name(self, tmp_path: Path):
        cls = _make_plugin_cls("shared-name")
        ep = _make_ep("shared-name", cls)
        (tmp_path / "shared-name.yml").write_text(
            "name: shared-name\nversion: 9.9.9\ndescription: dupe\n"
            "hook_type: provider\nmodule: m\nentry_class: C\n"
        )
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            result = discover_plugins(plugin_dir=tmp_path)
        assert len(result) == 1
        # Entry-point wins over manifest
        assert result[0].version == "1.0.0"


# ---------------------------------------------------------------------------
# load_plugin
# ---------------------------------------------------------------------------


class TestLoadPlugin:
    def test_load_and_initialize(self, tmp_path: Path):
        calls: list[str] = []

        class _P:
            name = "my-ep"
            version = "1.0.0"
            hook_type = PluginHook.CLI_COMMAND

            def initialize(self) -> None:
                calls.append("init")

        ep = _make_ep("my-ep", _P)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            plugin = load_plugin("my-ep", plugin_dir=tmp_path)

        assert isinstance(plugin, Plugin)
        assert calls == ["init"]

    def test_raises_key_error_for_unknown_name(self, tmp_path: Path):
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[]):
            with pytest.raises(KeyError, match="no-such"):
                load_plugin("no-such", plugin_dir=tmp_path)

    def test_raises_type_error_when_protocol_not_satisfied(self, tmp_path: Path):
        class _Bad:
            """Missing required Protocol attributes."""

            pass

        ep = _make_ep("bad-ep", _Bad)

        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[ep]):
            with pytest.raises(TypeError, match="Plugin protocol"):
                load_plugin("bad-ep", plugin_dir=tmp_path)

    def test_load_from_manifest_dir(self, tmp_path: Path):
        """Manifest-based loading when no entry-point exists."""
        # Write manifest
        (tmp_path / "demo.yml").write_text(
            "name: demo-manifest\nversion: 1.0.0\ndescription: D\n"
            "hook_type: tool\nmodule: bmt_ai_os.plugins.hooks\nentry_class: PluginHook\n"
        )
        # PluginHook is not a Plugin — expect TypeError but confirms manifest
        # path is attempted (we just verify KeyError is NOT raised)
        with patch("bmt_ai_os.plugins.loader.entry_points", return_value=[]):
            with pytest.raises((TypeError, AttributeError)):
                load_plugin("demo-manifest", plugin_dir=tmp_path)


# ---------------------------------------------------------------------------
# _load_from_manifest
# ---------------------------------------------------------------------------


class TestLoadFromManifest:
    def test_import_error_on_bad_module(self):
        m = PluginManifest.from_dict(
            _make_manifest(module="nonexistent.module.xyz", entry_class="Cls")
        )
        with pytest.raises(ImportError, match="nonexistent.module.xyz"):
            _load_from_manifest(m)

    def test_attribute_error_on_missing_class(self):
        m = PluginManifest.from_dict(
            _make_manifest(module="bmt_ai_os.plugins.hooks", entry_class="NonExistentClass")
        )
        with pytest.raises(AttributeError, match="NonExistentClass"):
            _load_from_manifest(m)


# ---------------------------------------------------------------------------
# _sandboxed_call
# ---------------------------------------------------------------------------


class TestSandboxedCall:
    def test_returns_result_on_success(self):
        def _fn(x):
            return x * 2

        result = _sandboxed_call(_fn, 21)
        assert result == 42

    def test_returns_none_on_exception(self):
        def _bad():
            raise RuntimeError("plugin crash")

        result = _sandboxed_call(_bad)
        assert result is None

    def test_returns_none_on_timeout(self):
        import time

        def _slow():
            time.sleep(10)
            return "done"

        result = _sandboxed_call(_slow, timeout=0.05)
        assert result is None

    def test_passes_kwargs(self):
        def _fn(a, b=0):
            return a + b

        result = _sandboxed_call(_fn, 3, b=7)
        assert result == 10


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class TestPluginManager:
    @pytest.fixture
    def state_file(self, tmp_path: Path) -> str:
        return str(tmp_path / "plugins.json")

    @pytest.fixture
    def plugin_dir(self, tmp_path: Path) -> str:
        d = tmp_path / "plugins"
        d.mkdir()
        return str(d)

    @pytest.fixture
    def mock_discover(self, plugin_dir):
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
        Path(state_file).write_text(json.dumps({"alpha": {"enabled": False, "installed": True}}))
        mgr = PluginManager(state_file=state_file)
        plugins = {p.name: p for p in mgr.list_plugins()}
        assert plugins["alpha"].enabled is False
        assert plugins["beta"].enabled is True

    def test_list_reflects_legacy_bool_state(self, state_file, mock_discover):
        """Legacy state files stored plain booleans; must still load correctly."""
        Path(state_file).write_text(json.dumps({"alpha": False}))
        mgr = PluginManager(state_file=state_file)
        plugins = {p.name: p for p in mgr.list_plugins()}
        assert plugins["alpha"].enabled is False

    # -- enable / disable ----------------------------------------------------

    def test_enable_sets_state_and_persists(self, state_file, mock_discover):
        Path(state_file).write_text(json.dumps({"alpha": {"enabled": False, "installed": True}}))
        mgr = PluginManager(state_file=state_file)
        mgr.enable("alpha")

        assert mgr.is_enabled("alpha") is True
        saved = json.loads(Path(state_file).read_text())
        assert saved["alpha"]["enabled"] is True

    def test_disable_sets_state_and_persists(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        mgr.disable("beta")

        assert mgr.is_enabled("beta") is False
        saved = json.loads(Path(state_file).read_text())
        assert saved["beta"]["enabled"] is False

    def test_enable_unknown_plugin_raises_key_error(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError, match="gamma"):
            mgr.enable("gamma")

    def test_disable_unknown_plugin_raises_key_error(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError, match="gamma"):
            mgr.disable("gamma")

    # -- install / uninstall -------------------------------------------------

    def test_install_marks_plugin_installed(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        assert mgr.is_installed("alpha") is False
        mgr.install("alpha")
        assert mgr.is_installed("alpha") is True
        assert mgr.is_enabled("alpha") is True

    def test_install_unknown_raises_key_error(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError):
            mgr.install("nonexistent-plugin")

    def test_uninstall_removes_plugin_from_state(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        mgr.install("alpha")
        assert mgr.is_installed("alpha") is True
        mgr.uninstall("alpha")
        assert mgr.is_installed("alpha") is False

    def test_uninstall_not_installed_raises_key_error(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError, match="alpha"):
            mgr.uninstall("alpha")

    def test_install_persists_to_disk(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        mgr.install("beta")
        saved = json.loads(Path(state_file).read_text())
        assert saved["beta"]["installed"] is True

    def test_uninstall_persists_to_disk(self, state_file, mock_discover):
        Path(state_file).write_text(json.dumps({"alpha": {"enabled": True, "installed": True}}))
        mgr = PluginManager(state_file=state_file)
        mgr.uninstall("alpha")
        saved = json.loads(Path(state_file).read_text())
        assert "alpha" not in saved

    # -- get_plugin_info -----------------------------------------------------

    def test_get_plugin_info_returns_info(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        info = mgr.get_plugin_info("alpha")
        assert info.name == "alpha"

    def test_get_plugin_info_unknown_raises(self, state_file, mock_discover):
        mgr = PluginManager(state_file=state_file)
        with pytest.raises(KeyError):
            mgr.get_plugin_info("nonexistent")

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

    # -- dispatch_hook -------------------------------------------------------

    def test_dispatch_hook_calls_enabled_plugins(self, state_file):
        handle_calls: list = []

        class _PrePlugin:
            name = "pre-hook-plugin"
            version = "1.0.0"
            hook_type = PluginHook.PRE_REQUEST

            def initialize(self):
                pass

            def handle(self, payload):
                handle_calls.append(payload)
                return "handled"

        infos = [PluginInfo("pre-hook-plugin", "1.0.0", PluginHook.PRE_REQUEST, "mod")]
        plugin_instance = _PrePlugin()

        with (
            patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos),
            patch("bmt_ai_os.plugins.manager.load_plugin", return_value=plugin_instance),
        ):
            mgr = PluginManager(state_file=state_file)
            results = mgr.dispatch_hook(PluginHook.PRE_REQUEST, payload={"path": "/test"})

        assert results == ["handled"]
        assert handle_calls == [{"path": "/test"}]

    def test_dispatch_hook_skips_disabled_plugins(self, state_file):
        infos = [PluginInfo("pre-disabled", "1.0.0", PluginHook.PRE_REQUEST, "mod", enabled=False)]

        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            mgr = PluginManager(state_file=state_file)
            results = mgr.dispatch_hook(PluginHook.PRE_REQUEST)

        assert results == []

    def test_dispatch_hook_skips_wrong_hook_type(self, state_file):
        infos = [PluginInfo("provider-plugin", "1.0.0", PluginHook.PROVIDER, "mod")]

        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            mgr = PluginManager(state_file=state_file)
            results = mgr.dispatch_hook(PluginHook.PRE_REQUEST)

        assert results == []

    def test_dispatch_hook_handles_plugin_load_failure(self, state_file):
        infos = [PluginInfo("broken", "1.0.0", PluginHook.POST_REQUEST, "mod")]

        with (
            patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos),
            patch(
                "bmt_ai_os.plugins.manager.load_plugin",
                side_effect=ImportError("missing"),
            ),
        ):
            mgr = PluginManager(state_file=state_file)
            # Must not raise — just returns empty results
            results = mgr.dispatch_hook(PluginHook.POST_REQUEST)

        assert results == []

    def test_dispatch_hook_omits_none_results(self, state_file):
        """Plugins returning None should not appear in results."""

        class _NonePlugin:
            name = "none-returner"
            version = "1.0.0"
            hook_type = PluginHook.POST_REQUEST

            def initialize(self):
                pass

            def handle(self, payload):
                return None

        infos = [PluginInfo("none-returner", "1.0.0", PluginHook.POST_REQUEST, "mod")]
        plugin_instance = _NonePlugin()

        with (
            patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos),
            patch("bmt_ai_os.plugins.manager.load_plugin", return_value=plugin_instance),
        ):
            mgr = PluginManager(state_file=state_file)
            results = mgr.dispatch_hook(PluginHook.POST_REQUEST)

        assert results == []


# ---------------------------------------------------------------------------
# Plugin API routes
# ---------------------------------------------------------------------------


class TestPluginRoutes:
    """Integration-style tests for the plugin management HTTP endpoints."""

    @pytest.fixture
    def client(self, tmp_path: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        env_patch = {
            "BMT_PLUGIN_STATE": str(tmp_path / "plugins.json"),
            "BMT_PLUGIN_DIR": str(tmp_path / "plugins"),
        }
        (tmp_path / "plugins").mkdir()

        with patch.dict("os.environ", env_patch):
            # Re-import to pick up env vars
            import importlib

            import bmt_ai_os.controller.plugin_routes as pr

            importlib.reload(pr)
            test_app = FastAPI()
            test_app.include_router(pr.router)
            yield TestClient(test_app)

    @pytest.fixture
    def mock_discover_two(self):
        infos = [
            PluginInfo("alpha", "1.0.0", PluginHook.PROVIDER, "pkg.alpha"),
            PluginInfo("beta", "0.5.0", PluginHook.RAG_PROCESSOR, "pkg.beta"),
        ]
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=infos):
            yield infos

    def test_list_plugins_empty(self, client, tmp_path):
        with patch("bmt_ai_os.plugins.manager.discover_plugins", return_value=[]):
            resp = client.get("/api/v1/plugins")
        assert resp.status_code == 200
        assert resp.json()["plugins"] == []

    def test_list_plugins_returns_discovered(self, client, mock_discover_two):
        resp = client.get("/api/v1/plugins")
        assert resp.status_code == 200
        names = {p["name"] for p in resp.json()["plugins"]}
        assert names == {"alpha", "beta"}

    def test_get_plugin_found(self, client, mock_discover_two):
        resp = client.get("/api/v1/plugins/alpha")
        assert resp.status_code == 200
        assert resp.json()["name"] == "alpha"

    def test_get_plugin_not_found(self, client, mock_discover_two):
        resp = client.get("/api/v1/plugins/nonexistent")
        assert resp.status_code == 404

    def test_install_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/alpha/install")
        assert resp.status_code == 200
        assert resp.json()["status"] == "installed"

    def test_install_nonexistent_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/nonexistent/install")
        assert resp.status_code == 404

    def test_uninstall_plugin(self, client, mock_discover_two, tmp_path):
        state_file = str(tmp_path / "plugins.json")
        Path(state_file).write_text(json.dumps({"alpha": {"enabled": True, "installed": True}}))
        resp = client.post("/api/v1/plugins/alpha/uninstall")
        assert resp.status_code == 200
        assert resp.json()["status"] == "uninstalled"

    def test_uninstall_not_installed_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/alpha/uninstall")
        assert resp.status_code == 404

    def test_enable_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/beta/enable")
        assert resp.status_code == 200
        assert resp.json()["status"] == "enabled"

    def test_disable_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/alpha/disable")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

    def test_enable_unknown_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/no-such/enable")
        assert resp.status_code == 404

    def test_disable_unknown_plugin(self, client, mock_discover_two):
        resp = client.post("/api/v1/plugins/no-such/disable")
        assert resp.status_code == 404


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
