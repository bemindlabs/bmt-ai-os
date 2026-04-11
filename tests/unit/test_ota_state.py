"""Unit tests for bmt_ai_os.ota.state."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bmt_ai_os.ota.state import OTAState, StateManager, _state_path


class TestOTAState:
    def test_default_values(self):
        s = OTAState()
        assert s.current_slot == "a"
        assert s.standby_slot == "b"
        assert s.bootcount == 0
        assert s.confirmed is True
        assert s.last_update is None

    def test_to_dict(self):
        s = OTAState(current_slot="b", standby_slot="a", bootcount=2, confirmed=False)
        d = s.to_dict()
        assert d["current_slot"] == "b"
        assert d["standby_slot"] == "a"
        assert d["bootcount"] == 2
        assert d["confirmed"] is False

    def test_from_dict_round_trip(self):
        s = OTAState(current_slot="b", standby_slot="a", bootcount=3, confirmed=True)
        s2 = OTAState.from_dict(s.to_dict())
        assert s2.current_slot == "b"
        assert s2.standby_slot == "a"
        assert s2.bootcount == 3
        assert s2.confirmed is True

    def test_from_dict_uses_defaults_for_missing_keys(self):
        s = OTAState.from_dict({})
        assert s.current_slot == "a"
        assert s.bootcount == 0

    def test_from_dict_coerces_types(self):
        s = OTAState.from_dict({"bootcount": "5", "confirmed": 1})
        assert s.bootcount == 5
        assert s.confirmed is True


class TestStatePath:
    def test_returns_default_path_when_no_env(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("BMT_OTA_STATE_PATH", None)
            path = _state_path()
        assert "ota-state.json" in str(path)

    def test_honors_env_override(self, tmp_path):
        override = str(tmp_path / "custom-state.json")
        with patch.dict("os.environ", {"BMT_OTA_STATE_PATH": override}):
            path = _state_path()
        assert str(path) == override


class TestStateManager:
    def _make(self, tmp_path: Path) -> StateManager:
        return StateManager(path=tmp_path / "ota-state.json")

    def test_load_returns_default_when_file_missing(self, tmp_path):
        sm = self._make(tmp_path)
        state = sm.load()
        assert isinstance(state, OTAState)
        assert state.current_slot == "a"

    def test_save_and_load_round_trip(self, tmp_path):
        sm = self._make(tmp_path)
        original = OTAState(current_slot="b", standby_slot="a", bootcount=1, confirmed=False)
        sm.save(original)
        loaded = sm.load()
        assert loaded.current_slot == "b"
        assert loaded.bootcount == 1
        assert loaded.confirmed is False

    def test_save_creates_parent_directories(self, tmp_path):
        sm = StateManager(path=tmp_path / "nested" / "deep" / "ota-state.json")
        sm.save(OTAState())
        assert sm.path.exists()

    def test_load_returns_default_on_corrupted_file(self, tmp_path):
        sm = self._make(tmp_path)
        sm.path.write_text("not-valid-json!!!")
        state = sm.load()
        assert state.current_slot == "a"  # fallback defaults

    def test_increment_bootcount(self, tmp_path):
        sm = self._make(tmp_path)
        sm.save(OTAState(bootcount=2, confirmed=True))
        state = sm.increment_bootcount()
        assert state.bootcount == 3
        assert state.confirmed is False

    def test_confirm(self, tmp_path):
        sm = self._make(tmp_path)
        sm.save(OTAState(bootcount=3, confirmed=False))
        state = sm.confirm()
        assert state.bootcount == 0
        assert state.confirmed is True

    def test_switch_slots(self, tmp_path):
        sm = self._make(tmp_path)
        sm.save(OTAState(current_slot="a", standby_slot="b"))
        state = sm.switch_slots()
        assert state.current_slot == "b"
        assert state.standby_slot == "a"
        assert state.confirmed is False
        assert state.last_update is not None

    def test_set_last_update_uses_now_by_default(self, tmp_path):
        sm = self._make(tmp_path)
        sm.save(OTAState())
        state = sm.set_last_update()
        assert state.last_update is not None
        assert "T" in state.last_update  # ISO-8601

    def test_set_last_update_with_explicit_timestamp(self, tmp_path):
        sm = self._make(tmp_path)
        sm.save(OTAState())
        state = sm.set_last_update("2026-01-01T00:00:00+00:00")
        assert state.last_update == "2026-01-01T00:00:00+00:00"

    def test_path_property(self, tmp_path):
        sm = self._make(tmp_path)
        assert isinstance(sm.path, Path)
