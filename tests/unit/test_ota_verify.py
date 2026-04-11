"""Unit tests for bmt_ai_os.ota.verify."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from bmt_ai_os.ota.verify import _ct_equal, verify_sha256


def _write_file(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# _ct_equal
# ---------------------------------------------------------------------------


class TestCtEqual:
    def test_equal_strings(self):
        assert _ct_equal("abc", "abc") is True

    def test_different_strings(self):
        assert _ct_equal("abc", "xyz") is False

    def test_different_lengths(self):
        assert _ct_equal("abc", "abcd") is False

    def test_empty_strings(self):
        assert _ct_equal("", "") is True

    def test_case_insensitive_not_confused(self):
        # _ct_equal is case-sensitive; SHA-256 lower() is called by caller
        assert _ct_equal("abc", "ABC") is False


# ---------------------------------------------------------------------------
# verify_sha256
# ---------------------------------------------------------------------------


class TestVerifySha256:
    def test_matching_digest(self, tmp_path):
        data = b"Hello, BMT AI OS!"
        fp = _write_file(tmp_path / "image.bin", data)
        digest = _sha256(data)
        assert verify_sha256(fp, digest) is True

    def test_mismatched_digest(self, tmp_path):
        data = b"Hello, BMT AI OS!"
        fp = _write_file(tmp_path / "image.bin", data)
        wrong = "a" * 64
        assert verify_sha256(fp, wrong) is False

    def test_nonexistent_file(self, tmp_path):
        assert verify_sha256(tmp_path / "missing.bin", "a" * 64) is False

    def test_empty_file(self, tmp_path):
        fp = _write_file(tmp_path / "empty.bin", b"")
        digest = _sha256(b"")
        assert verify_sha256(fp, digest) is True

    def test_large_data(self, tmp_path):
        data = b"x" * (1 << 17)  # 128 KiB — crosses chunk boundary
        fp = _write_file(tmp_path / "large.bin", data)
        digest = _sha256(data)
        assert verify_sha256(fp, digest) is True

    def test_accepts_path_object(self, tmp_path):
        data = b"path-object test"
        fp = _write_file(tmp_path / "img.bin", data)
        assert verify_sha256(Path(fp), _sha256(data)) is True

    def test_accepts_string_path(self, tmp_path):
        data = b"string-path test"
        fp = _write_file(tmp_path / "img.bin", data)
        assert verify_sha256(str(fp), _sha256(data)) is True

    def test_case_insensitive_digest(self, tmp_path):
        data = b"case test"
        fp = _write_file(tmp_path / "img.bin", data)
        digest_upper = _sha256(data).upper()
        assert verify_sha256(fp, digest_upper) is True


# ---------------------------------------------------------------------------
# verify_signature (requires cryptography package)
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_raises_runtime_error_when_cryptography_missing(self, tmp_path):
        """When 'cryptography' is not importable inside the function, RuntimeError is raised."""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name.startswith("cryptography"):
                raise ImportError(f"Mocked: {name} not available")
            return real_import(name, *args, **kwargs)

        from bmt_ai_os.ota.verify import verify_signature

        with patch("builtins.__import__", side_effect=_fake_import):
            with pytest.raises((RuntimeError, ImportError)):
                verify_signature(
                    tmp_path / "img.bin",
                    tmp_path / "img.sig",
                    tmp_path / "pub.key",
                )

    def test_returns_false_when_files_missing(self, tmp_path):
        """When any required file is missing, returns False (not raises)."""
        try:
            from bmt_ai_os.ota.verify import verify_signature
        except ImportError:
            pytest.skip("cryptography not available")

        result = verify_signature(
            tmp_path / "nonexistent.bin",
            tmp_path / "nonexistent.sig",
            tmp_path / "nonexistent.key",
        )
        assert result is False
