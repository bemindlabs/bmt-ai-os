"""TLS configuration dataclass for BMT AI OS.

TLS is opt-in: set BMT_TLS_ENABLED=true to activate.  The default mode
is plain HTTP, which is correct for air-gapped, local-only deployments.

Environment variables
---------------------
BMT_TLS_ENABLED   : "true" / "1" / "yes" to enable (default: disabled)
BMT_TLS_CERT      : Path to PEM certificate (auto-generated when absent)
BMT_TLS_KEY       : Path to PEM private key  (auto-generated when absent)
BMT_TLS_PORT      : HTTPS listen port        (default: 8443)
BMT_TLS_REDIRECT  : "true" to redirect HTTP→HTTPS (default: false)
"""

import os
from dataclasses import dataclass, field

_DEFAULT_TLS_PORT = 8443


@dataclass
class TLSConfig:
    """TLS settings for the BMT AI OS controller API.

    Attributes:
        enabled:       Whether TLS is active.  Always False by default.
        cert_path:     Path to the PEM-encoded server certificate.
                       Empty string means "auto-generate".
        key_path:      Path to the PEM-encoded server private key.
                       Empty string means "auto-generate".
        port:          HTTPS listen port (default 8443).
        redirect_http: When True the HTTP server (api_port) redirects
                       all requests to the HTTPS port.  Only meaningful
                       when ``enabled`` is True.
    """

    enabled: bool = False
    cert_path: str = ""
    key_path: str = ""
    port: int = _DEFAULT_TLS_PORT
    redirect_http: bool = False

    # Resolved at runtime by ensure_certs(); populated in load_tls_config().
    _resolved_cert: str = field(default="", repr=False, compare=False)
    _resolved_key: str = field(default="", repr=False, compare=False)

    def resolved_cert(self) -> str:
        """Return the effective certificate path (may differ from cert_path)."""
        return self._resolved_cert or self.cert_path

    def resolved_key(self) -> str:
        """Return the effective key path (may differ from key_path)."""
        return self._resolved_key or self.key_path


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

    cfg = TLSConfig(
        enabled=enabled,
        cert_path=cert_path,
        key_path=key_path,
        port=port,
        redirect_http=redirect_http,
    )

    if enabled and (not cert_path or not key_path):
        # Auto-generate missing certificates.
        from .certs import ensure_certs

        resolved_cert, resolved_key = ensure_certs()
        cfg._resolved_cert = resolved_cert
        cfg._resolved_key = resolved_key

    return cfg
