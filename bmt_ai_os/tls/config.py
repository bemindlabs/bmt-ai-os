"""TLS configuration dataclass for BMT AI OS.

TLS is opt-in: set BMT_TLS_ENABLED=true to activate.  The default mode
is plain HTTP, which is correct for air-gapped, local-only deployments.

Environment variables
---------------------
BMT_TLS_ENABLED    : "true" / "1" / "yes" to enable (default: disabled)
BMT_TLS_CERT       : Path to PEM certificate (auto-generated when absent)
BMT_TLS_KEY        : Path to PEM private key  (auto-generated when absent)
BMT_TLS_PORT       : HTTPS listen port        (default: 8443)
BMT_TLS_REDIRECT   : "true" to redirect HTTP→HTTPS (default: false)
BMT_TLS_MTLS       : "true" to enable mutual TLS for inter-service traffic
BMT_TLS_CA_CERT    : Path to CA certificate for mTLS client verification
BMT_TLS_RENEW_DAYS : Days before expiry that triggers auto-renewal (default: 30)
"""

import os
import ssl
from dataclasses import dataclass, field

_DEFAULT_TLS_PORT = 8443

# TLS 1.2+ cipher suites — weak ciphers (RC4, DES, 3DES, NULL, EXPORT, anon)
# and non-PFS suites are excluded.  The list follows Mozilla's "Intermediate"
# compatibility profile adapted for Python's ssl module cipher string syntax.
_SECURE_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:"
    "ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-CHACHA20-POLY1305:"
    "DHE-RSA-AES128-GCM-SHA256:"
    "DHE-RSA-AES256-GCM-SHA384:"
    "DHE-RSA-CHACHA20-POLY1305"
)


@dataclass
class TLSConfig:
    """TLS settings for the BMT AI OS controller API.

    Attributes:
        enabled:           Whether TLS is active.  Always False by default.
        cert_path:         Path to the PEM-encoded server certificate.
                           Empty string means "auto-generate".
        key_path:          Path to the PEM-encoded server private key.
                           Empty string means "auto-generate".
        port:              HTTPS listen port (default 8443).
        redirect_http:     When True the HTTP server (api_port) redirects
                           all requests to the HTTPS port.  Only meaningful
                           when ``enabled`` is True.
        mtls_enabled:      When True, require client certificates for
                           inter-service (mTLS) connections.
        ca_cert_path:      Path to the CA certificate used to verify client
                           certs in mTLS mode.  Empty string disables client
                           cert verification even when ``mtls_enabled`` is True.
        ciphers:           OpenSSL cipher string to restrict cipher suites.
                           Defaults to :data:`_SECURE_CIPHERS`.
    """

    enabled: bool = False
    cert_path: str = ""
    key_path: str = ""
    port: int = _DEFAULT_TLS_PORT
    redirect_http: bool = False
    mtls_enabled: bool = False
    ca_cert_path: str = ""
    ciphers: str = _SECURE_CIPHERS

    # Resolved at runtime by ensure_certs(); populated in load_tls_config().
    _resolved_cert: str = field(default="", repr=False, compare=False)
    _resolved_key: str = field(default="", repr=False, compare=False)

    def resolved_cert(self) -> str:
        """Return the effective certificate path (may differ from cert_path)."""
        return self._resolved_cert or self.cert_path

    def resolved_key(self) -> str:
        """Return the effective key path (may differ from key_path)."""
        return self._resolved_key or self.key_path

    def build_ssl_context(self) -> ssl.SSLContext:
        """Build a hardened :class:`ssl.SSLContext` from this configuration.

        Enforces TLS 1.2 minimum, applies the restricted cipher list, and
        (when mTLS is enabled) configures client certificate verification.

        Returns:
            A configured :class:`ssl.SSLContext` ready for use with uvicorn.

        Raises:
            ValueError:  When TLS is not enabled.
            ssl.SSLError: When the certificate/key cannot be loaded.
            OSError:     When cert/key files are unreadable.
        """
        if not self.enabled:
            raise ValueError("Cannot build SSL context: TLS is not enabled")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers(self.ciphers)

        # Disable insecure TLS options
        # minimum_version = TLSv1_2 is the primary enforcement mechanism.
        # OP_NO_COMPRESSION is always valid and prevents CRIME-class attacks.
        ctx.options |= ssl.OP_NO_COMPRESSION
        ctx.options |= ssl.OP_SINGLE_DH_USE
        ctx.options |= ssl.OP_SINGLE_ECDH_USE

        cert = self.resolved_cert()
        key = self.resolved_key()
        ctx.load_cert_chain(certfile=cert, keyfile=key)

        if self.mtls_enabled and self.ca_cert_path:
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(cafile=self.ca_cert_path)

        return ctx


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def load_tls_config() -> TLSConfig:
    """Build a :class:`TLSConfig` from environment variables.

    When TLS is enabled and no explicit cert/key paths are provided the
    certificates are auto-generated via :func:`~bmt_ai_os.tls.certs.ensure_certs`.

    Returns:
        A fully populated :class:`TLSConfig` instance.
    """
    enabled_raw = os.environ.get("BMT_TLS_ENABLED", "false")
    enabled = _parse_bool(enabled_raw)

    cert_path = os.environ.get("BMT_TLS_CERT", "")
    key_path = os.environ.get("BMT_TLS_KEY", "")

    port_raw = os.environ.get("BMT_TLS_PORT", str(_DEFAULT_TLS_PORT))
    try:
        port = int(port_raw)
    except ValueError:
        port = _DEFAULT_TLS_PORT

    redirect_raw = os.environ.get("BMT_TLS_REDIRECT", "false")
    redirect_http = _parse_bool(redirect_raw)

    mtls_enabled = _parse_bool(os.environ.get("BMT_TLS_MTLS", "false"))
    ca_cert_path = os.environ.get("BMT_TLS_CA_CERT", "")

    cfg = TLSConfig(
        enabled=enabled,
        cert_path=cert_path,
        key_path=key_path,
        port=port,
        redirect_http=redirect_http,
        mtls_enabled=mtls_enabled,
        ca_cert_path=ca_cert_path,
    )

    if enabled and (not cert_path or not key_path):
        # Auto-generate missing certificates.
        from .certs import ensure_certs

        resolved_cert, resolved_key = ensure_certs()
        cfg._resolved_cert = resolved_cert
        cfg._resolved_key = resolved_key

    return cfg
