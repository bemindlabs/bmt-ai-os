"""Unit tests for bmt_ai_os.tls — certificate generation and TLS config.

Covers:
- generate_self_signed: RSA key, PEM output, SANs, validity, file permissions
- ensure_certs: idempotency (no re-generation), fresh generation, hostname env var
- TLSConfig defaults and field values
- load_tls_config: env-var parsing for all five variables
"""

from __future__ import annotations

import os
import stat

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cert(path: str):
    """Load a PEM certificate from *path* using the cryptography library."""
    from cryptography import x509

    with open(path, "rb") as fh:
        return x509.load_pem_x509_certificate(fh.read())


# ---------------------------------------------------------------------------
# generate_self_signed
# ---------------------------------------------------------------------------


class TestGenerateSelfSigned:
    def test_creates_cert_and_key_files(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="test.local")

        assert cert.exists(), "Certificate file should be created"
        assert key.exists(), "Key file should be created"

    def test_cert_is_valid_pem(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="test.local")

        cert_obj = _load_cert(str(cert))
        assert cert_obj is not None

    def test_common_name_matches_hostname(self, tmp_path):
        from cryptography import x509

        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="my-device.local")

        cert_obj = _load_cert(str(cert))
        cn_attrs = cert_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert cn_attrs[0].value == "my-device.local"

    def test_dns_san_includes_hostname_and_localhost(self, tmp_path):
        from cryptography import x509

        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="edge-node.bmt")

        cert_obj = _load_cert(str(cert))
        san_ext = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san_ext.value.get_values_for_type(x509.DNSName)

        assert "edge-node.bmt" in dns_names
        assert "localhost" in dns_names

    def test_ip_sans_include_loopback(self, tmp_path):
        import ipaddress

        from cryptography import x509

        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="test.local")

        cert_obj = _load_cert(str(cert))
        san_ext = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ip_sans = san_ext.value.get_values_for_type(x509.IPAddress)

        assert ipaddress.IPv4Address("127.0.0.1") in ip_sans
        assert ipaddress.IPv6Address("::1") in ip_sans

    def test_validity_period_respected(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="test.local", days=90)

        cert_obj = _load_cert(str(cert))
        not_before = cert_obj.not_valid_before_utc
        not_after = cert_obj.not_valid_after_utc

        delta = not_after - not_before
        # Allow ±1 day tolerance for sub-second timing.
        assert abs(delta.days - 90) <= 1

    def test_key_file_permissions_are_0600(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key, hostname="test.local")

        mode = stat.S_IMODE(os.stat(key).st_mode)
        assert mode == 0o600, f"Key file permissions should be 0600, got {oct(mode)}"

    def test_overwrites_existing_files(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"

        generate_self_signed(cert, key, hostname="host-a")
        mtime_first = cert.stat().st_mtime

        generate_self_signed(cert, key, hostname="host-b")
        mtime_second = cert.stat().st_mtime

        # Second call must produce a new file (mtime changes) with a new CN.
        from cryptography import x509

        cert_obj = _load_cert(str(cert))
        cn_attrs = cert_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert cn_attrs[0].value == "host-b"

    def test_creates_parent_directories(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        deep_cert = tmp_path / "a" / "b" / "c" / "server.crt"
        deep_key = tmp_path / "a" / "b" / "c" / "server.key"

        generate_self_signed(deep_cert, deep_key, hostname="test.local")

        assert deep_cert.exists()
        assert deep_key.exists()

    def test_default_hostname_is_localhost(self, tmp_path):
        from cryptography import x509

        from bmt_ai_os.tls.certs import generate_self_signed

        cert = tmp_path / "server.crt"
        key = tmp_path / "server.key"
        generate_self_signed(cert, key)  # no hostname argument

        cert_obj = _load_cert(str(cert))
        cn_attrs = cert_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert cn_attrs[0].value == "localhost"


# ---------------------------------------------------------------------------
# ensure_certs
# ---------------------------------------------------------------------------


class TestEnsureCerts:
    def test_generates_certs_in_given_dir(self, tmp_path):
        from bmt_ai_os.tls.certs import ensure_certs

        cert_p, key_p = ensure_certs(cert_dir=tmp_path)

        assert os.path.exists(cert_p)
        assert os.path.exists(key_p)

    def test_returns_absolute_string_paths(self, tmp_path):
        from bmt_ai_os.tls.certs import ensure_certs

        cert_p, key_p = ensure_certs(cert_dir=tmp_path)

        assert os.path.isabs(cert_p)
        assert os.path.isabs(key_p)

    def test_idempotent_does_not_regenerate(self, tmp_path):
        from bmt_ai_os.tls.certs import ensure_certs

        cert_p1, key_p1 = ensure_certs(cert_dir=tmp_path)
        mtime_cert = os.path.getmtime(cert_p1)
        mtime_key = os.path.getmtime(key_p1)

        # Second call should not touch the files.
        cert_p2, key_p2 = ensure_certs(cert_dir=tmp_path)

        assert os.path.getmtime(cert_p2) == mtime_cert
        assert os.path.getmtime(key_p2) == mtime_key

    def test_uses_bmt_tls_hostname_env_var(self, tmp_path, monkeypatch):
        from cryptography import x509

        from bmt_ai_os.tls.certs import ensure_certs

        monkeypatch.setenv("BMT_TLS_HOSTNAME", "custom-device.bmt")
        cert_p, _ = ensure_certs(cert_dir=tmp_path)

        cert_obj = _load_cert(cert_p)
        cn_attrs = cert_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert cn_attrs[0].value == "custom-device.bmt"


# ---------------------------------------------------------------------------
# TLSConfig
# ---------------------------------------------------------------------------


class TestTLSConfig:
    def test_default_disabled(self):
        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig()
        assert cfg.enabled is False

    def test_default_port(self):
        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig()
        assert cfg.port == 8443

    def test_default_redirect_http_false(self):
        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig()
        assert cfg.redirect_http is False

    def test_custom_values(self):
        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig(
            enabled=True,
            cert_path="/etc/tls/cert.pem",
            key_path="/etc/tls/key.pem",
            port=9443,
            redirect_http=True,
        )
        assert cfg.enabled is True
        assert cfg.cert_path == "/etc/tls/cert.pem"
        assert cfg.key_path == "/etc/tls/key.pem"
        assert cfg.port == 9443
        assert cfg.redirect_http is True

    def test_resolved_paths_fall_back_to_set_paths(self):
        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig(cert_path="/a/b/cert.pem", key_path="/a/b/key.pem")
        assert cfg.resolved_cert() == "/a/b/cert.pem"
        assert cfg.resolved_key() == "/a/b/key.pem"

    def test_internal_resolved_overrides_explicit_path(self):
        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig(cert_path="/explicit/cert.pem")
        cfg._resolved_cert = "/generated/cert.pem"
        assert cfg.resolved_cert() == "/generated/cert.pem"


# ---------------------------------------------------------------------------
# load_tls_config
# ---------------------------------------------------------------------------


class TestLoadTLSConfig:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("BMT_TLS_ENABLED", raising=False)
        from bmt_ai_os.tls.config import load_tls_config

        cfg = load_tls_config()
        assert cfg.enabled is False

    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes"])
    def test_enabled_truthy_values(self, monkeypatch, tmp_path, val):
        monkeypatch.setenv("BMT_TLS_ENABLED", val)
        # Provide explicit paths so ensure_certs is not called.
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        # Write dummy PEM files (load_tls_config only checks paths, not content).
        cert.write_text("CERT")
        key.write_text("KEY")
        monkeypatch.setenv("BMT_TLS_CERT", str(cert))
        monkeypatch.setenv("BMT_TLS_KEY", str(key))

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        cfg = _mod.load_tls_config()
        assert cfg.enabled is True

    @pytest.mark.parametrize("val", ["false", "False", "0", "no", ""])
    def test_disabled_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv("BMT_TLS_ENABLED", val)
        monkeypatch.delenv("BMT_TLS_CERT", raising=False)
        monkeypatch.delenv("BMT_TLS_KEY", raising=False)

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        cfg = _mod.load_tls_config()
        assert cfg.enabled is False

    def test_custom_port_from_env(self, monkeypatch):
        monkeypatch.setenv("BMT_TLS_PORT", "9443")
        monkeypatch.delenv("BMT_TLS_ENABLED", raising=False)

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        cfg = _mod.load_tls_config()
        assert cfg.port == 9443

    def test_invalid_port_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BMT_TLS_PORT", "not-a-number")
        monkeypatch.delenv("BMT_TLS_ENABLED", raising=False)

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        cfg = _mod.load_tls_config()
        assert cfg.port == 8443

    def test_explicit_cert_key_paths_respected(self, monkeypatch, tmp_path):
        cert = tmp_path / "c.pem"
        key = tmp_path / "k.pem"
        cert.write_text("CERT")
        key.write_text("KEY")

        monkeypatch.setenv("BMT_TLS_ENABLED", "true")
        monkeypatch.setenv("BMT_TLS_CERT", str(cert))
        monkeypatch.setenv("BMT_TLS_KEY", str(key))

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        cfg = _mod.load_tls_config()
        assert cfg.cert_path == str(cert)
        assert cfg.key_path == str(key)

    def test_redirect_http_from_env(self, monkeypatch):
        monkeypatch.setenv("BMT_TLS_REDIRECT", "true")
        monkeypatch.delenv("BMT_TLS_ENABLED", raising=False)

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        cfg = _mod.load_tls_config()
        assert cfg.redirect_http is True

    def test_auto_generate_certs_when_paths_absent(self, monkeypatch, tmp_path):
        """When TLS is enabled without explicit paths, certs are auto-generated."""
        monkeypatch.setenv("BMT_TLS_ENABLED", "true")
        monkeypatch.delenv("BMT_TLS_CERT", raising=False)
        monkeypatch.delenv("BMT_TLS_KEY", raising=False)
        monkeypatch.setenv("BMT_TLS_HOSTNAME", "auto-gen.bmt")

        # Patch ensure_certs so tests don't write to /data or /tmp in CI.
        expected_cert = str(tmp_path / "server.crt")
        expected_key = str(tmp_path / "server.key")

        import bmt_ai_os.tls.certs as certs_mod

        original_ensure = certs_mod.ensure_certs

        def fake_ensure(cert_dir=None):
            return expected_cert, expected_key

        monkeypatch.setattr(certs_mod, "ensure_certs", fake_ensure)

        from importlib import reload

        import bmt_ai_os.tls.config as _mod

        reload(_mod)
        # Also patch within the reloaded module's namespace.
        monkeypatch.setattr(_mod, "load_tls_config", _mod.load_tls_config)

        cfg = _mod.load_tls_config()
        assert cfg.enabled is True
        assert cfg._resolved_cert == expected_cert
        assert cfg._resolved_key == expected_key
