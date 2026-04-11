"""Image verification helpers for BMT AI OS OTA.

Two levels of verification are provided:

1. **SHA-256 checksum** — fast integrity check, always available via stdlib.
2. **Ed25519 signature** — authenticates the image against a trusted public
   key.  Requires the ``cryptography`` package (shipped with the OS image).

Signature policy
----------------
By default Ed25519 verification is **required**.  The public key is loaded
from (in priority order):

1. ``BMT_OTA_PUBKEY`` environment variable — path to a PEM/DER/raw-32-byte
   Ed25519 public key file.
2. ``/etc/bmt_ai_os/ota-pubkey.pem`` — key baked into the OS image at build
   time.

Unsigned images are **rejected** unless ``BMT_OTA_ALLOW_UNSIGNED=true`` is
set in the environment.  This escape-hatch exists for development/CI only;
production images must never set it.

Design note
-----------
The signature verification deliberately imports ``cryptography`` lazily so
that the rest of the OTA engine remains stdlib-only.  On production images
``cryptography`` is expected to be present; on a bare development machine the
function raises ``RuntimeError`` with an actionable message rather than
crashing at import time.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 1 << 16  # 64 KiB read chunks — efficient for large images

# Default public key path baked into production OS images.
_DEFAULT_PUBKEY_PATH = "/etc/bmt_ai_os/ota-pubkey.pem"


# ---------------------------------------------------------------------------
# Environment-driven policy helpers
# ---------------------------------------------------------------------------


def _pubkey_path() -> Path:
    """Return the configured Ed25519 public key path."""
    override = os.environ.get("BMT_OTA_PUBKEY", "").strip()
    return Path(override) if override else Path(_DEFAULT_PUBKEY_PATH)


def _allow_unsigned() -> bool:
    """Return ``True`` when ``BMT_OTA_ALLOW_UNSIGNED=true`` is set."""
    return os.environ.get("BMT_OTA_ALLOW_UNSIGNED", "").strip().lower() == "true"


# ---------------------------------------------------------------------------
# SHA-256 verification
# ---------------------------------------------------------------------------


def verify_sha256(file_path: str | Path, expected: str) -> bool:
    """Return ``True`` when *file_path* matches the *expected* SHA-256 hex digest.

    Parameters
    ----------
    file_path:
        Path to the file to hash.
    expected:
        Lowercase hex-encoded SHA-256 digest (64 characters).

    Returns
    -------
    bool
        ``True`` on match, ``False`` on mismatch or I/O error.
    """
    path = Path(file_path)
    if not path.is_file():
        return False

    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK_SIZE):
                h.update(chunk)
    except OSError:
        return False

    actual = h.hexdigest()
    # Constant-time comparison avoids timing side-channels.
    return _ct_equal(actual.lower(), expected.lower())


def _ct_equal(a: str, b: str) -> bool:
    """Constant-time string equality (length-aware)."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


# ---------------------------------------------------------------------------
# Ed25519 signature verification
# ---------------------------------------------------------------------------


