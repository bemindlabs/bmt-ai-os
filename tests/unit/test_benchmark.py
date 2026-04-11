"""Unit tests for the benchmark suite.

All tests are offline — no live Ollama or ChromaDB instances are required.
HTTP calls made by the benchmark modules are intercepted with ``unittest.mock``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmt_ai_os.benchmark import suite as _suite
from bmt_ai_os.benchmark.inference import (  # noqa: E402
    InferenceResult,
    _count_prompt_tokens,
    _read_model_memory_mb,
)
from bmt_ai_os.benchmark.rag import RAGResult
from bmt_ai_os.benchmark.suite import (
    BenchmarkReport,
    compare_reports,
    detect_board,
    format_comparison,
    save_report,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_inference_result(**kwargs) -> InferenceResult:
    defaults = dict(
        model="qwen2.5:0.5b",
        prompt_tokens=10,
        generated_tokens=120,
        first_token_ms=95.0,
        total_ms=2800.0,
        throughput_tok_s=42.8,
        memory_peak_mb=900.0,
    )
    defaults.update(kwargs)
    return InferenceResult(**defaults)


def _make_rag_result(**kwargs) -> RAGResult:
    defaults = dict(
        model="qwen2.5:0.5b",
        embedding_model="nomic-embed-text",
        embed_ms=180.0,
        retrieve_ms=45.0,
        generate_ms=2100.0,
        total_ms=2325.0,
        retrieved_docs=3,
    )
    defaults.update(kwargs)
    return RAGResult(**defaults)


def _make_report(**kwargs) -> BenchmarkReport:
    defaults = dict(
        timestamp="2026-04-10T12:00:00",
        board="apple-silicon",
        model="qwen2.5:0.5b",
        inference_tok_s=42.8,
        first_token_ms=95.0,
        rag_query_ms=2325.0,
        memory_peak_mb=900.0,
        inference_total_ms=2800.0,
        rag_embed_ms=180.0,
        rag_retrieve_ms=45.0,
        rag_generate_ms=2100.0,
        embedding_model="nomic-embed-text",
    )
    defaults.update(kwargs)
    return BenchmarkReport(**defaults)


# ---------------------------------------------------------------------------
# InferenceResult
# ---------------------------------------------------------------------------


class TestInferenceResult:
    def test_to_dict_keys(self) -> None:
        r = _make_inference_result()
        d = r.to_dict()
        assert set(d) == {
            "model",
            "prompt_tokens",
            "generated_tokens",
            "first_token_ms",
            "total_ms",
            "throughput_tok_s",
            "memory_peak_mb",
        }

    def test_to_dict_rounding(self) -> None:
        r = _make_inference_result(first_token_ms=95.12345, throughput_tok_s=42.8765)
        d = r.to_dict()
        assert d["first_token_ms"] == 95.1
        assert d["throughput_tok_s"] == 42.88

    def test_count_prompt_tokens(self) -> None:
        assert _count_prompt_tokens("hello world foo") == 3
        assert _count_prompt_tokens("") == 0

    def test_read_model_memory_mb_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {"name": "qwen2.5:0.5b", "size_vram": 0, "size": 943_718_400},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("bmt_ai_os.benchmark.inference.requests.get", return_value=mock_resp):
            mb = _read_model_memory_mb("http://localhost:11434", "qwen2.5:0.5b")
        assert mb == pytest.approx(900.0, rel=0.01)

    def test_read_model_memory_mb_not_found(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("bmt_ai_os.benchmark.inference.requests.get", return_value=mock_resp):
            mb = _read_model_memory_mb("http://localhost:11434", "missing-model")
        assert mb == 0.0

    def test_read_model_memory_mb_request_failure(self) -> None:
        with patch(
            "bmt_ai_os.benchmark.inference.requests.get",
            side_effect=ConnectionError("refused"),
        ):
            mb = _read_model_memory_mb("http://localhost:11434", "qwen2.5:0.5b")
        assert mb == 0.0


# ---------------------------------------------------------------------------
# RAGResult
# ---------------------------------------------------------------------------


class TestRAGResult:
    def test_to_dict_keys(self) -> None:
        r = _make_rag_result()
        d = r.to_dict()
        assert set(d) == {
            "model",
            "embedding_model",
            "embed_ms",
            "retrieve_ms",
            "generate_ms",
            "total_ms",
            "retrieved_docs",
        }

    def test_to_dict_rounding(self) -> None:
        r = _make_rag_result(embed_ms=180.1234, total_ms=2325.9876)
        d = r.to_dict()
        assert d["embed_ms"] == 180.1
        assert d["total_ms"] == 2326.0


# ---------------------------------------------------------------------------
# BenchmarkReport
# ---------------------------------------------------------------------------


class TestBenchmarkReport:
    def test_to_dict_has_required_schema_fields(self) -> None:
        report = _make_report()
        d = report.to_dict()
        required = {
            "timestamp",
            "board",
            "model",
            "inference_tok_s",
            "first_token_ms",
            "rag_query_ms",
            "memory_peak_mb",
        }
        assert required.issubset(set(d))

    def test_to_json_is_valid(self) -> None:
        report = _make_report()
        parsed = json.loads(report.to_json())
        assert parsed["model"] == "qwen2.5:0.5b"

    def test_to_json_indent(self) -> None:
        report = _make_report()
        raw = report.to_json(indent=2)
        # Indented JSON should contain newlines.
        assert "\n" in raw


# ---------------------------------------------------------------------------
# save_report / compare_reports
# ---------------------------------------------------------------------------


class TestSaveReport:
    def test_creates_file(self, tmp_path: Path) -> None:
        report = _make_report()
        path = save_report(report, reports_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".json"

    def test_file_content_is_valid_json(self, tmp_path: Path) -> None:
        report = _make_report()
        path = save_report(report, reports_dir=tmp_path)
        data = json.loads(path.read_text())
        assert data["board"] == "apple-silicon"
        assert data["model"] == "qwen2.5:0.5b"

    def test_filename_contains_model(self, tmp_path: Path) -> None:
        report = _make_report(model="qwen2.5:7b")
        path = save_report(report, reports_dir=tmp_path)
        assert "qwen2.5-7b" in path.name

    def test_creates_reports_dir(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "new_subdir"
        assert not new_dir.exists()
        save_report(_make_report(), reports_dir=new_dir)
        assert new_dir.exists()


class TestCompareReports:
    def _write_report(self, path: Path, overrides: dict | None = None) -> Path:
        data = _make_report(**(overrides or {})).to_dict()
        path.write_text(json.dumps(data))
        return path

    def test_compare_returns_all_keys(self, tmp_path: Path) -> None:
        f1 = self._write_report(tmp_path / "a.json")
        f2 = self._write_report(tmp_path / "b.json")
        comparison = compare_reports(f1, f2)
        assert "inference_tok_s" in comparison
        assert "first_token_ms" in comparison
        assert "rag_query_ms" in comparison

    def test_delta_computed_correctly(self, tmp_path: Path) -> None:
        f1 = self._write_report(tmp_path / "a.json", {"inference_tok_s": 40.0})
        f2 = self._write_report(tmp_path / "b.json", {"inference_tok_s": 50.0})
        comparison = compare_reports(f1, f2)
        entry = comparison["inference_tok_s"]
        assert entry["before"] == pytest.approx(40.0)
        assert entry["after"] == pytest.approx(50.0)
        assert entry["delta"] == pytest.approx(10.0)
        assert entry["pct_change"] == pytest.approx(25.0)

    def test_negative_delta(self, tmp_path: Path) -> None:
        f1 = self._write_report(tmp_path / "a.json", {"first_token_ms": 200.0})
        f2 = self._write_report(tmp_path / "b.json", {"first_token_ms": 100.0})
        comparison = compare_reports(f1, f2)
        assert comparison["first_token_ms"]["delta"] == pytest.approx(-100.0)

    def test_zero_before_no_pct(self, tmp_path: Path) -> None:
        f1 = self._write_report(tmp_path / "a.json", {"rag_query_ms": 0.0})
        f2 = self._write_report(tmp_path / "b.json", {"rag_query_ms": 100.0})
        comparison = compare_reports(f1, f2)
        assert comparison["rag_query_ms"]["pct_change"] is None

    def test_string_field_no_delta(self, tmp_path: Path) -> None:
        f1 = self._write_report(tmp_path / "a.json", {"board": "pi5"})
        f2 = self._write_report(tmp_path / "b.json", {"board": "jetson-orin"})
        comparison = compare_reports(f1, f2)
        board_entry = comparison["board"]
        assert "delta" not in board_entry
        assert board_entry["before"] == "pi5"
        assert board_entry["after"] == "jetson-orin"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(Exception):
            compare_reports("/nonexistent/a.json", "/nonexistent/b.json")


# ---------------------------------------------------------------------------
# format_comparison
# ---------------------------------------------------------------------------


class TestFormatComparison:
    def test_output_is_string(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        r = _make_report()
        f1.write_text(r.to_json())
        f2.write_text(r.to_json())
        comparison = compare_reports(f1, f2)
        table = format_comparison(comparison)
        assert isinstance(table, str)
        assert "METRIC" in table
        assert "BEFORE" in table
        assert "AFTER" in table

    def test_output_contains_metric_names(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        r = _make_report()
        f1.write_text(r.to_json())
        f2.write_text(r.to_json())
        comparison = compare_reports(f1, f2)
        table = format_comparison(comparison)
        assert "inference_tok_s" in table
        assert "rag_query_ms" in table


# ---------------------------------------------------------------------------
# detect_board
# ---------------------------------------------------------------------------


class TestDetectBoard:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BMT_BOARD", "my-custom-board")
        assert detect_board() == "my-custom-board"

    def test_returns_string(self) -> None:
        # Should always return a string without raising.
        result = detect_board()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# suite.run_full (mocked HTTP)
# ---------------------------------------------------------------------------


class TestRunFull:
    def test_run_full_returns_report(self) -> None:
        inf_result = _make_inference_result()
        rag_result = _make_rag_result()

        with (
            patch("bmt_ai_os.benchmark.suite._inf.run", return_value=inf_result),
            patch("bmt_ai_os.benchmark.suite._rag.run", return_value=rag_result),
        ):
            report = _suite.run_full(model="qwen2.5:0.5b", board="test-board")

        assert report.model == "qwen2.5:0.5b"
        assert report.board == "test-board"
        assert report.inference_tok_s == pytest.approx(inf_result.throughput_tok_s)
        assert report.first_token_ms == pytest.approx(inf_result.first_token_ms)
        assert report.rag_query_ms == pytest.approx(rag_result.total_ms)
        assert report.memory_peak_mb == pytest.approx(inf_result.memory_peak_mb)

    def test_run_full_passes_urls(self) -> None:
        inf_result = _make_inference_result()
        rag_result = _make_rag_result()

        with (
            patch("bmt_ai_os.benchmark.suite._inf.run", return_value=inf_result) as mock_inf,
            patch("bmt_ai_os.benchmark.suite._rag.run", return_value=rag_result) as mock_rag,
        ):
            _suite.run_full(
                model="qwen2.5:0.5b",
                ollama_url="http://ollama:11434",
                chromadb_url="http://chroma:8000",
                board="pi5",
            )

        mock_inf.assert_called_once_with(
            model="qwen2.5:0.5b",
            ollama_url="http://ollama:11434",
            warmup=True,
        )
        mock_rag.assert_called_once_with(
            model="qwen2.5:0.5b",
            embedding_model="nomic-embed-text",
            ollama_url="http://ollama:11434",
            chromadb_url="http://chroma:8000",
        )

    def test_run_inference_only_rag_zeroed(self) -> None:
        inf_result = _make_inference_result()

        with patch("bmt_ai_os.benchmark.suite._inf.run", return_value=inf_result):
            report = _suite.run_inference_only(model="qwen2.5:0.5b", board="pi5")

        assert report.rag_query_ms == 0.0
        assert report.inference_tok_s == pytest.approx(inf_result.throughput_tok_s)


# ---------------------------------------------------------------------------
# CLI — benchmark subcommands (smoke test via Click test runner)
# ---------------------------------------------------------------------------


class TestBenchmarkCLI:
    def test_benchmark_run_invokes_suite(self) -> None:
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        with (
            patch("bmt_ai_os.benchmark.suite._inf.run", return_value=_make_inference_result()),
            patch("bmt_ai_os.benchmark.suite._rag.run", return_value=_make_rag_result()),
            patch("bmt_ai_os.benchmark.suite.save_report", return_value=Path("/tmp/report.json")),
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["benchmark", "run", "--model", "qwen2.5:0.5b", "--board", "apple-silicon"],
            )

        assert result.exit_code == 0, result.output
        assert "tok/s" in result.output
        assert "apple-silicon" in result.output

    def test_benchmark_inference_only(self) -> None:
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        with (
            patch("bmt_ai_os.benchmark.suite._inf.run", return_value=_make_inference_result()),
            patch("bmt_ai_os.benchmark.suite.save_report", return_value=Path("/tmp/r.json")),
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["benchmark", "inference", "--model", "qwen2.5:0.5b", "--board", "pi5"],
            )

        assert result.exit_code == 0, result.output
        assert "tok/s" in result.output

    def test_benchmark_inference_no_save(self) -> None:
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        with patch("bmt_ai_os.benchmark.suite._inf.run", return_value=_make_inference_result()):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["benchmark", "inference", "--model", "qwen2.5:0.5b", "--no-save"],
            )

        assert result.exit_code == 0, result.output
        assert "Report saved" not in result.output

    def test_benchmark_compare(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        r = _make_report()
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(r.to_json())
        f2.write_text(r.to_json())

        runner = CliRunner()
        result = runner.invoke(main, ["benchmark", "compare", str(f1), str(f2)])

        assert result.exit_code == 0, result.output
        assert "METRIC" in result.output
        assert "inference_tok_s" in result.output

    def test_benchmark_run_error_propagates(self) -> None:
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        with (
            patch(
                "bmt_ai_os.benchmark.suite._inf.run",
                side_effect=RuntimeError("Ollama unreachable"),
            ),
            patch("bmt_ai_os.benchmark.suite._rag.run", return_value=_make_rag_result()),
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["benchmark", "run", "--model", "qwen2.5:0.5b"],
            )

        assert result.exit_code != 0
        assert "Error" in result.output
