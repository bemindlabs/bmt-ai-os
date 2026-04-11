"""Unit tests for bmt_ai_os.logging — JSONFormatter and setup_logging."""

from __future__ import annotations

import importlib.util

import pytest
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
setup_logging = _mod.setup_logging


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
        lines = [l for l in log_file.read_text().splitlines() if l.strip()]
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


@pytest.mark.skip(reason="CLI logs subcommand pending integration")
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
        output_lines = [l for l in result.output.splitlines() if l.strip()]
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
        output_lines = [l for l in result.output.splitlines() if l.strip()]
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
