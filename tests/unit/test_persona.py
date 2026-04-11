"""Unit tests for bmt_ai_os.persona — BMTOS-87 / BMTOS-90."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bmt_ai_os.persona.assembler import (
    _SECTION_SEPARATOR,
    _SOUL_FRAMING,
    assemble_system_prompt,
)
from bmt_ai_os.persona.config import AgentPersona, resolve_workspace
from bmt_ai_os.persona.loader import (
    _MAX_FILE_CHARS,
    _MAX_TOTAL_CHARS,
    ContextFile,
    load_context_file,
    load_workspace_files,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ===========================================================================
# loader.py
# ===========================================================================


class TestContextFile:
    def test_filename_property(self, tmp_path):
        cf = ContextFile(path=tmp_path / "SOUL.md", content="hello", priority=20)
        assert cf.filename == "SOUL.md"

    def test_lt_by_priority(self, tmp_path):
        low = ContextFile(path=tmp_path / "SOUL.md", content="", priority=20)
        high = ContextFile(path=tmp_path / "IDENTITY.md", content="", priority=30)
        assert low < high

    def test_sorting(self, tmp_path):
        files = [
            ContextFile(path=tmp_path / "IDENTITY.md", content="", priority=30),
            ContextFile(path=tmp_path / "SOUL.md", content="", priority=20),
        ]
        assert sorted(files)[0].filename == "SOUL.md"


class TestLoadContextFile:
    def test_returns_none_when_missing(self, tmp_path):
        result = load_context_file(tmp_path, "SOUL.md")
        assert result is None

    def test_reads_existing_file(self, tmp_path):
        _write(tmp_path / "SOUL.md", "I am a helpful assistant.")
        result = load_context_file(tmp_path, "SOUL.md")
        assert result == "I am a helpful assistant."

    def test_truncates_oversized_file(self, tmp_path):
        big_content = "x" * (_MAX_FILE_CHARS + 100)
        _write(tmp_path / "SOUL.md", big_content)
        result = load_context_file(tmp_path, "SOUL.md")
        assert result is not None
        assert len(result) == _MAX_FILE_CHARS

    def test_accepts_path_as_string(self, tmp_path):
        _write(tmp_path / "SOUL.md", "content")
        result = load_context_file(str(tmp_path), "SOUL.md")
        assert result == "content"

    def test_returns_none_on_directory(self, tmp_path):
        # Create a directory instead of a file — should return None.
        (tmp_path / "SOUL.md").mkdir()
        result = load_context_file(tmp_path, "SOUL.md")
        assert result is None

    def test_identity_file(self, tmp_path):
        _write(tmp_path / "IDENTITY.md", "Name: Aria")
        result = load_context_file(tmp_path, "IDENTITY.md")
        assert result == "Name: Aria"


class TestLoadWorkspaceFiles:
    def test_empty_workspace_returns_empty_list(self, tmp_path):
        result = load_workspace_files(tmp_path)
        assert result == []

    def test_loads_soul_only(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind.")
        result = load_workspace_files(tmp_path)
        assert len(result) == 1
        assert result[0].filename == "SOUL.md"
        assert result[0].priority == 20

    def test_loads_identity_only(self, tmp_path):
        _write(tmp_path / "IDENTITY.md", "Name: Aria")
        result = load_workspace_files(tmp_path)
        assert len(result) == 1
        assert result[0].filename == "IDENTITY.md"
        assert result[0].priority == 30

    def test_loads_both_files_in_priority_order(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind.")
        _write(tmp_path / "IDENTITY.md", "Name: Aria")
        result = load_workspace_files(tmp_path)
        assert len(result) == 2
        assert result[0].filename == "SOUL.md"
        assert result[1].filename == "IDENTITY.md"

    def test_ignores_unknown_files(self, tmp_path):
        _write(tmp_path / "README.md", "unrelated")
        result = load_workspace_files(tmp_path)
        assert result == []

    def test_total_budget_enforcement(self, tmp_path):
        # Fill SOUL.md to exactly _MAX_FILE_CHARS chars, then IDENTITY.md
        # would push total over _MAX_TOTAL_CHARS — it must be skipped.
        soul_content = "s" * _MAX_FILE_CHARS
        _write(tmp_path / "SOUL.md", soul_content)
        identity_content = "i" * (_MAX_TOTAL_CHARS - _MAX_FILE_CHARS + 1)
        _write(tmp_path / "IDENTITY.md", identity_content[:_MAX_FILE_CHARS])

        result = load_workspace_files(tmp_path)
        total = sum(len(cf.content) for cf in result)
        assert total <= _MAX_TOTAL_CHARS

    def test_accepts_string_path(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind.")
        result = load_workspace_files(str(tmp_path))
        assert len(result) == 1

    def test_content_is_stored_in_context_file(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be helpful.")
        result = load_workspace_files(tmp_path)
        assert result[0].content == "Be helpful."


# ===========================================================================
# assembler.py — assemble_system_prompt
# ===========================================================================


class TestAssembleSystemPrompt:
    def test_empty_workspace_returns_empty_string(self, tmp_path):
        result = assemble_system_prompt(tmp_path)
        assert result == ""

    def test_soul_only_includes_framing(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind and helpful.")
        result = assemble_system_prompt(tmp_path)
        assert _SOUL_FRAMING.strip() in result
        assert "Be kind and helpful." in result

    def test_identity_only_no_framing(self, tmp_path):
        _write(tmp_path / "IDENTITY.md", "Name: Aria")
        result = assemble_system_prompt(tmp_path)
        assert _SOUL_FRAMING.strip() not in result
        assert "Name: Aria" in result

    def test_both_files_framing_and_order(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be a pirate.")
        _write(tmp_path / "IDENTITY.md", "Name: Captain Hook")
        result = assemble_system_prompt(tmp_path)
        # Framing must appear before soul content
        framing_pos = result.index(_SOUL_FRAMING.strip())
        soul_pos = result.index("Be a pirate.")
        identity_pos = result.index("Name: Captain Hook")
        assert framing_pos < soul_pos < identity_pos

    def test_runtime_info_appended(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind.")
        result = assemble_system_prompt(tmp_path, runtime_info="Date: 2026-04-11")
        assert "Date: 2026-04-11" in result
        assert result.index("Date: 2026-04-11") > result.index("Be kind.")

    def test_runtime_info_only_no_persona_files(self, tmp_path):
        result = assemble_system_prompt(tmp_path, runtime_info="Device: rk3588")
        assert result == "Device: rk3588"

    def test_sections_separated_by_delimiter(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind.")
        _write(tmp_path / "IDENTITY.md", "Name: Aria")
        result = assemble_system_prompt(tmp_path)
        assert _SECTION_SEPARATOR in result

    def test_accepts_string_path(self, tmp_path):
        _write(tmp_path / "SOUL.md", "Be kind.")
        result = assemble_system_prompt(str(tmp_path))
        assert "Be kind." in result

    def test_whitespace_stripped_from_file_content(self, tmp_path):
        _write(tmp_path / "SOUL.md", "  \n  Be kind.  \n  ")
        result = assemble_system_prompt(tmp_path)
        assert "Be kind." in result

    def test_runtime_info_whitespace_stripped(self, tmp_path):
        result = assemble_system_prompt(tmp_path, runtime_info="  info  ")
        assert result == "info"


# ===========================================================================
# config.py
# ===========================================================================


class TestResolveWorkspace:
    def test_returns_path_under_custom_base(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/custom/agents"}):
            path = resolve_workspace("myagent")
        assert path == Path("/custom/agents/myagent")

    def test_uses_dev_base_when_prod_missing(self, tmp_path):
        # Force neither prod nor custom dir to exist
        with patch.dict(os.environ, {}, clear=True):
            with patch("bmt_ai_os.persona.config._PROD_BASE", tmp_path / "nonexistent"):
                path = resolve_workspace("bot")
        assert path.name == "bot"

    def test_uses_env_var_override(self, tmp_path):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": str(tmp_path)}):
            path = resolve_workspace("coder")
        assert path == tmp_path / "coder"

    def test_raises_on_empty_agent_id(self):
        with pytest.raises(ValueError, match="agent_id"):
            resolve_workspace("")

    def test_prod_base_used_when_exists(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            with patch("bmt_ai_os.persona.config._PROD_BASE", tmp_path):
                path = resolve_workspace("assistant")
        assert path == tmp_path / "assistant"


class TestAgentPersona:
    def test_default_display_name_from_agent_id(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/tmp/agents"}):
            persona = AgentPersona(agent_id="coder")
        assert persona.display_name == "coder"

    def test_explicit_display_name(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/tmp/agents"}):
            persona = AgentPersona(agent_id="coder", display_name="Code Bot")
        assert persona.display_name == "Code Bot"

    def test_workspace_dir_auto_resolved(self, tmp_path):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": str(tmp_path)}):
            persona = AgentPersona(agent_id="assistant")
        assert persona.workspace_dir == tmp_path / "assistant"

    def test_explicit_workspace_dir_not_overridden(self, tmp_path):
        custom = tmp_path / "custom_ws"
        persona = AgentPersona(agent_id="bot", workspace_dir=custom)
        assert persona.workspace_dir == custom

    def test_default_model_empty_string(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/tmp/agents"}):
            persona = AgentPersona(agent_id="viewer")
        assert persona.default_model == ""

    def test_custom_model(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/tmp/agents"}):
            persona = AgentPersona(agent_id="coder", default_model="qwen2.5-coder:7b")
        assert persona.default_model == "qwen2.5-coder:7b"

    def test_tags_default_empty(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/tmp/agents"}):
            persona = AgentPersona(agent_id="bot")
        assert persona.tags == []

    def test_tags_assigned(self):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": "/tmp/agents"}):
            persona = AgentPersona(agent_id="bot", tags=["coding", "rag"])
        assert "coding" in persona.tags


# ===========================================================================
# Integration — persona isolation (BMTOS-90)
# ===========================================================================


class TestMultiAgentIsolation:
    """Each agent workspace is fully isolated."""

    def test_separate_souls(self, tmp_path):
        agent_a = tmp_path / "agent-a"
        agent_b = tmp_path / "agent-b"
        _write(agent_a / "SOUL.md", "I am Agent A: direct and concise.")
        _write(agent_b / "SOUL.md", "I am Agent B: warm and verbose.")

        prompt_a = assemble_system_prompt(agent_a)
        prompt_b = assemble_system_prompt(agent_b)

        assert "Agent A" in prompt_a
        assert "Agent B" not in prompt_a
        assert "Agent B" in prompt_b
        assert "Agent A" not in prompt_b

    def test_agent_without_soul_gets_no_framing(self, tmp_path):
        agent_a = tmp_path / "agent-a"
        agent_b = tmp_path / "agent-b"
        _write(agent_a / "SOUL.md", "Personality text.")
        # agent_b has no persona files

        prompt_a = assemble_system_prompt(agent_a)
        prompt_b = assemble_system_prompt(agent_b)

        assert _SOUL_FRAMING.strip() in prompt_a
        assert prompt_b == ""

    def test_per_agent_model_defaults(self, tmp_path):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": str(tmp_path)}):
            coder = AgentPersona(agent_id="coder", default_model="qwen2.5-coder:7b")
            chat = AgentPersona(agent_id="chat", default_model="qwen2.5:3b")

        assert coder.default_model == "qwen2.5-coder:7b"
        assert chat.default_model == "qwen2.5:3b"
        assert coder.workspace_dir != chat.workspace_dir

    def test_agent_persona_resolve_workspace_unique(self, tmp_path):
        with patch.dict(os.environ, {"BMT_PERSONA_DIR": str(tmp_path)}):
            p1 = AgentPersona(agent_id="alpha")
            p2 = AgentPersona(agent_id="beta")

        assert p1.workspace_dir != p2.workspace_dir
        assert p1.workspace_dir.name == "alpha"
        assert p2.workspace_dir.name == "beta"

    def test_identity_isolation(self, tmp_path):
        agent_a = tmp_path / "agent-a"
        agent_b = tmp_path / "agent-b"
        _write(agent_a / "IDENTITY.md", "Name: Aria\nRole: Assistant")
        _write(agent_b / "IDENTITY.md", "Name: Rex\nRole: Coder")

        prompt_a = assemble_system_prompt(agent_a)
        prompt_b = assemble_system_prompt(agent_b)

        assert "Aria" in prompt_a and "Rex" not in prompt_a
        assert "Rex" in prompt_b and "Aria" not in prompt_b
