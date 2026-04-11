"""Structured JSON logging with rotation for BMT AI OS.

Provides:
- JSONFormatter: formats log records as newline-delimited JSON with canonical fields
- TextFormatter: human-readable format for development/debugging
- setup_logging: configures a rotating file handler (or stdout fallback) for a named service
- configure_log_streams: sets up separate loggers for controller/providers/health/rag
- RequestIDFilter: injects the current request ID into log records

Log record fields (JSON mode)
------------------------------
ts        ISO-8601 timestamp in UTC (e.g. "2026-04-10T12:34:56.789012Z")
level     Log level string ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
service   Service name passed to setup_logging
logger    Logger name (e.g. "bmt-controller", "bmt.providers")
msg       Rendered log message (printf-style args already applied)
trace_id  Optional trace/request ID pulled from the LogRecord's trace_id attribute;
          empty string when absent so the field is always present

Environment variables
---------------------
BMT_LOG_FORMAT   "json" (default) or "text" — selects the output formatter
BMT_LOG_LEVEL    Override the default log level (e.g. "DEBUG", "WARNING")

Usage
-----
    from bmt_ai_os.logging import setup_logging
    import logging

    setup_logging("controller", log_dir="/var/log/bmt-ai-os")
    logger = logging.getLogger("bmt-controller")
    logger.info("started")

To attach a trace_id per-request, use a logging.Filter or LoggerAdapter::

    class TraceFilter(logging.Filter):
        def filter(self, record):
            record.trace_id = current_trace_id()
            return True

Named log streams (separate log files per subsystem)::

    from bmt_ai_os.logging import configure_log_streams
    configure_log_streams(log_dir="/var/log/bmt-ai-os")
    # Creates controller.log, providers.log, health.log, rag.log
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "JSONFormatter",
    "TextFormatter",
    "RequestIDFilter",
    "setup_logging",
    "configure_log_streams",
    "get_formatter",
]

# Default rotation thresholds per acceptance criteria
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
_DEFAULT_BACKUP_COUNT = 7

# Named log streams for each subsystem
LOG_STREAMS = ("controller", "providers", "health", "rag")

# Thread-local storage for request ID propagation
_request_id_local = threading.local()


def set_request_id(request_id: str) -> None:
    """Set the current request ID on the calling thread."""
    _request_id_local.request_id = request_id


def get_request_id() -> str:
    """Return the current thread's request ID, or empty string if unset."""
    return getattr(_request_id_local, "request_id", "")


def clear_request_id() -> None:
    """Clear the current thread's request ID."""
    _request_id_local.request_id = ""


