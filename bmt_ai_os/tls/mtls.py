"""Mutual TLS (mTLS) support for inter-service communication in BMT AI OS.

Provides a CA, server, and per-service client certificate infrastructure for
securing traffic between Controller, Ollama, and ChromaDB on the
172.30.0.0/16 bmt-ai-net bridge network.

Directory layout (under the TLS base dir):
    ca/
        ca.crt   — CA certificate (self-signed, shared trust anchor)
        ca.key   — CA private key (0600)
    server/
        server.crt   — Server certificate (signed by CA)
        server.key   — Server private key (0600)
    clients/
        <service_name>.crt
        <service_name>.key

Environment variables
---------------------
BMT_TLS_MTLS_DIR  : Base directory for mTLS certificates
                    (default: /data/secrets/mtls, fallback /tmp/bmt-mtls)
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import os
from pathlib import Path

logger = logging.getLogger("bmt-tls.mtls")

_PROD_MTLS_DIR = Path("/data/secrets/mtls")
_DEV_MTLS_DIR = Path("/tmp/bmt-mtls")

# Services that receive client certificates for mTLS
_BMT_SERVICES = ("controller", "ollama", "chromadb")


def _mtls_base_dir() -> Path:
    """Return the mTLS certificate base directory with prod/dev fallback."""
    env_dir = os.environ.get("BMT_TLS_MTLS_DIR")
    if env_dir:
        return Path(env_dir)
    try:
        _PROD_MTLS_DIR.mkdir(parents=True, exist_ok=True)
        probe = _PROD_MTLS_DIR / ".write_probe"
        probe.touch()
        probe.unlink()
        return _PROD_MTLS_DIR
    except OSError:
        logger.debug("Cannot write to %s, using dev fallback %s", _PROD_MTLS_DIR, _DEV_MTLS_DIR)
        return _DEV_MTLS_DIR


def _write_pem(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def generate_ca(
    ca_dir: Path, cn: str = "BMT AI OS Internal CA", days: int = 3650
) -> tuple[Path, Path]:
    """Generate a self-signed CA certificate and key for internal mTLS.

    Args:
        ca_dir: Directory to write ``ca.crt`` and ``ca.key``.
        cn:     Common Name for the CA certificate.
        days:   Validity period in days (default: 10 years).

    Returns:
        ``(ca_cert_path, ca_key_path)`` as :class:`Path` objects.

    Raises:
        ImportError: When the ``cryptography`` package is unavailable.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise ImportError(
            "The 'cryptography' package is required for mTLS support. "
            "Install it with: pip install 'cryptography>=43.0'"
        ) from exc

    ca_cert_path = ca_dir / "ca.crt"
    ca_key_path = ca_dir / "ca.key"

    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BMT AI OS"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Internal CA"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    _write_pem(ca_key_path, key_pem, mode=0o600)
    _write_pem(ca_cert_path, cert.public_bytes(serialization.Encoding.PEM))

    logger.info("Generated mTLS CA: CN=%s, valid %d days, path=%s", cn, days, ca_cert_path)
    return ca_cert_path, ca_key_path


