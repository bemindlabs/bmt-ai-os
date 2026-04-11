"""BMT AI OS — OTA update engine (A/B slot switching)."""

from bmt_ai_os.ota.engine import (
    UpdateInfo,
    apply_update,
    check_update,
    confirm_boot,
    download_image,
    get_current_slot,
    rollback_update,
    should_rollback,
)
from bmt_ai_os.ota.state import OTAState, StateManager
from bmt_ai_os.ota.verify import verify_sha256, verify_signature

__all__ = [
    "UpdateInfo",
    "apply_update",
    "check_update",
    "confirm_boot",
    "download_image",
    "get_current_slot",
    "rollback_update",
    "should_rollback",
    "OTAState",
    "StateManager",
    "verify_sha256",
    "verify_signature",
]
