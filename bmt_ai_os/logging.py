"""Structured JSON logging with rotation for BMT AI OS.

Provides:
- JSONFormatter: formats log records as newline-delimited JSON with canonical fields
- setup_logging: configures a rotating file handler (or stdout fallback) for a named service

Log record fields
-----------------
ts        ISO-8601 timestamp in UTC (e.g. "2026-04-10T12:34:56.789012Z")
level     Log level string ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
service   Service name passed to setup_logging
msg       Rendered log message (printf-style args already applied)
trace_id  Optional trace/request ID pulled from the LogRecord's trace_id attribute;
          empty string when absent so the field is always present

Usage
-----
    from bmt_ai_os.logging import setup_logging
    import logging

    setup_logging("controller", log_dir="/var/log/bmt")
    logger = logging.getLogger("bmt-controller")
    logger.info("started")

To attach a trace_id per-request, use a logging.Filter or LoggerAdapter::

    class TraceFilter(logging.Filter):
        def filter(self, record):
            record.trace_id = current_trace_id()
            return True
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["JSONFormatter", "setup_logging"]

_DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
_DEFAULT_BACKUP_COUNT = 5


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Each line written to the handler is a complete JSON document terminated
    by a newline — suitable for structured log aggregators (Loki, Fluentd, etc.)
    and for streaming with ``tail -f``.

    The ``service`` field is set at construction time so that every record
    emitted through this formatter carries the originating service name even
    when multiple services write to the same log directory.
    """

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _utc_iso(record: logging.LogRecord) -> str:
        """Return the record's creation time as an ISO-8601 UTC string."""
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")

    @staticmethod
    def _format_exc(record: logging.LogRecord) -> str | None:
        """Return a formatted exception string if one is attached, else None."""
        if record.exc_info:
            # formatException caches the result in record.exc_text
            return logging.Formatter().formatException(record.exc_info)
        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def format(self, record: logging.LogRecord) -> str:
        """Render *record* as a JSON line (no trailing newline)."""
        # Materialise the human-readable message (handles printf-style args).
        msg = record.getMessage()

        doc: dict = {
            "ts": self._utc_iso(record),
            "level": record.levelname,
            "service": self._service,
            "msg": msg,
            "trace_id": getattr(record, "trace_id", ""),
        }

        exc_text = self._format_exc(record)
        if exc_text:
            doc["exc"] = exc_text

        return json.dumps(doc, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def setup_logging(
    service_name: str,
    log_dir: str | Path | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    level: int | str = logging.INFO,
) -> logging.Logger:
    """Configure structured JSON logging for *service_name*.

    A ``RotatingFileHandler`` is created at ``<log_dir>/<service_name>.log``
    when *log_dir* exists (or can be created).  If *log_dir* is ``None``, does
    not exist, and cannot be created, the handler falls back to ``stdout``
    transparently — so the same call works both on the full OS image and in
    developer laptops.

    The root logger is left untouched; only the logger named *service_name*
    (and its parent chain up to the root when propagation is enabled) is
    configured.  Call this function once at process start.

    Parameters
    ----------
    service_name:
        Logical name of the service (e.g. ``"controller"``).  Also used as
        the log file stem and the ``service`` JSON field.
    log_dir:
        Directory in which to store the rotating log file.  ``None`` forces
        stdout.
    max_bytes:
        Maximum size of a single log file before rotation.  Default 50 MB.
    backup_count:
        Number of rotated files to retain (e.g. 5 → ``.log.1`` … ``.log.5``).
        Default 5.
    level:
        Logging level for this service logger.  Accepts an ``int``
        (``logging.INFO``) or a string (``"DEBUG"``).  Default ``logging.INFO``.

    Returns
    -------
    logging.Logger
        The configured logger for *service_name*.
    """
    formatter = JSONFormatter(service=service_name)

    handler: logging.Handler

    # Resolve log directory — attempt creation if it doesn't exist yet.
    resolved_dir: Path | None = None
    if log_dir is not None:
        resolved_dir = Path(log_dir)
        try:
            resolved_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            resolved_dir = None  # fall back to stdout

    if resolved_dir is not None:
        log_path = resolved_dir / f"{service_name}.log"
        try:
            handler = logging.handlers.RotatingFileHandler(
                filename=log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
                delay=True,  # don't open the file until the first record
            )
        except OSError:
            handler = logging.StreamHandler(sys.stdout)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)

    # Resolve string level to int.
    if isinstance(level, str):
        numeric_level = getattr(logging, level.upper(), logging.INFO)
    else:
        numeric_level = level

    logger = logging.getLogger(service_name)
    logger.setLevel(numeric_level)

    # Avoid duplicating handlers if setup_logging is called more than once.
    if not logger.handlers:
        logger.addHandler(handler)
    else:
        # Replace handlers with the freshly configured one.
        logger.handlers.clear()
        logger.addHandler(handler)

    return logger