def verify_signature(
    file_path: str | Path,
    sig_path: str | Path,
    pubkey_path: str | Path,
) -> bool:
    """Verify an Ed25519 detached signature over *file_path*.

    Parameters
    ----------
    file_path:
        The image file whose content was signed.
    sig_path:
        Path to the raw 64-byte Ed25519 signature (binary file).
    pubkey_path:
        Path to the DER- or PEM-encoded Ed25519 public key.

    Returns
    -------
    bool
        ``True`` when the signature is valid, ``False`` on any failure
        (bad signature, missing file, key parse error, …).

    Raises
    ------
    RuntimeError
        When the ``cryptography`` package is not installed.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError(
            "Ed25519 verification requires the 'cryptography' package "
            "(pip install cryptography).  It is not part of the stdlib-only "
            "default install."
        ) from exc

    sig_path = Path(sig_path)
    pubkey_path = Path(pubkey_path)
    file_path = Path(file_path)

    for p in (sig_path, pubkey_path, file_path):
        if not p.is_file():
            return False

    # --- Load public key -----------------------------------------------
    try:
        raw_key = pubkey_path.read_bytes()
        # Try PEM first, fall back to raw 32-byte key.
        if raw_key.startswith(b"-----"):
            public_key: Ed25519PublicKey = serialization.load_pem_public_key(raw_key)  # type: ignore[assignment]
        elif len(raw_key) == 32:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Ed

            public_key = _Ed.from_public_bytes(raw_key)
        else:
            public_key = serialization.load_der_public_key(raw_key)  # type: ignore[assignment]
    except Exception:
        return False

    # --- Load signature ------------------------------------------------
    try:
        signature = sig_path.read_bytes()
    except OSError:
        return False

    # --- Hash the image and verify ------------------------------------
    h = hashlib.sha256()
    try:
        with file_path.open("rb") as fh:
            while chunk := fh.read(_CHUNK_SIZE):
                h.update(chunk)
    except OSError:
        return False

    digest = h.digest()

    try:
        public_key.verify(signature, digest)
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Policy enforcement
# ---------------------------------------------------------------------------


def enforce_signature(
    image_path: str | Path,
    sig_path: str | Path | None = None,
) -> None:
    """Enforce Ed25519 signature policy before an image is applied.

    This is the single choke-point that the OTA engine must call before
    writing any image to a slot.

    Behaviour
    ---------
    * When ``BMT_OTA_ALLOW_UNSIGNED=true``: logs a warning and returns
      without verification (development/CI escape-hatch only).
    * Otherwise: looks up the public key via :func:`_pubkey_path`, derives
      the default signature path from *image_path* (``<image>.sig``) when
      *sig_path* is ``None``, and calls :func:`verify_signature`.  Raises
      :class:`PermissionError` when verification fails or the signature file
      is missing.

    Parameters
    ----------
    image_path:
        Path to the downloaded image file.
    sig_path:
        Explicit path to the detached signature.  Defaults to
        ``<image_path>.sig`` when ``None``.

    Raises
    ------
    PermissionError
        When the signature is missing, invalid, or verification is not
        possible (e.g. ``cryptography`` absent and unsigned images are
        disallowed).
    """
    import logging

    logger = logging.getLogger(__name__)

    if _allow_unsigned():
        logger.warning(
            "enforce_signature: BMT_OTA_ALLOW_UNSIGNED=true — "
            "skipping Ed25519 verification for %s (UNSAFE, dev only)",
            image_path,
        )
        return

    image_path = Path(image_path)
    resolved_sig = (
        Path(sig_path)
        if sig_path is not None
        else image_path.with_suffix(image_path.suffix + ".sig")
    )
    pubkey = _pubkey_path()

    logger.debug(
        "enforce_signature: verifying %s with sig=%s pubkey=%s",
        image_path,
        resolved_sig,
        pubkey,
    )

    if not resolved_sig.is_file():
        raise PermissionError(
            f"OTA signature file not found: {resolved_sig}. "
            "Set BMT_OTA_ALLOW_UNSIGNED=true to bypass (dev only)."
        )

    if not pubkey.is_file():
        raise PermissionError(
            f"OTA public key not found: {pubkey}. "
            "Set BMT_OTA_PUBKEY to an alternative path or "
            "BMT_OTA_ALLOW_UNSIGNED=true to bypass (dev only)."
        )

    try:
        valid = verify_signature(image_path, resolved_sig, pubkey)
    except RuntimeError as exc:
        raise PermissionError(
            f"Ed25519 verification unavailable: {exc}. "
            "Install the 'cryptography' package or set BMT_OTA_ALLOW_UNSIGNED=true (dev only)."
        ) from exc

    if not valid:
        raise PermissionError(
            f"Ed25519 signature verification FAILED for {image_path}. "
            "The image may be corrupted or tampered. "
            "Set BMT_OTA_ALLOW_UNSIGNED=true to bypass (dev only)."
        )

    logger.info("enforce_signature: signature OK for %s", image_path)