def _sign_certificate(
    ca_cert_path: Path,
    ca_key_path: Path,
    cn: str,
    days: int,
    *,
    is_server: bool,
    extra_sans: list[str] | None = None,
) -> tuple[bytes, bytes]:
    """Internal helper: sign a certificate with the given CA."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    with open(ca_cert_path, "rb") as fh:
        ca_cert = x509.load_pem_x509_certificate(fh.read())
    with open(ca_key_path, "rb") as fh:
        ca_key = serialization.load_pem_private_key(fh.read(), password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)

    subject = x509.Name(
        [
            x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, cn),
            x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, "BMT AI OS"),
        ]
    )

    san_entries: list[x509.GeneralName] = [
        x509.DNSName(cn),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    for san in extra_sans or []:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(san)))
        except ValueError:
            san_entries.append(x509.DNSName(san))

    eku = (
        x509.oid.ExtendedKeyUsageOID.SERVER_AUTH
        if is_server
        else x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=is_server,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return cert_pem, key_pem


def generate_service_cert(
    service_name: str,
    ca_cert_path: Path,
    ca_key_path: Path,
    out_dir: Path,
    days: int = 365,
    extra_sans: list[str] | None = None,
) -> tuple[Path, Path]:
    """Generate a client certificate for *service_name* signed by the CA.

    The certificate is suitable for mTLS client authentication when
    connecting to another BMT AI OS service.

    Args:
        service_name:  Logical service name (used as CN and file basename).
        ca_cert_path:  Path to the CA certificate.
        ca_key_path:   Path to the CA private key.
        out_dir:       Directory to write the service cert and key.
        days:          Certificate validity period in days.
        extra_sans:    Additional SAN entries (IPs or DNS names).

    Returns:
        ``(cert_path, key_path)`` as :class:`Path` objects.
    """
    cert_path = out_dir / f"{service_name}.crt"
    key_path = out_dir / f"{service_name}.key"

    cert_pem, key_pem = _sign_certificate(
        ca_cert_path,
        ca_key_path,
        cn=service_name,
        days=days,
        is_server=False,
        extra_sans=extra_sans,
    )

    _write_pem(cert_path, cert_pem)
    _write_pem(key_path, key_pem, mode=0o600)
    logger.info("Generated mTLS client cert for '%s': %s", service_name, cert_path)
    return cert_path, key_path


def generate_server_cert(
    hostname: str,
    ca_cert_path: Path,
    ca_key_path: Path,
    out_dir: Path,
    days: int = 365,
    extra_sans: list[str] | None = None,
) -> tuple[Path, Path]:
    """Generate a server certificate signed by the CA.

    Args:
        hostname:      Server hostname (CN and primary DNS SAN).
        ca_cert_path:  Path to the CA certificate.
        ca_key_path:   Path to the CA private key.
        out_dir:       Directory to write ``server.crt`` and ``server.key``.
        days:          Certificate validity period in days.
        extra_sans:    Additional SAN entries.

    Returns:
        ``(cert_path, key_path)`` as :class:`Path` objects.
    """
    cert_path = out_dir / "server.crt"
    key_path = out_dir / "server.key"

    cert_pem, key_pem = _sign_certificate(
        ca_cert_path,
        ca_key_path,
        cn=hostname,
        days=days,
        is_server=True,
        extra_sans=extra_sans,
    )

    _write_pem(cert_path, cert_pem)
    _write_pem(key_path, key_pem, mode=0o600)
    logger.info("Generated mTLS server cert for '%s': %s", hostname, cert_path)
    return cert_path, key_path


def ensure_mtls_pki(
    base_dir: Path | None = None,
    services: tuple[str, ...] = _BMT_SERVICES,
    hostname: str = "bmt-controller",
    days: int = 365,
) -> dict[str, dict[str, str]]:
    """Bootstrap the full mTLS PKI if it does not already exist.

    Creates:
    - ``<base_dir>/ca/``         — CA cert + key
    - ``<base_dir>/server/``     — Server cert + key (signed by CA)
    - ``<base_dir>/clients/<n>/`` — Per-service client cert + key

    Existing files are *not* overwritten; call :func:`generate_ca` /
    :func:`generate_service_cert` directly to force regeneration.

    Args:
        base_dir:  Root directory for the PKI tree (auto-detected when None).
        services:  Tuple of service names to issue client certs for.
        hostname:  Hostname for the server certificate CN / SAN.
        days:      Certificate validity for server and client certs.

    Returns:
        A dict mapping ``"ca"``, ``"server"``, and each service name to a
        ``{"cert": ..., "key": ...}`` dict of absolute path strings.
    """
    if base_dir is None:
        base_dir = _mtls_base_dir()

    ca_dir = base_dir / "ca"
    server_dir = base_dir / "server"
    clients_dir = base_dir / "clients"

    result: dict[str, dict[str, str]] = {}

    # --- CA ---
    ca_cert_path = ca_dir / "ca.crt"
    ca_key_path = ca_dir / "ca.key"

    if not ca_cert_path.exists() or not ca_key_path.exists():
        ca_cert_path, ca_key_path = generate_ca(ca_dir)
    else:
        logger.debug("mTLS CA already present at %s", ca_dir)

    result["ca"] = {"cert": str(ca_cert_path), "key": str(ca_key_path)}

    # --- Server cert ---
    server_cert = server_dir / "server.crt"
    server_key = server_dir / "server.key"

    if not server_cert.exists() or not server_key.exists():
        server_cert, server_key = generate_server_cert(
            hostname, ca_cert_path, ca_key_path, server_dir, days=days
        )
    else:
        logger.debug("mTLS server cert already present at %s", server_dir)

    result["server"] = {"cert": str(server_cert), "key": str(server_key)}

    # --- Per-service client certs ---
    for svc in services:
        svc_dir = clients_dir / svc
        svc_cert = svc_dir / f"{svc}.crt"
        svc_key = svc_dir / f"{svc}.key"

        if not svc_cert.exists() or not svc_key.exists():
            svc_cert, svc_key = generate_service_cert(
                svc, ca_cert_path, ca_key_path, svc_dir, days=days
            )
        else:
            logger.debug("mTLS client cert for '%s' already present at %s", svc, svc_dir)

        result[svc] = {"cert": str(svc_cert), "key": str(svc_key)}

    return result
