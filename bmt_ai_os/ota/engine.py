"""OTA update engine for BMT AI OS — A/B slot switching.

Public API
----------
- :func:`check_update` — query the release server for a newer version
- :func:`download_image` — download with progress reporting + SHA-256 verify
- :func:`apply_update` — write the image to the standby partition
- :func:`confirm_boot` — mark the current boot as good (reset bootcount)
- :func:`get_current_slot` — return the active slot name ("a" or "b")

All functions are synchronous and use stdlib only (``urllib``, ``hashlib``,
``subprocess``).

Partition write strategy
------------------------
On a real device ``apply_update`` invokes ``dd`` via :mod:`subprocess` to
write the image to a block device such as ``/dev/disk/by-partlabel/boot_b``.
In the default **file-backed** mode (``dry_run=True`` or when the target slot
device does not exist) the function copies the image to a plain file under
``/data/bmt_ai_os/slots/<slot>.img`` so the engine is fully testable without
root or physical hardware.

U-Boot env integration
-----------------------
``get_current_slot`` reads the ``slot_name`` variable from U-Boot environment
via ``fw_printenv``.  On a development machine (where ``fw_printenv`` is
absent) it falls back to the :class:`~bmt_ai_os.ota.state.StateManager`
state file.  ``confirm_boot`` writes ``bootcount=0 upgrade_available=0`` back
via ``fw_setenv`` (no-op on dev machines).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bmt_ai_os.ota.state import StateManager
from bmt_ai_os.ota.verify import enforce_signature

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_SLOT_DEVICES: dict[str, str] = {
    "a": os.environ.get("BMT_OTA_SLOT_A_DEV", "/dev/disk/by-partlabel/boot_a"),
    "b": os.environ.get("BMT_OTA_SLOT_B_DEV", "/dev/disk/by-partlabel/boot_b"),
}

_SLOT_FILE_DIR_DEFAULT = "/data/bmt_ai_os/slots"


def _slot_file_dir() -> Path:
    """Return the file-backed slot directory, honouring env override at call time."""
    return Path(os.environ.get("BMT_OTA_SLOT_DIR", _SLOT_FILE_DIR_DEFAULT))


_CHUNK_SIZE = 1 << 17  # 128 KiB download chunks

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class UpdateInfo:
    """Metadata for an available OS update returned by :func:`check_update`."""

    version: str
    url: str
    sha256: str
    release_notes: str = ""
    size_bytes: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_update(
    server_url: str,
    current_version: str | None = None,
    timeout: int = 15,
) -> UpdateInfo | None:
    """Query *server_url* for a newer OS image.

    The server is expected to respond with JSON of the form::

        {
            "version":       "2026.5.1",
            "url":           "https://releases.example.com/bmt-ai-os-2026.5.1.img.zst",
            "sha256":        "abc123...",
            "release_notes": "Bug fixes and performance improvements.",
            "size_bytes":    123456789
        }

    Parameters
    ----------
    server_url:
        Full URL of the release-info endpoint (e.g.
        ``https://releases.bemindlabs.com/bmt-ai-os/latest.json``).
    current_version:
        The running version string.  When provided, the function returns
        ``None`` if the server version is not strictly newer.
    timeout:
        HTTP request timeout in seconds.

    Returns
    -------
    UpdateInfo | None
        ``None`` means either the server is unreachable, the response is
        invalid, or no update is available.
    """
    logger.debug("check_update: querying %s", server_url)
    try:
        req = urllib.request.Request(
            server_url,
            headers={"User-Agent": "bmt-ai-os/ota"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read(1 << 20)  # 1 MiB cap
            data = json.loads(body)
    except urllib.error.URLError as exc:
        logger.warning("check_update: network error — %s", exc)
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("check_update: bad response — %s", exc)
        return None

    # Validate required fields.
    for field in ("version", "url", "sha256"):
        if not data.get(field):
            logger.warning("check_update: missing field '%s' in server response", field)
            return None

    info = UpdateInfo(
        version=str(data["version"]),
        url=str(data["url"]),
        sha256=str(data["sha256"]),
        release_notes=str(data.get("release_notes", "")),
        size_bytes=int(data.get("size_bytes", 0)),
    )

    if current_version and not _is_newer(info.version, current_version):
        logger.info(
            "check_update: no update available (current=%s, server=%s)",
            current_version,
            info.version,
        )
        return None

    logger.info("check_update: update available — version %s", info.version)
    return info


def download_image(
    url: str,
    dest_path: str | Path,
    expected_sha256: str,
    progress_cb: Callable[[int, int], None] | None = None,
    timeout: int = 3600,
) -> bool:
    """Download an OS image from *url* to *dest_path* and verify its SHA-256.

    The download is streamed in chunks to keep memory usage low.  A progress
    callback receives ``(bytes_received, total_bytes)`` — total may be ``0``
    when the server omits ``Content-Length``.

    Parameters
    ----------
    url:
        Direct download URL for the image file.
    dest_path:
        Local filesystem path to write the downloaded file.
    expected_sha256:
        Hex-encoded SHA-256 digest that the downloaded file must match.
    progress_cb:
        Optional callable invoked after each chunk.
    timeout:
        Socket timeout for the underlying connection (seconds).

    Returns
    -------
    bool
        ``True`` on success (download complete + checksum matches).
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    logger.info("download_image: starting download from %s → %s", url, dest)

    req = urllib.request.Request(url, headers={"User-Agent": "bmt-ai-os/ota"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            total = int(resp.headers.get("Content-Length", 0))
            received = 0
            h = hashlib.sha256()

            with dest.open("wb") as fh:
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    fh.write(chunk)
                    h.update(chunk)
                    received += len(chunk)
                    if progress_cb:
                        progress_cb(received, total)

    except urllib.error.URLError as exc:
        logger.error("download_image: network error — %s", exc)
        _safe_unlink(dest)
        return False
    except OSError as exc:
        logger.error("download_image: I/O error writing %s — %s", dest, exc)
        _safe_unlink(dest)
        return False

    # Verify checksum.
    actual = h.hexdigest()
    if not _ct_equal(actual.lower(), expected_sha256.lower()):
        logger.error(
            "download_image: SHA-256 mismatch (expected=%s, got=%s)",
            expected_sha256,
            actual,
        )
        _safe_unlink(dest)
        return False

    logger.info("download_image: checksum OK (%s)", actual)
    return True


def apply_update(
    image_path: str | Path,
    target_slot: str,
    dry_run: bool | None = None,
    state_manager: StateManager | None = None,
    sig_path: str | Path | None = None,
) -> bool:
    """Write *image_path* to the *target_slot* partition.

    In production the image is written via ``dd`` to the block device
    associated with *target_slot*.  In file-backed / development mode the
    image is copied to ``/data/bmt_ai_os/slots/<slot>.img``.

    Ed25519 signature verification is enforced before any write occurs.
    The signature file is resolved in the same way as
    :func:`~bmt_ai_os.ota.verify.enforce_signature`: *sig_path* when
    provided, otherwise ``<image_path>.sig``.  Set
    ``BMT_OTA_ALLOW_UNSIGNED=true`` to skip verification in development.

    The function performs a SHA-256 readback verification after writing to
    confirm data integrity.

    Parameters
    ----------
    image_path:
        Path to the locally downloaded (and pre-verified) image file.
    target_slot:
        Slot identifier: ``"a"`` or ``"b"``.
    dry_run:
        When ``True`` always use the file-backed path even on a real device.
        When ``None`` (default) auto-detect: use block device if present,
        otherwise fall back to file-backed.
    state_manager:
        Injected :class:`~bmt_ai_os.ota.state.StateManager` for testability.
        Defaults to a fresh instance using the default path.
    sig_path:
        Explicit path to the detached Ed25519 signature.  Defaults to
        ``<image_path>.sig`` when ``None``.

    Returns
    -------
    bool
        ``True`` when the image was written and the readback checksum matches.

    Raises
    ------
    PermissionError
        When Ed25519 signature verification fails and
        ``BMT_OTA_ALLOW_UNSIGNED`` is not ``true``.
    """
    if target_slot not in ("a", "b"):
        logger.error("apply_update: invalid slot '%s'", target_slot)
        return False

    image_path = Path(image_path)
    if not image_path.is_file():
        logger.error("apply_update: image not found at %s", image_path)
        return False

    # --- Ed25519 signature gate (required by default) -----------------
    enforce_signature(image_path, sig_path)

    sm = state_manager or StateManager()

    # Determine write target.
    block_dev = Path(_SLOT_DEVICES.get(target_slot, ""))
    use_file_backed = (dry_run is True) or (dry_run is None and not block_dev.exists())

    if use_file_backed:
        success = _write_file_backed(image_path, target_slot)
    else:
        success = _write_dd(image_path, block_dev)

    if not success:
        return False

    # Record the update in state and switch the slot pointers so the next
    # boot will try the new image.
    sm.switch_slots()
    logger.info("apply_update: slot switched — standby slot %s is now current", target_slot)
    return True


def confirm_boot(state_manager: StateManager | None = None) -> None:
    """Mark the current boot as confirmed (healthy).

    Resets bootcount in the state file and — on real hardware — tells
    U-Boot that no automatic rollback is needed.

    Parameters
    ----------
    state_manager:
        Injected :class:`~bmt_ai_os.ota.state.StateManager`.  Defaults to
        a fresh instance.
    """
    sm = state_manager or StateManager()
    state = sm.confirm()
    logger.info(
        "confirm_boot: slot '%s' confirmed, bootcount reset to %d",
        state.current_slot,
        state.bootcount,
    )

    # Best-effort U-Boot env update; silently skip when fw_setenv is absent.
    _fw_setenv("bootcount", "0")
    _fw_setenv("upgrade_available", "0")


def get_current_slot(state_manager: StateManager | None = None) -> str:
    """Return the currently active slot name (``"a"`` or ``"b"``).

    Reads from (in priority order):

    1. ``fw_printenv slot_name`` — U-Boot environment (real device).
    2. ``BMT_OTA_CURRENT_SLOT`` environment variable — useful in CI.
    3. The :class:`~bmt_ai_os.ota.state.StateManager` state file.

    Returns
    -------
    str
        ``"a"`` or ``"b"``.  Defaults to ``"a"`` when nothing is configured.
    """
    # 1. U-Boot env.
    uboot_slot = _fw_printenv("slot_name")
    if uboot_slot in ("a", "b"):
        return uboot_slot

    # 2. Environment variable (CI / dev override).
    env_slot = os.environ.get("BMT_OTA_CURRENT_SLOT", "").strip().lower()
    if env_slot in ("a", "b"):
        return env_slot

    # 3. State file.
    sm = state_manager or StateManager()
    state = sm.load()
    return state.current_slot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_file_backed(image_path: Path, slot: str) -> bool:
    """Copy *image_path* into the file-backed slot store."""
    slot_dir = _slot_file_dir()
    slot_dir.mkdir(parents=True, exist_ok=True)
    dest = slot_dir / f"{slot}.img"

    logger.info("apply_update (file-backed): writing %s → %s", image_path, dest)

    # Compute SHA-256 of the source before copying for readback comparison.
    src_hash = _hash_file(image_path)
    if src_hash is None:
        logger.error("apply_update: failed to hash source image")
        return False

    try:
        shutil.copy2(image_path, dest)
    except OSError as exc:
        logger.error("apply_update: copy failed — %s", exc)
        return False

    # Readback verification.
    dest_hash = _hash_file(dest)
    if dest_hash != src_hash:
        logger.error("apply_update: readback hash mismatch after copy")
        _safe_unlink(dest)
        return False

    logger.info("apply_update (file-backed): readback OK, slot %s image written", slot)
    return True


def _write_dd(image_path: Path, device: Path) -> bool:
    """Write *image_path* to *device* using ``dd``."""
    logger.info("apply_update (dd): writing %s → %s", image_path, device)

    # Pre-hash the source.
    src_hash = _hash_file(image_path)
    if src_hash is None:
        return False

    cmd = [
        "dd",
        f"if={image_path}",
        f"of={device}",
        "bs=4M",
        "conv=fsync",
        "status=progress",
    ]

    try:
        result = subprocess.run(cmd, capture_output=False, timeout=3600)
    except FileNotFoundError:
        logger.error("apply_update (dd): 'dd' not found on PATH")
        return False
    except subprocess.TimeoutExpired:
        logger.error("apply_update (dd): dd timed out")
        return False

    if result.returncode != 0:
        logger.error("apply_update (dd): dd exited with code %d", result.returncode)
        return False

    # Readback: hash the device block range equal to image size.
    image_size = image_path.stat().st_size
    dest_hash = _hash_block_device(device, image_size)
    if dest_hash != src_hash:
        logger.error("apply_update (dd): readback hash mismatch")
        return False

    logger.info("apply_update (dd): readback OK, device %s written", device)
    return True


def _hash_file(path: Path) -> str | None:
    """Return the hex SHA-256 of *path*, or ``None`` on I/O error."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 17):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _hash_block_device(device: Path, size: int) -> str | None:
    """SHA-256 the first *size* bytes of *device*."""
    h = hashlib.sha256()
    chunk_size = 1 << 17
    remaining = size
    try:
        with device.open("rb") as fh:
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                chunk = fh.read(to_read)
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _fw_printenv(key: str) -> str:
    """Return the value of U-Boot env variable *key*, or ``""`` on failure."""
    try:
        result = subprocess.run(
            ["fw_printenv", key],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # fw_printenv output: "key=value\n"
            line = result.stdout.strip()
            if "=" in line:
                return line.split("=", 1)[1].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _fw_setenv(key: str, value: str) -> bool:
    """Set U-Boot env *key=value*.  Returns ``True`` on success."""
    try:
        result = subprocess.run(
            ["fw_setenv", key, value],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _ct_equal(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _is_newer(candidate: str, current: str) -> bool:
    """Return ``True`` when *candidate* version string is newer than *current*.

    Compares dot-separated integer tuples (e.g. ``"2026.5.1" > "2026.4.10"``).
    Falls back to a simple lexicographic comparison if parsing fails.
    """
    try:
        c_parts = tuple(int(x) for x in candidate.split("."))
        r_parts = tuple(int(x) for x in current.split("."))
        return c_parts > r_parts
    except ValueError:
        return candidate > current
