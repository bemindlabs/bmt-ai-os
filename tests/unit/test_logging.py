"""Unit tests for bmt_ai_os.logging — JSONFormatter and setup_logging."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Direct module load to avoid heavy transitive imports from bmt_ai_os.__init__
# ---------------------------------------------------------------------------

_logging_path = Path(__file__).resolve().parents[2] / "bmt_ai_os" / "logging.py"
_spec = importlib.util.spec_from_file_location("bmt_logging", _logging_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("bmt_logging", _mod)
_spec.loader.exec_module(_mod)

JSONFormatter = _mod.JSONFormatter
TextFormatter = _mod.TextFormatter
RequestIDFilter = _mod.RequestIDFilter
setup_logging = _mod.setup_logging
configure_log_streams = _mod.configure_log_streams
get_formatter = _mod.get_formatter
set_request_id = _mod.set_request_id
get_request_id = _mod.get_request_id
clear_request_id = _mod.clear_request_id
LOG_STREAMS = _mod.LOG_STREAMS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    msg: str = "test message",
    level: int = logging.INFO,
    logger_name: str = "test",
    trace_id: str | None = None,
    exc_info=None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=logger_name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    if trace_id is not None:
        record.trace_id = trace_id
    return record


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    def test_output_is_valid_json(self):
        fmt = JSONFormatter(service="svc")
        record = _make_record()
        line = fmt.format(record)
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        fmt = JSONFormatter(service="my-service")
        record = _make_record(msg="hello world")
        doc = json.loads(fmt.format(record))

        assert "ts" in doc
        assert "level" in doc
        assert "service" in doc
        assert "msg" in doc
        assert "trace_id" in doc

    def test_service_field_matches_constructor(self):
        fmt = JSONFormatter(service="controller")
        doc = json.loads(fmt.format(_make_record()))
        assert doc["service"] == "controller"

    def test_msg_field_contains_message(self):
        fmt = JSONFormatter(service="svc")
        doc = json.loads(fmt.format(_make_record(msg="something happened")))
        assert doc["msg"] == "something happened"

    def test_level_field_matches(self):
        fmt = JSONFormatter(service="svc")

        for level, expected in [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]:
            doc = json.loads(fmt.format(_make_record(level=level)))
            assert doc["level"] == expected

    def test_trace_id_present_when_set(self):
        fmt = JSONFormatter(service="svc")
        doc = json.loads(fmt.format(_make_record(trace_id="abc-123")))
        assert doc["trace_id"] == "abc-123"

    def test_trace_id_empty_string_when_absent(self):
        fmt = JSONFormatter(service="svc")
        record = _make_record()
        # Ensure attribute is absent (not set by _make_record when None)
        assert not hasattr(record, "trace_id")
        doc = json.loads(fmt.format(record))
        assert doc["trace_id"] == ""

    def test_ts_is_utc_iso8601(self):
        fmt = JSONFormatter(service="svc")
        doc = json.loads(fmt.format(_make_record()))
        ts = doc["ts"]
        # Must end with Z for UTC
        assert ts.endswith("Z"), f"Expected UTC timestamp ending in Z, got: {ts}"
        # Must parse without error
        from datetime import datetime

        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_printf_style_args_are_rendered(self):
        fmt = JSONFormatter(service="svc")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="count=%d",
            args=(42,),
            exc_info=None,
        )
        doc = json.loads(fmt.format(record))
        assert doc["msg"] == "count=42"

    def test_exc_field_included_on_exception(self):
        fmt = JSONFormatter(service="svc")
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = _make_record(exc_info=exc_info)
        doc = json.loads(fmt.format(record))
        assert "exc" in doc
        assert "ValueError" in doc["exc"]
        assert "boom" in doc["exc"]

    def test_no_exc_field_without_exception(self):
        fmt = JSONFormatter(service="svc")
        doc = json.loads(fmt.format(_make_record()))
        assert "exc" not in doc

    def test_output_is_single_line(self):
        fmt = JSONFormatter(service="svc")
        line = fmt.format(_make_record(msg="no newlines here"))
        # The JSON itself should have no literal newlines (exc aside)
        assert "\n" not in line


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def _unique_name(self, suffix: str = "") -> str:
        import uuid

        return f"test_svc_{uuid.uuid4().hex[:8]}{suffix}"

    def test_returns_logger_with_correct_name(self):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=None)
        assert logger.name == name

    def test_stdout_fallback_when_log_dir_none(self):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=None)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_stdout_fallback_when_log_dir_missing_and_cannot_create(self, tmp_path):
        # Point to a sub-path under a non-writable directory by using a
        # path that cannot be created (parent is a file, not a dir).
        fake_file = tmp_path / "not_a_dir"
        fake_file.write_text("x")
        bad_dir = fake_file / "subdir"  # parent is a file — mkdir will fail

        name = self._unique_name()
        logger = setup_logging(name, log_dir=bad_dir)
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_rotating_file_handler_created_for_valid_dir(self, tmp_path):
        import logging.handlers as lh

        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], lh.RotatingFileHandler)

    def test_log_file_path_is_service_name_dot_log(self, tmp_path):
        import logging.handlers as lh

        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)
        handler = logger.handlers[0]
        assert isinstance(handler, lh.RotatingFileHandler)
        assert Path(handler.baseFilename).name == f"{name}.log"
        assert Path(handler.baseFilename).parent == tmp_path

    def test_max_bytes_propagated(self, tmp_path):
        import logging.handlers as lh

        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, max_bytes=1024)
        handler = logger.handlers[0]
        assert isinstance(handler, lh.RotatingFileHandler)
        assert handler.maxBytes == 1024

    def test_backup_count_propagated(self, tmp_path):
        import logging.handlers as lh

        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, backup_count=3)
        handler = logger.handlers[0]
        assert isinstance(handler, lh.RotatingFileHandler)
        assert handler.backupCount == 3

    def test_log_level_set_correctly(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_log_level_as_string(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, level="WARNING")
        assert logger.level == logging.WARNING

    def test_handler_uses_json_formatter(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_log_dir_is_created_if_missing(self, tmp_path):
        new_dir = tmp_path / "nested" / "logs"
        assert not new_dir.exists()
        name = self._unique_name()
        setup_logging(name, log_dir=new_dir)
        assert new_dir.exists()

    def test_calling_twice_does_not_duplicate_handlers(self, tmp_path):
        name = self._unique_name()
        setup_logging(name, log_dir=tmp_path)
        setup_logging(name, log_dir=tmp_path)
        logger = logging.getLogger(name)
        assert len(logger.handlers) == 1

    def test_emitted_record_is_valid_json(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)

        # Force the file to be opened by emitting a record.
        logger.info("integration check")

        # Flush and close to ensure data is written.
        for h in logger.handlers:
            h.flush()

        log_file = tmp_path / f"{name}.log"
        assert log_file.exists()
        lines = [line for line in log_file.read_text().splitlines() if line.strip()]
        assert len(lines) >= 1
        doc = json.loads(lines[-1])
        assert doc["service"] == name
        assert doc["msg"] == "integration check"
        assert doc["level"] == "INFO"
        assert doc["ts"].endswith("Z")

    def test_stdout_fallback_emits_json(self):
        """When stdout is used as fallback the formatter is still JSONFormatter."""
        name = self._unique_name()
        logger = setup_logging(name, log_dir=None)
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)


# ---------------------------------------------------------------------------
# CLI logs command
# ---------------------------------------------------------------------------


class TestCLILogs:
    """Tests for the `bmt-ai-os logs` CLI subcommand."""

    def _write_json_log(self, path: Path, records: list[dict]) -> None:
        with open(path, "w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def _sample_records(self, n: int = 5) -> list[dict]:
        return [
            {
                "ts": f"2026-04-10T12:00:{i:02d}.000000Z",
                "level": "INFO",
                "service": "controller",
                "msg": f"message {i}",
                "trace_id": f"tid-{i}",
            }
            for i in range(n)
        ]

    def test_logs_human_format(self, tmp_path):
        from click.testing import CliRunner

        log_file = tmp_path / "controller.log"
        records = self._sample_records(5)
        self._write_json_log(log_file, records)

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--service", "controller", "--tail", "5", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        # Human format includes the message text
        assert "message 4" in result.output

    def test_logs_json_format(self, tmp_path):
        from click.testing import CliRunner

        log_file = tmp_path / "controller.log"
        records = self._sample_records(3)
        self._write_json_log(log_file, records)

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--service", "controller", "--json", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        # Each output line must be valid JSON
        output_lines = [line for line in result.output.splitlines() if line.strip()]
        assert len(output_lines) == 3
        for line in output_lines:
            doc = json.loads(line)
            assert "msg" in doc

    def test_logs_tail_limits_output(self, tmp_path):
        from click.testing import CliRunner

        log_file = tmp_path / "controller.log"
        records = self._sample_records(20)
        self._write_json_log(log_file, records)

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--service", "controller", "--tail", "5", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        output_lines = [line for line in result.output.splitlines() if line.strip()]
        assert len(output_lines) == 5

    def test_logs_last_n_lines_returned(self, tmp_path):
        """--tail N should return the *last* N lines, not the first N."""
        from click.testing import CliRunner

        log_file = tmp_path / "controller.log"
        records = self._sample_records(10)
        self._write_json_log(log_file, records)

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--service", "controller", "--tail", "3", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        # Last 3 records have msgs "message 7", "message 8", "message 9"
        assert "message 7" in result.output
        assert "message 8" in result.output
        assert "message 9" in result.output
        assert "message 0" not in result.output

    def test_logs_missing_file_exits_nonzero(self, tmp_path):
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--service", "nonexistent", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_logs_default_service_is_controller(self, tmp_path):
        """Omitting --service should default to 'controller'."""
        from click.testing import CliRunner

        log_file = tmp_path / "controller.log"
        self._write_json_log(log_file, self._sample_records(2))

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "message" in result.output

    def test_logs_non_json_lines_passed_through(self, tmp_path):
        """Lines that are not valid JSON should be emitted unchanged."""
        from click.testing import CliRunner

        log_file = tmp_path / "controller.log"
        log_file.write_text("plain text line\n")

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["logs", "--service", "controller", "--log-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "plain text line" in result.output


# ---------------------------------------------------------------------------
# TextFormatter
# ---------------------------------------------------------------------------


class TestTextFormatter:
    def test_output_is_not_json(self):
        fmt = TextFormatter(service="svc")
        line = fmt.format(_make_record())
        # Human format is not valid JSON
        try:
            json.loads(line)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json

    def test_contains_level(self):
        fmt = TextFormatter(service="svc")
        line = fmt.format(_make_record(level=logging.WARNING))
        assert "WARNING" in line

    def test_contains_service(self):
        fmt = TextFormatter(service="myservice")
        line = fmt.format(_make_record())
        assert "myservice" in line

    def test_contains_message(self):
        fmt = TextFormatter(service="svc")
        line = fmt.format(_make_record(msg="hello world"))
        assert "hello world" in line

    def test_contains_logger_name(self):
        fmt = TextFormatter(service="svc")
        line = fmt.format(_make_record(logger_name="bmt.controller"))
        assert "bmt.controller" in line

    def test_contains_utc_timestamp(self):
        fmt = TextFormatter(service="svc")
        line = fmt.format(_make_record())
        assert "Z" in line

    def test_trace_id_included_when_set(self):
        fmt = TextFormatter(service="svc")
        doc = fmt.format(_make_record(trace_id="req-abc"))
        assert "req-abc" in doc

    def test_trace_id_absent_when_not_set(self):
        fmt = TextFormatter(service="svc")
        record = _make_record()
        line = fmt.format(record)
        assert "trace_id" not in line

    def test_exc_info_appended(self):
        fmt = TextFormatter(service="svc")
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            exc_info = sys.exc_info()
        record = _make_record(exc_info=exc_info)
        line = fmt.format(record)
        assert "RuntimeError" in line
        assert "kaboom" in line


# ---------------------------------------------------------------------------
# get_formatter / BMT_LOG_FORMAT env toggle
# ---------------------------------------------------------------------------


class TestGetFormatter:
    def test_default_returns_json_formatter(self, monkeypatch):
        monkeypatch.delenv("BMT_LOG_FORMAT", raising=False)
        formatter = get_formatter("svc")
        assert isinstance(formatter, JSONFormatter)

    def test_env_json_returns_json_formatter(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "json")
        formatter = get_formatter("svc")
        assert isinstance(formatter, JSONFormatter)

    def test_env_text_returns_text_formatter(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "text")
        formatter = get_formatter("svc")
        assert isinstance(formatter, TextFormatter)

    def test_explicit_fmt_overrides_env(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "json")
        formatter = get_formatter("svc", fmt="text")
        assert isinstance(formatter, TextFormatter)

    def test_explicit_json_overrides_text_env(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "text")
        formatter = get_formatter("svc", fmt="json")
        assert isinstance(formatter, JSONFormatter)

    def test_case_insensitive_env(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "TEXT")
        formatter = get_formatter("svc")
        assert isinstance(formatter, TextFormatter)

    def test_unknown_format_falls_back_to_json(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "xml")
        formatter = get_formatter("svc")
        assert isinstance(formatter, JSONFormatter)

    def test_text_format_emits_human_readable(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FORMAT", "text")
        formatter = get_formatter("svc")
        record = _make_record(msg="startup complete")
        line = formatter.format(record)
        assert "startup complete" in line


# ---------------------------------------------------------------------------
# RequestIDFilter
# ---------------------------------------------------------------------------


class TestRequestIDFilter:
    def setup_method(self):
        clear_request_id()

    def teardown_method(self):
        clear_request_id()

    def test_injects_empty_string_when_no_request_id(self):
        flt = RequestIDFilter()
        record = _make_record()
        # Ensure trace_id is absent
        if hasattr(record, "trace_id"):
            del record.trace_id
        flt.filter(record)
        assert record.trace_id == ""

    def test_injects_current_request_id(self):
        set_request_id("test-req-42")
        flt = RequestIDFilter()
        record = _make_record()
        if hasattr(record, "trace_id"):
            del record.trace_id
        flt.filter(record)
        assert record.trace_id == "test-req-42"

    def test_does_not_overwrite_existing_trace_id(self):
        set_request_id("from-thread")
        flt = RequestIDFilter()
        record = _make_record(trace_id="already-set")
        flt.filter(record)
        assert record.trace_id == "already-set"

    def test_always_returns_true(self):
        flt = RequestIDFilter()
        record = _make_record()
        assert flt.filter(record) is True


# ---------------------------------------------------------------------------
# set/get/clear_request_id
# ---------------------------------------------------------------------------


class TestRequestIDThreadLocal:
    def setup_method(self):
        clear_request_id()

    def teardown_method(self):
        clear_request_id()

    def test_set_and_get(self):
        set_request_id("abc-123")
        assert get_request_id() == "abc-123"

    def test_clear_resets_to_empty(self):
        set_request_id("abc-123")
        clear_request_id()
        assert get_request_id() == ""

    def test_default_is_empty_string(self):
        assert get_request_id() == ""

    def test_thread_isolation(self):
        """Each thread has its own request ID."""
        import threading

        results: dict[str, str] = {}

        def thread_fn(tid: str) -> None:
            set_request_id(tid)
            import time

            time.sleep(0.01)
            results[tid] = get_request_id()

        threads = [threading.Thread(target=thread_fn, args=(f"tid-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(5):
            assert results[f"tid-{i}"] == f"tid-{i}"


# ---------------------------------------------------------------------------
# setup_logging — new parameters
# ---------------------------------------------------------------------------


class TestSetupLoggingExtended:
    def _unique_name(self, suffix: str = "") -> str:
        import uuid

        return f"test_ext_{uuid.uuid4().hex[:8]}{suffix}"

    def test_default_max_bytes_is_100mb(self, tmp_path):
        import logging.handlers as lh

        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)
        handler = logger.handlers[0]
        assert isinstance(handler, lh.RotatingFileHandler)
        assert handler.maxBytes == 100 * 1024 * 1024

    def test_default_backup_count_is_7(self, tmp_path):
        import logging.handlers as lh

        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)
        handler = logger.handlers[0]
        assert isinstance(handler, lh.RotatingFileHandler)
        assert handler.backupCount == 7

    def test_fmt_text_uses_text_formatter(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, fmt="text")
        assert isinstance(logger.handlers[0].formatter, TextFormatter)

    def test_fmt_json_uses_json_formatter(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, fmt="json")
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_request_id_filter_attached(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path)
        handler = logger.handlers[0]
        filters = handler.filters
        assert any(isinstance(f, RequestIDFilter) for f in filters)

    def test_module_levels_applied(self, tmp_path):
        import uuid

        name = self._unique_name()
        target_module = f"bmt_test_{uuid.uuid4().hex[:6]}"
        setup_logging(
            name,
            log_dir=tmp_path,
            module_levels={target_module: "DEBUG"},
        )
        mod_logger = logging.getLogger(target_module)
        assert mod_logger.level == logging.DEBUG

    def test_module_levels_string_warning(self, tmp_path):
        import uuid

        name = self._unique_name()
        target_module = f"bmt_test_{uuid.uuid4().hex[:6]}"
        setup_logging(
            name,
            log_dir=tmp_path,
            module_levels={target_module: "WARNING"},
        )
        assert logging.getLogger(target_module).level == logging.WARNING

    def test_module_levels_int_value(self, tmp_path):
        import uuid

        name = self._unique_name()
        target_module = f"bmt_test_{uuid.uuid4().hex[:6]}"
        setup_logging(
            name,
            log_dir=tmp_path,
            module_levels={target_module: logging.ERROR},
        )
        assert logging.getLogger(target_module).level == logging.ERROR

    def test_json_record_includes_logger_field(self, tmp_path):
        name = self._unique_name()
        logger = setup_logging(name, log_dir=tmp_path, fmt="json")
        logger.info("test logger field")
        for h in logger.handlers:
            h.flush()
        log_file = tmp_path / f"{name}.log"
        lines = [ln for ln in log_file.read_text().splitlines() if ln.strip()]
        doc = json.loads(lines[-1])
        assert "logger" in doc
        assert doc["logger"] == name


# ---------------------------------------------------------------------------
# configure_log_streams
# ---------------------------------------------------------------------------


class TestConfigureLogStreams:
    def test_returns_all_streams(self, tmp_path):
        loggers = configure_log_streams(log_dir=tmp_path)
        assert set(loggers.keys()) == set(LOG_STREAMS)

    def test_each_stream_has_rotating_handler(self, tmp_path):
        import logging.handlers as lh

        loggers = configure_log_streams(log_dir=tmp_path)
        for name, logger in loggers.items():
            assert len(logger.handlers) >= 1
            assert isinstance(logger.handlers[0], lh.RotatingFileHandler), (
                f"Expected RotatingFileHandler for stream '{name}'"
            )

    def test_each_stream_has_separate_log_file(self, tmp_path):
        configure_log_streams(log_dir=tmp_path)
        for stream in LOG_STREAMS:
            logger = logging.getLogger(stream)
            logger.info("stream check %s", stream)
            for h in logger.handlers:
                h.flush()
        for stream in LOG_STREAMS:
            log_file = tmp_path / f"{stream}.log"
            assert log_file.exists(), f"Expected log file for stream '{stream}'"

    def test_stream_names_match_log_streams_constant(self):
        assert "controller" in LOG_STREAMS
        assert "providers" in LOG_STREAMS
        assert "health" in LOG_STREAMS
        assert "rag" in LOG_STREAMS

    def test_stdout_fallback_when_log_dir_none(self):
        loggers = configure_log_streams(log_dir=None)
        assert len(loggers) == len(LOG_STREAMS)
        for name, logger in loggers.items():
            assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers), (
                f"Stream '{name}' has no StreamHandler fallback"
            )

    def test_level_propagated_to_all_streams(self, tmp_path):
        configure_log_streams(log_dir=tmp_path, level=logging.DEBUG)
        for stream in LOG_STREAMS:
            assert logging.getLogger(stream).level == logging.DEBUG

    def test_fmt_text_propagated(self, tmp_path):
        loggers = configure_log_streams(log_dir=tmp_path, fmt="text")
        for name, logger in loggers.items():
            assert isinstance(logger.handlers[0].formatter, TextFormatter), (
                f"Expected TextFormatter for stream '{name}'"
            )
