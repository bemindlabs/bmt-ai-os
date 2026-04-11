"""Main benchmark runner for BMT AI OS.

Coordinates inference and RAG benchmarks, collects system metadata, and
produces a structured JSON report compatible with the BMTOS-47 output schema.

Output schema
-------------
.. code-block:: json

    {
        "timestamp": "2026-04-10T12:00:00",
        "board": "apple-silicon",
        "model": "qwen2.5:0.5b",
        "inference_tok_s": 45.2,
        "first_token_ms": 120,
        "rag_query_ms": 2800,
        "memory_peak_mb": 1200
    }
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import inference as _inf
from . import rag as _rag
from . import system as _sys

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "qwen2.5:0.5b"
_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_CHROMADB_URL = "http://localhost:8000"


@dataclass
class BenchmarkReport:
    """Full benchmark result matching the BMTOS-47 JSON schema."""

    timestamp: str
    board: str
    model: str
    inference_tok_s: float
    first_token_ms: float
    rag_query_ms: float
    memory_peak_mb: float

    # Extended inference fields.
    inference_total_ms: float = 0.0
    rag_embed_ms: float = 0.0
    rag_retrieve_ms: float = 0.0
    rag_generate_ms: float = 0.0
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL

    # System benchmark fields (populated only when the system suite is run).
    cpu_score: float = 0.0
    memory_read_mb_s: float = 0.0
    disk_write_mb_s: float = 0.0
    disk_read_mb_s: float = 0.0
    memory_total_mb: float = 0.0
    memory_available_mb: float = 0.0
    platform_info: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "board": self.board,
            "model": self.model,
            "inference_tok_s": self.inference_tok_s,
            "first_token_ms": self.first_token_ms,
            "rag_query_ms": self.rag_query_ms,
            "memory_peak_mb": self.memory_peak_mb,
            "inference_total_ms": self.inference_total_ms,
            "rag_embed_ms": self.rag_embed_ms,
            "rag_retrieve_ms": self.rag_retrieve_ms,
            "rag_generate_ms": self.rag_generate_ms,
            "embedding_model": self.embedding_model,
            "cpu_score": self.cpu_score,
            "memory_read_mb_s": self.memory_read_mb_s,
            "disk_write_mb_s": self.disk_write_mb_s,
            "disk_read_mb_s": self.disk_read_mb_s,
            "memory_total_mb": self.memory_total_mb,
            "memory_available_mb": self.memory_available_mb,
            "platform_info": self.platform_info,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def run_full(
    model: str = _DEFAULT_MODEL,
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    chromadb_url: str = _DEFAULT_CHROMADB_URL,
    board: str | None = None,
) -> BenchmarkReport:
    """Run the full benchmark suite (inference + RAG) and return a report.

    Parameters
    ----------
    model:
        Ollama model tag for both inference and RAG generation steps.
    embedding_model:
        Ollama model used to produce embeddings in the RAG benchmark.
    ollama_url:
        Base URL of the Ollama service.
    chromadb_url:
        Base URL of the ChromaDB service.
    board:
        Board identifier string.  Auto-detected from the environment when
        ``None`` (see :func:`detect_board`).
    """
    board = board or detect_board()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    logger.info("Running inference benchmark (model=%s)", model)
    inf_result = _inf.run(model=model, ollama_url=ollama_url, warmup=True)

    logger.info("Running RAG benchmark (model=%s, embedding=%s)", model, embedding_model)
    rag_result = _rag.run(
        model=model,
        embedding_model=embedding_model,
        ollama_url=ollama_url,
        chromadb_url=chromadb_url,
    )

    return BenchmarkReport(
        timestamp=timestamp,
        board=board,
        model=model,
        inference_tok_s=inf_result.throughput_tok_s,
        first_token_ms=inf_result.first_token_ms,
        rag_query_ms=rag_result.total_ms,
        memory_peak_mb=inf_result.memory_peak_mb,
        inference_total_ms=inf_result.total_ms,
        rag_embed_ms=rag_result.embed_ms,
        rag_retrieve_ms=rag_result.retrieve_ms,
        rag_generate_ms=rag_result.generate_ms,
        embedding_model=embedding_model,
    )


def run_inference_only(
    model: str = _DEFAULT_MODEL,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    board: str | None = None,
) -> BenchmarkReport:
    """Run only the inference benchmark and return a partial report."""
    board = board or detect_board()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    logger.info("Running inference benchmark (model=%s)", model)
    inf_result = _inf.run(model=model, ollama_url=ollama_url, warmup=True)

    return BenchmarkReport(
        timestamp=timestamp,
        board=board,
        model=model,
        inference_tok_s=inf_result.throughput_tok_s,
        first_token_ms=inf_result.first_token_ms,
        rag_query_ms=0.0,
        memory_peak_mb=inf_result.memory_peak_mb,
        inference_total_ms=inf_result.total_ms,
    )


def run_rag_only(
    model: str = _DEFAULT_MODEL,
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    chromadb_url: str = _DEFAULT_CHROMADB_URL,
    board: str | None = None,
) -> BenchmarkReport:
    """Run only the RAG benchmark and return a partial report."""
    board = board or detect_board()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    logger.info("Running RAG benchmark (model=%s, embedding=%s)", model, embedding_model)
    rag_result = _rag.run(
        model=model,
        embedding_model=embedding_model,
        ollama_url=ollama_url,
        chromadb_url=chromadb_url,
    )

    return BenchmarkReport(
        timestamp=timestamp,
        board=board,
        model=model,
        inference_tok_s=0.0,
        first_token_ms=0.0,
        rag_query_ms=rag_result.total_ms,
        memory_peak_mb=0.0,
        rag_embed_ms=rag_result.embed_ms,
        rag_retrieve_ms=rag_result.retrieve_ms,
        rag_generate_ms=rag_result.generate_ms,
        embedding_model=embedding_model,
    )


def run_system_only(board: str | None = None) -> BenchmarkReport:
    """Run only the system benchmark and return a partial report."""
    board = board or detect_board()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    logger.info("Running system benchmark")
    sys_result = _sys.run()

    return BenchmarkReport(
        timestamp=timestamp,
        board=board,
        model="",
        inference_tok_s=0.0,
        first_token_ms=0.0,
        rag_query_ms=0.0,
        memory_peak_mb=sys_result.memory_total_mb,
        cpu_score=sys_result.cpu_score,
        memory_read_mb_s=sys_result.memory_read_mb_s,
        disk_write_mb_s=sys_result.disk_write_mb_s,
        disk_read_mb_s=sys_result.disk_read_mb_s,
        memory_total_mb=sys_result.memory_total_mb,
        memory_available_mb=sys_result.memory_available_mb,
        platform_info=sys_result.platform_info,
    )


def run_all(
    model: str = _DEFAULT_MODEL,
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    chromadb_url: str = _DEFAULT_CHROMADB_URL,
    board: str | None = None,
) -> BenchmarkReport:
    """Run all benchmarks (inference + RAG + system) and return a combined report."""
    board = board or detect_board()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    logger.info("Running inference benchmark (model=%s)", model)
    inf_result = _inf.run(model=model, ollama_url=ollama_url, warmup=True)

    logger.info("Running RAG benchmark (model=%s, embedding=%s)", model, embedding_model)
    rag_result = _rag.run(
        model=model,
        embedding_model=embedding_model,
        ollama_url=ollama_url,
        chromadb_url=chromadb_url,
    )

    logger.info("Running system benchmark")
    sys_result = _sys.run()

    return BenchmarkReport(
        timestamp=timestamp,
        board=board,
        model=model,
        inference_tok_s=inf_result.throughput_tok_s,
        first_token_ms=inf_result.first_token_ms,
        rag_query_ms=rag_result.total_ms,
        memory_peak_mb=inf_result.memory_peak_mb,
        inference_total_ms=inf_result.total_ms,
        rag_embed_ms=rag_result.embed_ms,
        rag_retrieve_ms=rag_result.retrieve_ms,
        rag_generate_ms=rag_result.generate_ms,
        embedding_model=embedding_model,
        cpu_score=sys_result.cpu_score,
        memory_read_mb_s=sys_result.memory_read_mb_s,
        disk_write_mb_s=sys_result.disk_write_mb_s,
        disk_read_mb_s=sys_result.disk_read_mb_s,
        memory_total_mb=sys_result.memory_total_mb,
        memory_available_mb=sys_result.memory_available_mb,
        platform_info=sys_result.platform_info,
    )


def save_report(report: BenchmarkReport, reports_dir: str | Path = "reports") -> Path:
    """Write *report* as a JSON file under *reports_dir*.

    The filename is derived from the timestamp and model name to avoid
    collisions between runs.

    Returns
    -------
    Path
        Absolute path to the written file.
    """
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_model = report.model.replace(":", "-").replace("/", "-")
    safe_ts = report.timestamp.replace(":", "").replace("-", "").replace("T", "-")
    filename = f"benchmark-{safe_model}-{safe_ts}.json"
    path = out_dir / filename

    path.write_text(report.to_json(), encoding="utf-8")
    logger.info("Report saved to %s", path)
    return path.resolve()


def compare_reports(path1: str | Path, path2: str | Path) -> dict:
    """Load two JSON report files and return a side-by-side comparison dict.

    Each key maps to a sub-dict with ``before``, ``after``, and ``delta``
    (after - before) for numeric fields, or plain ``before``/``after`` strings
    for non-numeric fields.
    """
    data1 = json.loads(Path(path1).read_text(encoding="utf-8"))
    data2 = json.loads(Path(path2).read_text(encoding="utf-8"))

    numeric_fields = {
        "inference_tok_s",
        "first_token_ms",
        "rag_query_ms",
        "memory_peak_mb",
        "inference_total_ms",
        "rag_embed_ms",
        "rag_retrieve_ms",
        "rag_generate_ms",
    }

    comparison: dict = {}
    all_keys = sorted(set(data1) | set(data2))

    for key in all_keys:
        v1 = data1.get(key)
        v2 = data2.get(key)
        if key in numeric_fields and isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            comparison[key] = {
                "before": v1,
                "after": v2,
                "delta": round(v2 - v1, 3),
                "pct_change": round((v2 - v1) / v1 * 100, 1) if v1 != 0 else None,
            }
        else:
            comparison[key] = {"before": v1, "after": v2}

    return comparison


# ---------------------------------------------------------------------------
# Board detection
# ---------------------------------------------------------------------------


def detect_board() -> str:
    """Return a board identifier string based on the running environment.

    Detection order:
    1. ``BMT_BOARD`` environment variable (explicit override).
    2. Heuristics based on ``/proc/cpuinfo``, ``/sys/firmware/devicetree``,
       and ``platform.machine()``.
    3. Falls back to ``"unknown"``.
    """
    if env_board := os.getenv("BMT_BOARD"):
        return env_board

    machine = platform.machine().lower()
    if machine not in ("aarch64", "arm64"):
        # Running on non-ARM (e.g. developer machine).
        processor = platform.processor().lower()
        if "apple" in processor or "m1" in processor or "m2" in processor or "m3" in processor:
            return "apple-silicon"
        return f"non-arm64-{machine}"

    # Try device-tree model string (Linux on ARM).
    dt_model_path = Path("/sys/firmware/devicetree/base/model")
    if dt_model_path.exists():
        try:
            model_str = dt_model_path.read_text(encoding="utf-8", errors="replace").lower()
            if "jetson" in model_str:
                return "jetson-orin"
            if "rockchip" in model_str or "rk3588" in model_str:
                return "rk3588"
            if "raspberry" in model_str:
                return "pi5"
        except OSError:
            pass

    # Try /proc/cpuinfo Hardware field.
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        try:
            cpuinfo = cpuinfo_path.read_text(encoding="utf-8", errors="replace").lower()
            if "apple" in cpuinfo:
                return "apple-silicon"
            if "jetson" in cpuinfo:
                return "jetson-orin"
        except OSError:
            pass

    return "arm64-unknown"


# ---------------------------------------------------------------------------
# Utility: pretty-print comparison table
# ---------------------------------------------------------------------------


def format_comparison(comparison: dict) -> str:
    """Return a human-readable table from a :func:`compare_reports` result."""
    lines: list[str] = []
    col_w = [26, 14, 14, 12, 10]
    header = (
        _ljust("METRIC", col_w[0])
        + _ljust("BEFORE", col_w[1])
        + _ljust("AFTER", col_w[2])
        + _ljust("DELTA", col_w[3])
        + _ljust("CHG %", col_w[4])
    )
    sep = "  ".join("-" * w for w in col_w)
    lines.append(header)
    lines.append(sep)

    for key, val in comparison.items():
        before = val.get("before", "")
        after = val.get("after", "")
        delta = val.get("delta", "")
        pct = val.get("pct_change", "")

        before_s = _fmt_num(before)
        after_s = _fmt_num(after)
        delta_s = _fmt_num(delta) if delta != "" else ""
        pct_s = f"{pct:+.1f}%" if isinstance(pct, (int, float)) else ""

        lines.append(
            _ljust(key, col_w[0])
            + _ljust(before_s, col_w[1])
            + _ljust(after_s, col_w[2])
            + _ljust(delta_s, col_w[3])
            + _ljust(pct_s, col_w[4])
        )

    return "\n".join(lines)


def generate_markdown_report(
    report: BenchmarkReport,
    baseline_path: str | Path | None = None,
) -> str:
    """Generate a markdown summary report from *report*.

    When *baseline_path* points to a previous JSON report, a comparison
    table is appended to the summary showing deltas against the baseline.

    Parameters
    ----------
    report:
        The benchmark report to summarise.
    baseline_path:
        Optional path to a previous JSON report for comparison.

    Returns
    -------
    str
        Markdown-formatted report text.
    """
    lines: list[str] = []
    lines.append("# BMT AI OS Benchmark Report")
    lines.append("")
    lines.append(f"**Timestamp:** {report.timestamp}  ")
    lines.append(f"**Board:** {report.board}  ")
    if report.model:
        lines.append(f"**Model:** `{report.model}`  ")
    if report.platform_info:
        lines.append(f"**Platform:** {report.platform_info}  ")
    lines.append("")

    # --- Inference section ---
    if report.inference_tok_s > 0 or report.first_token_ms > 0:
        lines.append("## Inference")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Throughput | {report.inference_tok_s:.1f} tok/s |")
        lines.append(f"| First token latency | {report.first_token_ms:.0f} ms |")
        lines.append(f"| Total generation time | {report.inference_total_ms:.0f} ms |")
        lines.append(f"| Peak memory | {report.memory_peak_mb:.0f} MB |")
        lines.append("")

    # --- RAG section ---
    if report.rag_query_ms > 0:
        lines.append("## RAG Pipeline")
        lines.append("")
        lines.append("| Stage | Latency |")
        lines.append("|-------|---------|")
        lines.append(f"| Embed | {report.rag_embed_ms:.0f} ms |")
        lines.append(f"| Retrieve | {report.rag_retrieve_ms:.0f} ms |")
        lines.append(f"| Generate | {report.rag_generate_ms:.0f} ms |")
        lines.append(f"| **Total** | **{report.rag_query_ms:.0f} ms** |")
        if report.embedding_model:
            lines.append("")
            lines.append(f"_Embedding model: `{report.embedding_model}`_")
        lines.append("")

    # --- System section ---
    if report.cpu_score > 0 or report.memory_total_mb > 0:
        lines.append("## System")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        if report.cpu_score > 0:
            lines.append(f"| CPU score | {report.cpu_score:.2f} iter/ms |")
        if report.memory_read_mb_s > 0:
            lines.append(f"| Memory read | {report.memory_read_mb_s:.0f} MB/s |")
        if report.disk_write_mb_s > 0:
            lines.append(f"| Disk write | {report.disk_write_mb_s:.0f} MB/s |")
        if report.disk_read_mb_s > 0:
            lines.append(f"| Disk read | {report.disk_read_mb_s:.0f} MB/s |")
        if report.memory_total_mb > 0:
            lines.append(f"| Total RAM | {report.memory_total_mb:.0f} MB |")
        if report.memory_available_mb > 0:
            lines.append(f"| Available RAM | {report.memory_available_mb:.0f} MB |")
        lines.append("")

    # --- Comparison section ---
    if baseline_path is not None:
        baseline = Path(baseline_path)
        if baseline.exists():
            lines.append("## Comparison to Baseline")
            lines.append("")
            try:
                comparison = compare_reports(baseline, _report_to_tmp_path(report))
                lines.append("```")
                lines.append(format_comparison(comparison))
                lines.append("```")
            except Exception as exc:
                lines.append(f"_Comparison unavailable: {exc}_")
            lines.append("")

    lines.append("---")
    lines.append("_Generated by BMT AI OS benchmark suite_")
    return "\n".join(lines)


def save_markdown_report(
    report: BenchmarkReport,
    reports_dir: str | Path = "reports",
    baseline_path: str | Path | None = None,
) -> Path:
    """Write a markdown summary for *report* under *reports_dir*.

    Returns
    -------
    Path
        Absolute path to the written ``.md`` file.
    """
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_model = report.model.replace(":", "-").replace("/", "-") if report.model else "system"
    safe_ts = report.timestamp.replace(":", "").replace("-", "").replace("T", "-")
    filename = f"benchmark-{safe_model}-{safe_ts}.md"
    path = out_dir / filename

    md = generate_markdown_report(report, baseline_path=baseline_path)
    path.write_text(md, encoding="utf-8")
    logger.info("Markdown report saved to %s", path)
    return path.resolve()


def _report_to_tmp_path(report: BenchmarkReport) -> Path:
    """Write *report* to a temporary JSON file and return its path."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(report.to_json())
        return Path(fh.name)


def _ljust(text: str, width: int) -> str:
    return str(text).ljust(width)


def _fmt_num(val: object) -> str:
    if isinstance(val, float):
        return f"{val:.2f}"
    if isinstance(val, int):
        return str(val)
    return str(val) if val is not None else ""
