"""OTA state tracking for BMT AI OS.

The canonical state file lives at ``/data/bmt_ai_os/db/ota-state.json`` on
a real device.  For local development, the path can be overridden via the
``BMT_OTA_STATE_PATH`` environment variable.

State schema (JSON)
-------------------
{
    "current_slot":  "a" | "b",
    "standby_slot":  "b" | "a",
    "last_update":   "<ISO-8601 UTC timestamp> | null",
    "bootcount":     <int>,       // incremented each unconfirmed boot
    "confirmed":     <bool>       // true once confirm_boot() succeeds
}
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_DEFAULT_STATE_PATH = "/data/bmt_ai_os/db/ota-state.json"


def _state_path() -> Path:
    """Return the resolved state file path, honoring env override."""
    override = os.environ.get("BMT_OTA_STATE_PATH")
    return Path(override) if override else Path(_DEFAULT_STATE_PATH)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OTAState:
    """Snapshot of the current OTA / boot state."""

    current_slot: str = "a"
    standby_slot: str = "b"
    last_update: str | None = None  # ISO-8601 UTC or None
    bootcount: int = 0
    confirmed: bool = True  # factory image is pre-confirmed

    # -------------------------------------------------------------------
    # Serialisation helpers
    # -------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OTAState":
        return cls(
            current_slot=str(data.get("current_slot", "a")),
            standby_slot=str(data.get("standby_slot", "b")),
            last_update=data.get("last_update"),
            bootcount=int(data.get("bootcount", 0)),
            confirmed=bool(data.get("confirmed", True)),
        )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


class StateManager:
    """Reads and writes :class:`OTAState` to a JSON file.

    Parameters
    ----------
    path:
        Override the state file location.  Defaults to
        :func:`_state_path`.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path: Path = Path(path) if path else _state_path()

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> OTAState:
        """Load state from disk.  Returns a default :class:`OTAState` when
        the file does not exist yet (first boot / clean install)."""
        if not self._path.exists():
            return OTAState()
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return OTAState.from_dict(data)
        except (json.JSONDecodeError, OSError):
            # Corrupted state file — fall back to defaults so the system
            # remains bootable; the next confirm_boot() call will overwrite.
            return OTAState()

    def save(self, state: OTAState) -> None:
        """Persist *state* to disk atomically (write-then-rename)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
            fh.write("\n")
        tmp.replace(self._path)

    # ------------------------------------------------------------------
    # Convenience mutators
    # ------------------------------------------------------------------

    def increment_bootcount(self) -> OTAState:
        """Bump bootcount (called on each boot before confirmation)."""
        state = self.load()
        state.bootcount += 1
        state.confirmed = False
        self.save(state)
        return state

    def confirm(self) -> OTAState:
        """Mark the current boot as good; reset bootcount."""
        state = self.load()
        state.bootcount = 0
        state.confirmed = True
        self.save(state)
        return state

    def switch_slots(self) -> OTAState:
        """Swap current / standby after a successful image write.

        The new current slot becomes the previously standby slot.  The
        ``confirmed`` flag is reset so the next boot requires explicit
        confirmation.
        """
        state = self.load()
        state.current_slot, state.standby_slot = (
            state.standby_slot,
            state.current_slot,
        )
        state.confirmed = False
        state.bootcount = 0
        state.last_update = datetime.now(timezone.utc).isoformat()
        self.save(state)
        return state

    def set_last_update(self, ts: str | None = None) -> OTAState:
        """Record an update timestamp (defaults to *now* in UTC ISO-8601)."""
        state = self.load()
        state.last_update = ts or datetime.now(timezone.utc).isoformat()
        self.save(state)
        return state