class RequestIDFilter(logging.Filter):
    """Inject the current request/trace ID into every log record.

    Attach this filter to any handler or logger that should include
    ``trace_id`` in its output.  Works with both ``JSONFormatter`` and
    ``TextFormatter``.

    The filter pulls the request ID from thread-local storage (set by
    :func:`set_request_id`) so it works transparently without modifying
    any call sites.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "trace_id", None):
            record.trace_id = get_request_id()
        return True


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Each line written to the handler is a complete JSON document terminated
    by a newline — suitable for structured log aggregators (Loki, Fluentd,
    ELK, etc.) and for streaming with ``tail -f``.

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
            "logger": record.name,
            "msg": msg,
            "trace_id": getattr(record, "trace_id", ""),
        }

        exc_text = self._format_exc(record)
        if exc_text:
            doc["exc"] = exc_text

        return json.dumps(doc, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable log formatter for development and interactive use.

    Output format::

        2026-04-10T12:34:56Z  INFO     [controller] [bmt-controller] message here
        2026-04-10T12:34:56Z  INFO     [controller] [bmt-controller] message  [trace_id=abc-123]

    Enabled via ``BMT_LOG_FORMAT=text`` environment variable.
    """

    _FMT = "{ts}  {level:<9} [{service}] [{logger}] {msg}{trace}"

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    @staticmethod
    def _utc_iso(record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        trace_id = getattr(record, "trace_id", "")
        trace_str = f"  [trace_id={trace_id}]" if trace_id else ""

        line = self._FMT.format(
            ts=self._utc_iso(record),
            level=record.levelname,
            service=self._service,
            logger=record.name,
            msg=msg,
            trace=trace_str,
        )

        if record.exc_info:
            exc_text = logging.Formatter().formatException(record.exc_info)
            line = f"{line}\n{exc_text}"

        return line


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


def get_formatter(service: str, *, fmt: str | None = None) -> logging.Formatter:
    """Return a formatter appropriate for the given format name.

    Parameters
    ----------
    service:
        Service name embedded in every log line.
    fmt:
        ``"json"`` (default) or ``"text"``.  When *None*, the value of the
        ``BMT_LOG_FORMAT`` environment variable is used, defaulting to
        ``"json"``.

    Returns
    -------
    logging.Formatter
        Either a :class:`JSONFormatter` or a :class:`TextFormatter`.
    """
    if fmt is None:
        fmt = os.environ.get("BMT_LOG_FORMAT", "json").lower()
    if fmt == "text":
        return TextFormatter(service=service)
    return JSONFormatter(service=service)


def setup_logging(
    service_name: str,
    log_dir: str | Path | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    level: int | str = logging.INFO,
    *,
    fmt: str | None = None,
    module_levels: dict[str, int | str] | None = None,
) -> logging.Logger:
    """Configure structured logging for *service_name*.

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
        Maximum size of a single log file before rotation.  Default 100 MB.
    backup_count:
        Number of rotated files to retain (e.g. 7 → ``.log.1`` … ``.log.7``).
        Default 7.
    level:
        Logging level for this service logger.  Accepts an ``int``
        (``logging.INFO``) or a string (``"DEBUG"``).  Default ``logging.INFO``.
    fmt:
        ``"json"`` or ``"text"``.  Overrides ``BMT_LOG_FORMAT`` env variable.
    module_levels:
        Per-module level overrides, e.g.
        ``{"bmt_ai_os.providers": "DEBUG", "bmt_ai_os.rag": "WARNING"}``.
        Applied after the primary logger is configured.

    Returns
    -------
    logging.Logger
        The configured logger for *service_name*.
    """
    formatter = get_formatter(service_name, fmt=fmt)
    request_filter = RequestIDFilter()

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
    handler.addFilter(request_filter)

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

    # Apply per-module level overrides.
    if module_levels:
        for module_name, module_level in module_levels.items():
            mod_logger = logging.getLogger(module_name)
            if isinstance(module_level, str):
                mod_logger.setLevel(getattr(logging, module_level.upper(), logging.INFO))
            else:
                mod_logger.setLevel(module_level)

    return logger


def configure_log_streams(
    log_dir: str | Path | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    level: int | str = logging.INFO,
    *,
    fmt: str | None = None,
    module_levels: dict[str, int | str] | None = None,
) -> dict[str, logging.Logger]:
    """Configure separate log streams for each BMT AI OS subsystem.

    Creates individual loggers (and optionally rotating log files) for:
    - ``controller`` — main controller orchestration
    - ``providers``  — LLM provider layer
    - ``health``     — health checker and circuit breaker
    - ``rag``        — RAG pipeline

    Parameters mirror :func:`setup_logging`.  Each stream gets its own
    ``<log_dir>/<stream>.log`` file.

    Returns
    -------
    dict[str, logging.Logger]
        Mapping of stream name to configured logger.
    """
    loggers: dict[str, logging.Logger] = {}
    for stream in LOG_STREAMS:
        loggers[stream] = setup_logging(
            stream,
            log_dir=log_dir,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            fmt=fmt,
            module_levels=module_levels if stream == LOG_STREAMS[0] else None,
        )
    return loggers
