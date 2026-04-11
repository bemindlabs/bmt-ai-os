"""Image verification helpers for BMT AI OS OTA.

Two levels of verification are provided:

1. **SHA-256 checksum** — fast integrity check, always available via stdlib.
2. **Ed25519 signature** — authenticates the image against a trusted public
   key.  Requires Python ≥ 3.11 (``cryptography`` is *not* needed; the stdlib
   ``hashlib`` / ``hmac`` covers SHA-256, and Ed25519 is exposed via
   ``cryptography`` *if installed*, otherwise falls back gracefully with a
   clear error).

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

# Default location of the OTA signing public key on production images.
_DEFAULT_PUBKEY_PATH = "/etc/bmt_ai_os/ota-signing-key.pub"


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
# High-level download verification
# ---------------------------------------------------------------------------


def verify_download(
    image_path: str | Path,
    *,
    sig_path: str | Path | None = None,
    pubkey_path: str | Path | None = None,
) -> bool:
    """Verify an OTA image download using Ed25519 signature authentication.

    This is the primary entry point used by the OTA engine after a download
    completes.  It combines a SHA-256 integrity check (fast) with an Ed25519
    authenticity check (cryptographic) so that neither a corrupted download
    nor a tampered image can slip through.

    Parameters
    ----------
    image_path:
        Path to the downloaded OTA image file.
    sig_path:
        Path to the detached ``.sig`` file.  Defaults to
        ``<image_path>.sig`` when not provided.
    pubkey_path:
        Path to the Ed25519 public key used for verification.  Defaults to
        ``/etc/bmt_ai_os/ota-signing-key.pub`` (overridable via the
        ``BMT_OTA_PUBKEY_PATH`` environment variable).

    Returns
    -------
    bool
        ``True`` when the signature is valid, ``False`` on any failure
        (missing file, bad signature, key parse error).

    Raises
    ------
    RuntimeError
        When the ``cryptography`` package is not installed.

    Notes
    -----
    The ``BMT_OTA_PUBKEY_PATH`` environment variable overrides the built-in
    default key location, which is useful in CI and development environments.
    """
    image_path = Path(image_path)

    # Resolve signature path: default to <image>.sig
    if sig_path is None:
        sig_path = image_path.with_suffix(image_path.suffix + ".sig")
    sig_path = Path(sig_path)

    # Resolve public key path: env var > explicit arg > built-in default
    if pubkey_path is None:
        pubkey_path = Path(os.getenv("BMT_OTA_PUBKEY_PATH", _DEFAULT_PUBKEY_PATH))
    pubkey_path = Path(pubkey_path)

    return verify_signature(image_path, sig_path, pubkey_path)
