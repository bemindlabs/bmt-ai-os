"""Self-signed TLS certificate generation and renewal for BMT AI OS.

Certificates are stored in /data/secrets/tls/ on the target device.
Development fallback is /tmp/bmt-tls/ when the production path is not
writable (e.g. developer laptops or CI).

Certificate renewal is triggered automatically when the remaining validity
drops below ``BMT_TLS_RENEW_DAYS`` (default: 30 days).
"""

import datetime
import ipaddress
import logging
import os
from pathlib import Path

logger = logging.getLogger("bmt-tls")

# Production path on the device; requires /data to be mounted.
_PROD_CERT_DIR = Path("/data/secrets/tls")
# Developer/CI fallback when /data is not writable.
_DEV_CERT_DIR = Path("/tmp/bmt-tls")

_CERT_FILE = "server.crt"
_KEY_FILE = "server.key"

# Number of days before expiry that triggers automatic renewal.
_DEFAULT_RENEW_DAYS = 30


def _default_cert_dir() -> Path:
    """Return the preferred certificate directory, falling back to /tmp."""
    try:
        _PROD_CERT_DIR.mkdir(parents=True, exist_ok=True)
        # Verify writability with a probe.
        probe = _PROD_CERT_DIR / ".write_probe"
        probe.touch()
        probe.unlink()
        return _PROD_CERT_DIR
    except OSError:
        logger.debug("Cannot write to %s, using dev fallback %s", _PROD_CERT_DIR, _DEV_CERT_DIR)
        return _DEV_CERT_DIR


def generate_self_signed(
    cert_path: str | Path,
    key_path: str | Path,
    hostname: str = "localhost",
    days: int = 365,
) -> None:
    """Generate a self-signed X.509 certificate and write it to disk.

    Uses the ``cryptography`` library (>=43.0).  The certificate includes
    both a DNS SAN and an IP SAN for 127.0.0.1 / ::1 so local tooling
    that validates SANs works without extra configuration.

    Args:
        cert_path: Destination path for the PEM-encoded certificate.
        key_path:  Destination path for the PEM-encoded private key.
        hostname:  Common Name and primary DNS SAN (default: ``localhost``).
        days:      Certificate validity period in days (default: 365).

    Raises:
        ImportError: If the ``cryptography`` package is not installed.
        OSError:     If the parent directory cannot be created or the files
                     cannot be written.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise ImportError(
            "The 'cryptography' package is required for TLS support. "
            "Install it with: pip install 'cryptography>=43.0'"
        ) from exc

    cert_path = Path(cert_path)
    key_path = Path(key_path)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Private key (RSA 4096) ---
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )

    # --- Certificate ---
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BMT AI OS"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Self-Signed"),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(hostname),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv6Address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
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
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # --- Write key (mode 0600) ---
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(key_pem)
    key_path.chmod(0o600)

    # --- Write cert (mode 0644) ---
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_pem)
    cert_path.chmod(0o644)

    logger.info(
        "Generated self-signed certificate: CN=%s, valid %d days, cert=%s, key=%s",
        hostname,
        days,
        cert_path,
        key_path,
    )


def cert_days_remaining(cert_path: str | Path) -> int | None:
    """Return the number of days until the certificate at *cert_path* expires.

    Returns ``None`` if the certificate cannot be read or parsed.  A negative
    value means the certificate has already expired.
    """
    try:
        from cryptography import x509
    except ImportError:
        return None

    try:
        with open(cert_path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = cert.not_valid_after_utc - now
        return delta.days
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read certificate at %s: %s", cert_path, exc)
        return None


def needs_renewal(cert_path: str | Path, renew_before_days: int | None = None) -> bool:
    """Return ``True`` if the certificate should be renewed.

    The certificate is considered renewal-eligible when:
    - The file does not exist, or
    - The remaining validity is less than *renew_before_days* (default:
      ``BMT_TLS_RENEW_DAYS`` env var, then :data:`_DEFAULT_RENEW_DAYS`).

    Args:
        cert_path:        Path to the PEM certificate to inspect.
        renew_before_days: Override the renewal threshold in days.

    Returns:
        ``True`` if the certificate should be regenerated.
    """
    if not Path(cert_path).exists():
        return True

    if renew_before_days is None:
        try:
            renew_before_days = int(os.environ.get("BMT_TLS_RENEW_DAYS", _DEFAULT_RENEW_DAYS))
        except (TypeError, ValueError):
            renew_before_days = _DEFAULT_RENEW_DAYS

    days_left = cert_days_remaining(cert_path)
    if days_left is None:
        return True
    return days_left < renew_before_days


def ensure_certs(
    cert_dir: str | Path | None = None,
    *,
    renew: bool = True,
    renew_before_days: int | None = None,
) -> tuple[str, str]:
    """Return (cert_path, key_path), generating or renewing them as needed.

    If *cert_dir* is ``None`` the default directory is resolved: production
    devices use ``/data/secrets/tls/``; developer environments fall back to
    ``/tmp/bmt-tls/``.

    The hostname is taken from ``BMT_TLS_HOSTNAME`` env var, defaulting to
    the system hostname, then ``"localhost"`` if that is unavailable.

    Args:
        cert_dir:          Directory to store certificates (auto-detected when
                           ``None``).
        renew:             When ``True``, regenerate certificates that are
                           close to expiry (see *renew_before_days*).
        renew_before_days: Days-before-expiry threshold that triggers renewal.
                           Defaults to the ``BMT_TLS_RENEW_DAYS`` env var or
                           :data:`_DEFAULT_RENEW_DAYS` (30 days).

    Returns:
        A ``(cert_path, key_path)`` tuple of absolute path strings.
    """
    if cert_dir is None:
        base = _default_cert_dir()
    else:
        base = Path(cert_dir)

    cert_path = base / _CERT_FILE
    key_path = base / _KEY_FILE

    if cert_path.exists() and key_path.exists():
        if not renew or not needs_renewal(cert_path, renew_before_days=renew_before_days):
            logger.debug("TLS certificates already present at %s", base)
            return str(cert_path), str(key_path)

        days_left = cert_days_remaining(cert_path)
        logger.info(
            "Renewing TLS certificates in %s (days_remaining=%s)",
            base,
            days_left,
        )
    else:
        hostname = os.environ.get("BMT_TLS_HOSTNAME") or _system_hostname()
        logger.info("Generating TLS certificates in %s (hostname=%s)", base, hostname)

    hostname = os.environ.get("BMT_TLS_HOSTNAME") or _system_hostname()
    generate_self_signed(cert_path, key_path, hostname=hostname)

    return str(cert_path), str(key_path)


def _system_hostname() -> str:
    """Return the system hostname, falling back to 'localhost'."""
    import socket

    try:
        return socket.gethostname() or "localhost"
    except OSError:
        return "localhost"
