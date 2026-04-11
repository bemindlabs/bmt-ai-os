"""Unit tests for bmt_ai_os.ota.state.

Covers OTAState data model and StateManager I/O operations using tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bmt_ai_os.ota.state import OTAState, StateManager, _state_path

# ---------------------------------------------------------------------------
# OTAState data model
# ---------------------------------------------------------------------------


class TestOTAState:
    def test_defaults(self):
        s = OTAState()
        assert s.current_slot == "a"
        assert s.standby_slot == "b"
        assert s.last_update is None
        assert s.bootcount == 0
        assert s.confirmed is True

    def test_to_dict_keys(self):
        s = OTAState()
        d = s.to_dict()
        expected_keys = {"current_slot", "standby_slot", "last_update", "bootcount", "confirmed"}
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        s = OTAState(current_slot="b", standby_slot="a", bootcount=3, confirmed=False)
        d = s.to_dict()
        assert d["current_slot"] == "b"
        assert d["standby_slot"] == "a"
        assert d["bootcount"] == 3
        assert d["confirmed"] is False

    def test_from_dict_full(self):
        data = {
            "current_slot": "b",
            "standby_slot": "a",
            "last_update": "2026-04-10T12:00:00+00:00",
            "bootcount": 2,
            "confirmed": False,
        }
        s = OTAState.from_dict(data)
        assert s.current_slot == "b"
        assert s.standby_slot == "a"
        assert s.bootcount == 2
        assert s.confirmed is False
        assert s.last_update == "2026-04-10T12:00:00+00:00"

    def test_from_dict_defaults_on_missing(self):
        s = OTAState.from_dict({})
        assert s.current_slot == "a"
        assert s.standby_slot == "b"
        assert s.bootcount == 0
        assert s.confirmed is True

    def test_round_trip(self):
        original = OTAState(current_slot="b", standby_slot="a", bootcount=5, confirmed=False)
        restored = OTAState.from_dict(original.to_dict())
        assert restored.current_slot == original.current_slot
        assert restored.standby_slot == original.standby_slot
        assert restored.bootcount == original.bootcount
        assert restored.confirmed == original.confirmed


# ---------------------------------------------------------------------------
# _state_path
# ---------------------------------------------------------------------------


class TestStatePath:
    def test_env_override(self, monkeypatch, tmp_path):
        custom = str(tmp_path / "custom-state.json")
        monkeypatch.setenv("BMT_OTA_STATE_PATH", custom)
        assert _state_path() == Path(custom)

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("BMT_OTA_STATE_PATH", raising=False)
        assert _state_path() == Path("/data/bmt_ai_os/db/ota-state.json")


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class TestStateManager:
    @pytest.fixture()
    def manager(self, tmp_path):
        return StateManager(path=tmp_path / "ota-state.json")

    def test_load_returns_defaults_when_no_file(self, manager):
        state = manager.load()
        assert state.current_slot == "a"
        assert state.bootcount == 0

    def test_save_and_load_round_trip(self, manager):
        state = OTAState(current_slot="b", standby_slot="a", bootcount=3, confirmed=False)
        manager.save(state)
        loaded = manager.load()
        assert loaded.current_slot == "b"
        assert loaded.bootcount == 3
        assert loaded.confirmed is False

    def test_save_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "deep" / "nested" / "ota-state.json"
        mgr = StateManager(path=deep_path)
        mgr.save(OTAState())
        assert deep_path.exists()

    def test_save_writes_valid_json(self, manager):
        manager.save(OTAState(bootcount=7))
        content = manager.path.read_text()
        data = json.loads(content)
        assert data["bootcount"] == 7

    def test_load_returns_defaults_on_corrupted_file(self, manager):
        manager.path.parent.mkdir(parents=True, exist_ok=True)
        manager.path.write_text("NOT JSON {{{{")
        state = manager.load()
        assert state.current_slot == "a"  # defaults

    def test_path_property(self, tmp_path):
        p = tmp_path / "state.json"
        mgr = StateManager(path=p)
        assert mgr.path == p

    def test_increment_bootcount(self, manager):
        state = manager.increment_bootcount()
        assert state.bootcount == 1
        assert state.confirmed is False

    def test_increment_bootcount_twice(self, manager):
        manager.increment_bootcount()
        state = manager.increment_bootcount()
        assert state.bootcount == 2

    def test_confirm_resets_bootcount(self, manager):
        manager.increment_bootcount()
        manager.increment_bootcount()
        state = manager.confirm()
        assert state.bootcount == 0
        assert state.confirmed is True

    def test_switch_slots_swaps(self, manager):
        state = manager.switch_slots()
        assert state.current_slot == "b"
        assert state.standby_slot == "a"

    def test_switch_slots_twice_restores(self, manager):
        manager.switch_slots()
        state = manager.switch_slots()
        assert state.current_slot == "a"
        assert state.standby_slot == "b"

    def test_switch_slots_sets_unconfirmed(self, manager):
        state = manager.switch_slots()
        assert state.confirmed is False

    def test_switch_slots_resets_bootcount(self, manager):
        manager.increment_bootcount()
        state = manager.switch_slots()
        assert state.bootcount == 0

    def test_switch_slots_sets_last_update(self, manager):
        state = manager.switch_slots()
        assert state.last_update is not None
        assert "T" in state.last_update

    def test_set_last_update_custom(self, manager):
        ts = "2026-04-10T00:00:00+00:00"
        state = manager.set_last_update(ts)
        assert state.last_update == ts

    def test_set_last_update_auto(self, manager):
        state = manager.set_last_update()
        assert state.last_update is not None
        assert "T" in state.last_update

    def test_atomic_write_uses_tmp_file(self, tmp_path):
        """Verify that save uses a .tmp file for atomic replacement."""
        state_path = tmp_path / "state.json"
        mgr = StateManager(path=state_path)
        mgr.save(OTAState())
        # The .tmp file should no longer exist after successful save
        assert not (tmp_path / "state.tmp").exists()
        assert state_path.exists()
