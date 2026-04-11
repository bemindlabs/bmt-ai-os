"""Unit tests for bmt_ai_os.ota.verify.

Tests SHA-256 verification and constant-time equality.
Ed25519 tests require the 'cryptography' package (skipped if absent).
"""

from __future__ import annotations

import hashlib

from bmt_ai_os.ota.verify import _CHUNK_SIZE, _ct_equal, verify_sha256

# ---------------------------------------------------------------------------
# _ct_equal
# ---------------------------------------------------------------------------


class TestCtEqual:
    def test_equal_strings(self):
        assert _ct_equal("abc", "abc") is True

    def test_different_strings(self):
        assert _ct_equal("abc", "def") is False

    def test_different_lengths(self):
        assert _ct_equal("abc", "ab") is False
        assert _ct_equal("ab", "abc") is False

    def test_empty_strings(self):
        assert _ct_equal("", "") is True

    def test_hex_digests_equal(self):
        h = hashlib.sha256(b"hello").hexdigest()
        assert _ct_equal(h, h) is True

    def test_hex_digests_different(self):
        h1 = hashlib.sha256(b"hello").hexdigest()
        h2 = hashlib.sha256(b"world").hexdigest()
        assert _ct_equal(h1, h2) is False

    def test_case_insensitive_not_supported(self):
        # _ct_equal is byte-level — "ABC" != "abc"
        assert _ct_equal("ABC", "abc") is False

    def test_single_char_difference(self):
        assert _ct_equal("aaaa", "aaab") is False


# ---------------------------------------------------------------------------
# verify_sha256
# ---------------------------------------------------------------------------


class TestVerifySha256:
    def test_correct_hash_returns_true(self, tmp_path):
        f = tmp_path / "test.bin"
        content = b"Hello, BMT AI OS!"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert verify_sha256(f, expected) is True

    def test_wrong_hash_returns_false(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"content")
        wrong_hash = "a" * 64
        assert verify_sha256(f, wrong_hash) is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        assert verify_sha256(tmp_path / "nonexistent.img", "a" * 64) is False

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert verify_sha256(f, expected) is True

    def test_case_insensitive_comparison(self, tmp_path):
        f = tmp_path / "data.bin"
        content = b"test data"
        f.write_bytes(content)
        expected_lower = hashlib.sha256(content).hexdigest()
        expected_upper = expected_lower.upper()
        assert verify_sha256(f, expected_upper) is True

    def test_large_file(self, tmp_path):
        f = tmp_path / "large.bin"
        # Write 2 chunks worth of data (> 64KiB)
        content = b"x" * (_CHUNK_SIZE * 2 + 100)
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert verify_sha256(f, expected) is True

    def test_binary_content(self, tmp_path):
        f = tmp_path / "binary.img"
        content = bytes(range(256)) * 100
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert verify_sha256(f, expected) is True

    def test_accepts_string_path(self, tmp_path):
        f = tmp_path / "file.bin"
        content = b"test"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert verify_sha256(str(f), expected) is True

    def test_modified_file_fails(self, tmp_path):
        f = tmp_path / "file.bin"
        content = b"original content"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        # Modify file after computing expected hash
        f.write_bytes(b"modified content")
        assert verify_sha256(f, expected) is False

    def test_directory_returns_false(self, tmp_path):
        assert verify_sha256(tmp_path, "a" * 64) is False

    def test_hash_length_mismatch_returns_false(self, tmp_path):
        f = tmp_path / "f.bin"
        f.write_bytes(b"data")
        # Wrong-length hash (not 64 chars)
        assert verify_sha256(f, "abc") is False


# ---------------------------------------------------------------------------
# _CHUNK_SIZE
# ---------------------------------------------------------------------------


class TestChunkSize:
    def test_chunk_size_is_power_of_two(self):
        assert _CHUNK_SIZE > 0
        assert (_CHUNK_SIZE & (_CHUNK_SIZE - 1)) == 0

    def test_chunk_size_at_least_4k(self):
        assert _CHUNK_SIZE >= 4096
