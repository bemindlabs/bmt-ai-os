"""Unit tests for the OTA update engine.

All tests run offline — no network calls, no block device access, no
fw_printenv/fw_setenv.  State files use tmp_path (pytest fixture).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ===========================================================================
# state.py
# ===========================================================================


class TestOTAState:
    def test_defaults(self):
        from bmt_ai_os.ota.state import OTAState

        s = OTAState()
        assert s.current_slot == "a"
        assert s.standby_slot == "b"
        assert s.last_update is None
        assert s.bootcount == 0
        assert s.confirmed is True

    def test_round_trip(self):
        from bmt_ai_os.ota.state import OTAState

        s = OTAState(current_slot="b", standby_slot="a", bootcount=3, confirmed=False)
        restored = OTAState.from_dict(s.to_dict())
        assert restored.current_slot == "b"
        assert restored.standby_slot == "a"
        assert restored.bootcount == 3
        assert restored.confirmed is False

    def test_from_dict_missing_fields_uses_defaults(self):
        from bmt_ai_os.ota.state import OTAState

        s = OTAState.from_dict({})
        assert s.current_slot == "a"
        assert s.bootcount == 0


class TestStateManager:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "nonexistent.json")
        s = sm.load()
        assert s.current_slot == "a"

    def test_save_and_load_round_trip(self, tmp_path):
        from bmt_ai_os.ota.state import OTAState, StateManager

        sm = StateManager(path=tmp_path / "ota-state.json")
        original = OTAState(current_slot="b", standby_slot="a", bootcount=2, confirmed=False)
        sm.save(original)

        loaded = sm.load()
        assert loaded.current_slot == "b"
        assert loaded.bootcount == 2
        assert loaded.confirmed is False

    def test_save_creates_parent_dirs(self, tmp_path):
        from bmt_ai_os.ota.state import OTAState, StateManager

        deep = tmp_path / "a" / "b" / "c" / "state.json"
        sm = StateManager(path=deep)
        sm.save(OTAState())
        assert deep.exists()

    def test_load_corrupted_file_returns_defaults(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        p = tmp_path / "bad.json"
        p.write_text("{not valid json{{{")
        sm = StateManager(path=p)
        s = sm.load()
        assert s.current_slot == "a"

    def test_increment_bootcount(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        s = sm.increment_bootcount()
        assert s.bootcount == 1
        assert s.confirmed is False
        s2 = sm.increment_bootcount()
        assert s2.bootcount == 2

    def test_confirm_resets_bootcount(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        sm.increment_bootcount()
        sm.increment_bootcount()
        s = sm.confirm()
        assert s.bootcount == 0
        assert s.confirmed is True

    def test_switch_slots(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        s = sm.switch_slots()
        # default current=a → after switch current=b
        assert s.current_slot == "b"
        assert s.standby_slot == "a"
        assert s.confirmed is False
        assert s.last_update is not None

    def test_set_last_update_uses_now_by_default(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        s = sm.set_last_update()
        assert s.last_update is not None
        assert "T" in s.last_update  # ISO-8601 shape

    def test_set_last_update_explicit(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        s = sm.set_last_update("2026-01-01T00:00:00+00:00")
        assert s.last_update == "2026-01-01T00:00:00+00:00"

    def test_atomic_write_no_tmp_left_on_disk(self, tmp_path):
        from bmt_ai_os.ota.state import OTAState, StateManager

        p = tmp_path / "state.json"
        sm = StateManager(path=p)
        sm.save(OTAState())
        tmp_file = p.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_env_override(self, tmp_path, monkeypatch):
        from bmt_ai_os.ota.state import _state_path

        monkeypatch.setenv("BMT_OTA_STATE_PATH", str(tmp_path / "env.json"))
        p = _state_path()
        assert str(p).endswith("env.json")


# ===========================================================================
# verify.py
# ===========================================================================


class TestVerifySha256:
    def test_correct_digest(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_sha256

        data = b"hello world"
        p = _write_file(tmp_path / "f.bin", data)
        assert verify_sha256(p, _sha256(data)) is True

    def test_wrong_digest(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_sha256

        p = _write_file(tmp_path / "f.bin", b"hello world")
        assert verify_sha256(p, "0" * 64) is False

    def test_missing_file(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_sha256

        assert verify_sha256(tmp_path / "missing.bin", "a" * 64) is False

    def test_uppercase_digest_accepted(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_sha256

        data = b"BMT AI OS"
        p = _write_file(tmp_path / "f.bin", data)
        assert verify_sha256(p, _sha256(data).upper()) is True

    def test_empty_file(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_sha256

        p = _write_file(tmp_path / "empty.bin", b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert verify_sha256(p, expected) is True

    def test_large_file(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_sha256

        # 200 KiB — exercises the chunked read path
        data = bytes(range(256)) * 800
        p = _write_file(tmp_path / "big.bin", data)
        assert verify_sha256(p, _sha256(data)) is True


class TestVerifySignature:
    def test_raises_when_cryptography_missing(self, tmp_path):
        from bmt_ai_os.ota.verify import verify_signature

        # Simulate ImportError inside verify_signature by patching the nested import.
        with patch(
            "bmt_ai_os.ota.verify.verify_signature",
            side_effect=None,
        ):
            pass  # just a structural placeholder

        # Real test: make the internal 'from cryptography...' raise ImportError.
        import builtins

        real_import = builtins.__import__

        def _block_cryptography(name, *args, **kwargs):
            if name.startswith("cryptography"):
                raise ImportError("no module named cryptography")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_cryptography):
            with pytest.raises(RuntimeError, match="cryptography"):
                verify_signature(
                    tmp_path / "img",
                    tmp_path / "sig",
                    tmp_path / "pub",
                )

    def test_missing_file_returns_false(self, tmp_path):
        """When cryptography IS available but files are missing → False."""
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_signature

        assert verify_signature(tmp_path / "img", tmp_path / "sig", tmp_path / "pub") is False

    def test_invalid_signature_returns_false(self, tmp_path):
        """Real key pair; wrong signature bytes → False."""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_signature

        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        pub_bytes = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

        image_data = b"OS image content"
        img_path = _write_file(tmp_path / "img.bin", image_data)
        sig_path = _write_file(tmp_path / "img.sig", b"\x00" * 64)  # garbage sig
        pub_path = _write_file(tmp_path / "pub.key", pub_bytes)

        assert verify_signature(img_path, sig_path, pub_path) is False

    def test_valid_signature_returns_true(self, tmp_path):
        """Real key pair; correct signature → True."""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_signature

        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        pub_bytes = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

        image_data = b"legitimate OS image"
        digest = hashlib.sha256(image_data).digest()
        sig_bytes = priv.sign(digest)

        img_path = _write_file(tmp_path / "img.bin", image_data)
        sig_path = _write_file(tmp_path / "img.sig", sig_bytes)
        pub_path = _write_file(tmp_path / "pub.key", pub_bytes)

        assert verify_signature(img_path, sig_path, pub_path) is True


# ===========================================================================
# verify_download (BMTOS-68)
# ===========================================================================


class TestVerifyDownload:
    """Tests for the high-level verify_download() convenience wrapper."""

    def _make_keypair(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            return None, None, None

        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        pub_bytes = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return priv, pub_bytes, None

    def test_valid_signature_returns_true(self, tmp_path):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_download

        priv, pub_bytes, _ = self._make_keypair()
        image_data = b"production OTA image bytes"
        digest = hashlib.sha256(image_data).digest()
        sig_bytes = priv.sign(digest)

        img_path = _write_file(tmp_path / "update.img", image_data)
        sig_path = _write_file(tmp_path / "update.img.sig", sig_bytes)
        pub_path = _write_file(tmp_path / "signing-key.pub", pub_bytes)

        result = verify_download(img_path, sig_path=sig_path, pubkey_path=pub_path)
        assert result is True

    def test_default_sig_path_is_image_plus_sig(self, tmp_path):
        """When sig_path is None, defaults to <image>.sig."""
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_download

        priv, pub_bytes, _ = self._make_keypair()
        image_data = b"another image"
        digest = hashlib.sha256(image_data).digest()
        sig_bytes = priv.sign(digest)

        img_path = _write_file(tmp_path / "bmt.img", image_data)
        # sig file at default path: bmt.img.sig
        _write_file(tmp_path / "bmt.img.sig", sig_bytes)
        pub_path = _write_file(tmp_path / "signing-key.pub", pub_bytes)

        result = verify_download(img_path, pubkey_path=pub_path)
        assert result is True

    def test_env_var_overrides_pubkey_path(self, tmp_path, monkeypatch):
        """BMT_OTA_PUBKEY_PATH env var is honoured when pubkey_path is None."""
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_download

        priv, pub_bytes, _ = self._make_keypair()
        image_data = b"env var image"
        digest = hashlib.sha256(image_data).digest()
        sig_bytes = priv.sign(digest)

        pub_path = _write_file(tmp_path / "env-key.pub", pub_bytes)
        monkeypatch.setenv("BMT_OTA_PUBKEY_PATH", str(pub_path))

        img_path = _write_file(tmp_path / "bmt.img", image_data)
        sig_path = _write_file(tmp_path / "bmt.img.sig", sig_bytes)

        result = verify_download(img_path, sig_path=sig_path)
        assert result is True

    def test_missing_sig_file_returns_false(self, tmp_path):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_download

        _, pub_bytes, _ = self._make_keypair()
        img_path = _write_file(tmp_path / "update.img", b"data")
        pub_path = _write_file(tmp_path / "signing-key.pub", pub_bytes)

        result = verify_download(img_path, sig_path=tmp_path / "missing.sig", pubkey_path=pub_path)
        assert result is False

    def test_bad_signature_returns_false(self, tmp_path):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")

        from bmt_ai_os.ota.verify import verify_download

        _, pub_bytes, _ = self._make_keypair()
        img_path = _write_file(tmp_path / "update.img", b"data")
        sig_path = _write_file(tmp_path / "update.img.sig", b"\x00" * 64)
        pub_path = _write_file(tmp_path / "signing-key.pub", pub_bytes)

        result = verify_download(img_path, sig_path=sig_path, pubkey_path=pub_path)
        assert result is False


# ===========================================================================
# engine.py
# ===========================================================================


class TestCheckUpdate:
    def _mock_urlopen(self, payload: dict):
        """Return a context manager mock that delivers *payload* as JSON."""
        body = json.dumps(payload).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.headers = {"Content-Length": str(len(body))}
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_update_info_when_server_responds(self):
        from bmt_ai_os.ota.engine import check_update

        payload = {
            "version": "2026.5.1",
            "url": "https://example.com/bmt.img",
            "sha256": "abc" * 21 + "a",  # 64 chars
            "release_notes": "fixes",
            "size_bytes": 500_000_000,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(payload)):
            info = check_update("https://example.com/latest.json")

        assert info is not None
        assert info.version == "2026.5.1"
        assert info.url == "https://example.com/bmt.img"
        assert info.size_bytes == 500_000_000

    def test_returns_none_when_already_up_to_date(self):
        from bmt_ai_os.ota.engine import check_update

        payload = {
            "version": "2026.4.10",  # same as __version__
            "url": "https://example.com/bmt.img",
            "sha256": "a" * 64,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(payload)):
            info = check_update("https://example.com/latest.json", current_version="2026.4.10")

        assert info is None

    def test_returns_none_on_network_error(self):
        import urllib.error

        from bmt_ai_os.ota.engine import check_update

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("unreachable"),
        ):
            info = check_update("https://example.com/latest.json")

        assert info is None

    def test_returns_none_on_invalid_json(self):
        from bmt_ai_os.ota.engine import check_update

        resp = MagicMock()
        resp.read.return_value = b"<html>not json</html>"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=resp):
            info = check_update("https://example.com/latest.json")

        assert info is None

    def test_returns_none_when_required_field_missing(self):
        from bmt_ai_os.ota.engine import check_update

        payload = {"version": "2026.5.1"}  # missing url + sha256
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=resp):
            info = check_update("https://example.com/latest.json")

        assert info is None

    @pytest.mark.parametrize(
        "candidate,current,expected",
        [
            ("2026.5.0", "2026.4.10", True),
            ("2026.4.10", "2026.4.10", False),
            ("2025.12.31", "2026.1.1", False),
            ("2026.4.11", "2026.4.10", True),
        ],
    )
    def test_is_newer(self, candidate, current, expected):
        from bmt_ai_os.ota.engine import _is_newer

        assert _is_newer(candidate, current) is expected


class TestDownloadImage:
    def _mock_urlopen(self, data: bytes):
        resp = MagicMock()
        resp.headers = {"Content-Length": str(len(data))}
        resp.read.side_effect = [data, b""]  # one chunk + EOF
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_successful_download_and_verify(self, tmp_path):
        from bmt_ai_os.ota.engine import download_image

        data = b"fake OS image data"
        digest = _sha256(data)
        dest = tmp_path / "update.img"

        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(data)):
            result = download_image("https://example.com/img", dest, digest)

        assert result is True
        assert dest.exists()
        assert dest.read_bytes() == data

    def test_wrong_checksum_deletes_file(self, tmp_path):
        from bmt_ai_os.ota.engine import download_image

        data = b"fake OS image data"
        dest = tmp_path / "update.img"

        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(data)):
            result = download_image("https://example.com/img", dest, "0" * 64)

        assert result is False
        assert not dest.exists()

    def test_network_error_returns_false(self, tmp_path):
        import urllib.error

        from bmt_ai_os.ota.engine import download_image

        dest = tmp_path / "update.img"
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ):
            result = download_image("https://example.com/img", dest, "a" * 64)

        assert result is False
        assert not dest.exists()

    def test_progress_callback_is_called(self, tmp_path):
        from bmt_ai_os.ota.engine import download_image

        data = b"x" * 200_000
        digest = _sha256(data)
        dest = tmp_path / "update.img"
        calls: list[tuple[int, int]] = []

        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(data)):
            download_image(
                "https://example.com/img",
                dest,
                digest,
                progress_cb=lambda r, t: calls.append((r, t)),
            )

        assert len(calls) >= 1
        # Final call should show all bytes received.
        assert calls[-1][0] == len(data)

    def test_creates_parent_directories(self, tmp_path):
        from bmt_ai_os.ota.engine import download_image

        data = b"data"
        digest = _sha256(data)
        dest = tmp_path / "deep" / "dir" / "update.img"

        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(data)):
            result = download_image("https://example.com/img", dest, digest)

        assert result is True
        assert dest.exists()


class TestApplyUpdate:
    def test_file_backed_write_switches_slot(self, tmp_path, monkeypatch):
        from bmt_ai_os.ota.engine import apply_update
        from bmt_ai_os.ota.state import StateManager

        monkeypatch.setenv("BMT_OTA_SLOT_DIR", str(tmp_path / "slots"))
        sm = StateManager(path=tmp_path / "state.json")

        image_data = b"OS image payload"
        img = tmp_path / "image.img"
        img.write_bytes(image_data)

        result = apply_update(img, "b", dry_run=True, state_manager=sm)
        assert result is True

        # Slot file was written
        slot_file = tmp_path / "slots" / "b.img"
        assert slot_file.exists()
        assert slot_file.read_bytes() == image_data

        # State was switched
        state = sm.load()
        assert state.current_slot == "b"
        assert state.standby_slot == "a"

    def test_invalid_slot_returns_false(self, tmp_path):
        from bmt_ai_os.ota.engine import apply_update
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        img = tmp_path / "image.img"
        img.write_bytes(b"data")

        assert apply_update(img, "c", dry_run=True, state_manager=sm) is False

    def test_missing_image_returns_false(self, tmp_path):
        from bmt_ai_os.ota.engine import apply_update
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        assert (
            apply_update(tmp_path / "nonexistent.img", "b", dry_run=True, state_manager=sm) is False
        )

    def test_file_backed_readback_detects_corruption(self, tmp_path, monkeypatch):
        """Simulate a silent write corruption by monkeypatching shutil.copy2."""
        from bmt_ai_os.ota.engine import apply_update
        from bmt_ai_os.ota.state import StateManager

        monkeypatch.setenv("BMT_OTA_SLOT_DIR", str(tmp_path / "slots"))
        sm = StateManager(path=tmp_path / "state.json")

        img = tmp_path / "image.img"
        img.write_bytes(b"original data")

        def _corrupt_copy(src, dst, *a, **kw):
            # Write different bytes to simulate storage corruption.
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_bytes(b"corrupted!!!")

        with patch("shutil.copy2", side_effect=_corrupt_copy):
            result = apply_update(img, "b", dry_run=True, state_manager=sm)

        assert result is False


class TestConfirmBoot:
    def test_confirm_resets_bootcount_and_sets_confirmed(self, tmp_path):
        from bmt_ai_os.ota.engine import confirm_boot
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        sm.increment_bootcount()
        sm.increment_bootcount()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            confirm_boot(state_manager=sm)

        state = sm.load()
        assert state.confirmed is True
        assert state.bootcount == 0

    def test_confirm_calls_fw_setenv(self, tmp_path):
        from bmt_ai_os.ota.engine import confirm_boot
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=tmp_path / "state.json")
        calls = []

        def _mock_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            confirm_boot(state_manager=sm)

        # Should have called fw_setenv bootcount 0  and  fw_setenv upgrade_available 0
        cmds = [" ".join(c) for c in calls if c[0] == "fw_setenv"]
        assert any("bootcount" in c for c in cmds)
        assert any("upgrade_available" in c for c in cmds)


class TestGetCurrentSlot:
    def test_reads_from_state_file_when_no_uboot(self, tmp_path, monkeypatch):
        from bmt_ai_os.ota.engine import get_current_slot
        from bmt_ai_os.ota.state import OTAState, StateManager

        sm = StateManager(path=tmp_path / "state.json")
        sm.save(OTAState(current_slot="b"))

        # fw_printenv not available
        with patch("subprocess.run", side_effect=FileNotFoundError):
            slot = get_current_slot(sm)

        assert slot == "b"

    def test_env_variable_overrides_state_file(self, tmp_path, monkeypatch):
        from bmt_ai_os.ota.engine import get_current_slot
        from bmt_ai_os.ota.state import OTAState, StateManager

        monkeypatch.setenv("BMT_OTA_CURRENT_SLOT", "b")
        sm = StateManager(path=tmp_path / "state.json")
        sm.save(OTAState(current_slot="a"))

        with patch("subprocess.run", side_effect=FileNotFoundError):
            slot = get_current_slot(sm)

        assert slot == "b"

    def test_uboot_env_wins_over_state_file(self, tmp_path, monkeypatch):
        from bmt_ai_os.ota.engine import get_current_slot
        from bmt_ai_os.ota.state import OTAState, StateManager

        monkeypatch.delenv("BMT_OTA_CURRENT_SLOT", raising=False)
        sm = StateManager(path=tmp_path / "state.json")
        sm.save(OTAState(current_slot="a"))

        mock_result = MagicMock(returncode=0, stdout="slot_name=b\n")
        with patch("subprocess.run", return_value=mock_result):
            slot = get_current_slot(sm)

        assert slot == "b"

    def test_defaults_to_a_with_no_config(self, tmp_path, monkeypatch):
        from bmt_ai_os.ota.engine import get_current_slot
        from bmt_ai_os.ota.state import StateManager

        monkeypatch.delenv("BMT_OTA_CURRENT_SLOT", raising=False)
        # State file doesn't exist
        sm = StateManager(path=tmp_path / "nonexistent.json")

        with patch("subprocess.run", side_effect=FileNotFoundError):
            slot = get_current_slot(sm)

        assert slot == "a"


# ===========================================================================
# CLI integration (click CliRunner)
# ===========================================================================


class TestCLIUpdateCommands:
    @pytest.fixture()
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture()
    def state_file(self, tmp_path):
        return str(tmp_path / "ota-state.json")

    def test_status_shows_default_state(self, runner, state_file):
        from bmt_ai_os.cli import main

        result = runner.invoke(main, ["update", "status", "--state-file", state_file])
        assert result.exit_code == 0
        assert "Current slot" in result.output
        assert "Standby slot" in result.output

    def test_confirm_marks_slot_confirmed(self, runner, state_file, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        sm = StateManager(path=state_file)
        sm.increment_bootcount()  # simulate unconfirmed boot

        from bmt_ai_os.cli import main

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(main, ["update", "confirm", "--state-file", state_file])

        assert result.exit_code == 0
        assert "confirmed" in result.output.lower()

        state = sm.load()
        assert state.confirmed is True
        assert state.bootcount == 0

    def test_check_no_update(self, runner, state_file):
        import urllib.error

        from bmt_ai_os.cli import main

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("unreachable"),
            ):
                result = runner.invoke(
                    main,
                    ["update", "check", "--server", "https://example.com/latest.json"],
                )

        assert result.exit_code == 0
        assert "No update available" in result.output

    def test_status_shows_state_file_path(self, runner, state_file):
        from bmt_ai_os.cli import main

        result = runner.invoke(main, ["update", "status", "--state-file", state_file])
        assert result.exit_code == 0
        assert state_file in result.output
