"""BMT AI OS CLI — `bmt-ai-os` command entry point.

Provides subcommands for managing the AI stack, models, providers, and
interactive chat. Uses synchronous HTTP (requests) and subprocess for
docker compose operations.
"""

import subprocess
import sys
from typing import Any

import click
import requests

from bmt_ai_os.benchmark import suite as _suite
from bmt_ai_os.controller.config import load_config

__version__ = "2026.4.10"

_OLLAMA_BASE = "http://localhost:11434"
_CHROMADB_BASE = "http://localhost:8000"
_OPENAI_COMPAT_BASE = "http://localhost:8080"
_DEFAULT_TIMEOUT = 5  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_config():
    """Return a loaded ControllerConfig, silently using defaults on failure."""
    try:
        return load_config()
    except Exception:
        from bmt_ai_os.controller.config import ControllerConfig

        return ControllerConfig()


def _http_get(url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    """GET *url* and return parsed JSON, or None on any error."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None


def _http_post(url: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any] | None:
    """POST *payload* as JSON to *url* and return parsed JSON, or None on error."""
    try:
        resp = requests.post(url, json=payload, timeout=timeout, stream=False)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _run_compose(args: list[str], compose_file: str) -> int:
    """Run `docker compose -f <compose_file> <args>` and stream output.

    Returns the process exit code.
    """
    cmd = ["docker", "compose", "-f", compose_file] + args
    result = subprocess.run(cmd)
    return result.returncode


def _fmt_col(value: str, width: int) -> str:
    """Left-justify *value* in a column of *width* characters."""
    return value.ljust(width)


def _separator(widths: list[int]) -> str:
    return "  ".join("-" * w for w in widths)


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------


@click.group()
def main() -> None:
    """BMT AI OS — AI-first operating system for ARM64."""


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@main.command()
def version() -> None:
    """Show the BMT AI OS version."""
    click.echo(f"bmt-ai-os  {__version__}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show system status: services, models, and active provider."""
    cfg = _get_config()

    click.echo("BMT AI OS — System Status")
    click.echo("=" * 50)

    # Services
    click.echo("\nServices:")
    col_w = [12, 8, 30]
    click.echo(
        "  "
        + "  ".join(
            [
                _fmt_col("NAME", col_w[0]),
                _fmt_col("STATUS", col_w[1]),
                _fmt_col("URL", col_w[2]),
            ]
        )
    )
    click.echo("  " + _separator(col_w))

    for svc in cfg.services:
        data = _http_get(svc.health_url, timeout=cfg.health_timeout)
        status_str = "UP" if data is not None else "DOWN"
        click.echo(
            "  "
            + "  ".join(
                [
                    _fmt_col(svc.name, col_w[0]),
                    _fmt_col(status_str, col_w[1]),
                    _fmt_col(svc.health_url, col_w[2]),
                ]
            )
        )

    # Models (best-effort)
    click.echo("\nLoaded models (Ollama):")
    tags = _http_get(f"{_OLLAMA_BASE}/api/tags")
    if tags and "models" in tags:
        models = tags["models"]
        if models:
            for m in models:
                click.echo(f"  - {m.get('name', 'unknown')}")
        else:
            click.echo("  (no models loaded)")
    else:
        click.echo("  (Ollama unreachable)")

    # Provider
    click.echo("\nProvider API (OpenAI-compat):")
    info = _http_get(f"{_OPENAI_COMPAT_BASE}/v1/models")
    if info:
        provider_models = [m.get("id", "?") for m in info.get("data", [])]
        click.echo(f"  Reachable — models: {', '.join(provider_models) or 'none'}")
    else:
        click.echo("  Unreachable (start with: bmt-ai-os stack up)")


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


@main.group()
def models() -> None:
    """Manage Ollama models."""


@models.command("list")
def models_list() -> None:
    """List models available in Ollama."""
    data = _http_get(f"{_OLLAMA_BASE}/api/tags")
    if data is None:
        click.echo("Error: cannot reach Ollama at " + _OLLAMA_BASE, err=True)
        sys.exit(1)

    model_list = data.get("models", [])
    if not model_list:
        click.echo("No models found. Pull one with: bmt-ai-os models pull <name>")
        return

    col_w = [40, 12, 16]
    click.echo(
        "  ".join(
            [
                _fmt_col("NAME", col_w[0]),
                _fmt_col("SIZE", col_w[1]),
                _fmt_col("MODIFIED", col_w[2]),
            ]
        )
    )
    click.echo(_separator(col_w))

    for m in model_list:
        name = m.get("name", "unknown")
        size_bytes = m.get("size", 0)
        size_str = f"{size_bytes / 1_073_741_824:.1f} GB" if size_bytes else "?"
        modified = (m.get("modified_at", "") or "")[:16]
        click.echo(
            "  ".join(
                [
                    _fmt_col(name, col_w[0]),
                    _fmt_col(size_str, col_w[1]),
                    _fmt_col(modified, col_w[2]),
                ]
            )
        )


@models.command("pull")
@click.argument("model_name")
def models_pull(model_name: str) -> None:
    """Pull MODEL_NAME from Ollama registry.

    Example: bmt-ai-os models pull qwen2.5-coder:7b
    """
    click.echo(f"Pulling model: {model_name}")
    click.echo("This may take a while for large models...\n")

    # Ollama pull streams NDJSON; stream line by line for progress.
    url = f"{_OLLAMA_BASE}/api/pull"
    try:
        with requests.post(url, json={"name": model_name}, stream=True, timeout=3600) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                import json

                try:
                    evt = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                status = evt.get("status", "")
                completed = evt.get("completed", 0)
                total = evt.get("total", 0)

                if total and completed:
                    pct = completed / total * 100
                    click.echo(f"\r  {status}: {pct:.1f}%", nl=False)
                else:
                    click.echo(f"  {status}")

    except requests.exceptions.ConnectionError:
        click.echo(f"Error: cannot reach Ollama at {_OLLAMA_BASE}", err=True)
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"\nModel '{model_name}' pulled successfully.")


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


@main.command()
@click.option("--model", "-m", default=None, help="Model name (default: first available)")
def chat(model: str | None) -> None:
    """Interactive chat with the active provider (Ollama).

    Type 'exit' or press Ctrl-C to quit.
    """
    # Resolve model
    if model is None:
        tags = _http_get(f"{_OLLAMA_BASE}/api/tags")
        if not tags or not tags.get("models"):
            click.echo("Error: Ollama unreachable or no models loaded.", err=True)
            click.echo("Hint: bmt-ai-os models pull qwen2.5-coder:7b")
            sys.exit(1)
        model = tags["models"][0]["name"]

    click.echo(f"Chatting with model: {model}")
    click.echo("Type 'exit' or press Ctrl-C to quit.\n")

    history: list[dict[str, str]] = []

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix=" > ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nGoodbye.")
            break

        if user_input.strip().lower() in {"exit", "quit", "q"}:
            click.echo("Goodbye.")
            break

        history.append({"role": "user", "content": user_input})

        payload = {
            "model": model,
            "messages": history,
            "stream": False,
        }

        resp = _http_post(f"{_OLLAMA_BASE}/api/chat", payload, timeout=120)
        if resp is None:
            click.echo("Error: no response from Ollama.", err=True)
            continue

        assistant_msg = resp.get("message", {}).get("content", "(no content)")
        history.append({"role": "assistant", "content": assistant_msg})
        click.echo(f"\nAssistant > {assistant_msg}\n")


# ---------------------------------------------------------------------------
# stack
# ---------------------------------------------------------------------------


@main.group()
def stack() -> None:
    """Manage the AI stack via docker compose."""


@stack.command("up")
@click.option("--build", is_flag=True, default=False, help="Rebuild images before starting.")
def stack_up(build: bool) -> None:
    """Start the AI stack (docker compose up -d)."""
    cfg = _get_config()
    args = ["up", "-d"]
    if build:
        args.append("--build")
    click.echo(f"Starting AI stack from: {cfg.compose_file}")
    rc = _run_compose(args, cfg.compose_file)
    if rc != 0:
        sys.exit(rc)


@stack.command("down")
@click.option("--volumes", "-v", is_flag=True, default=False, help="Also remove volumes.")
def stack_down(volumes: bool) -> None:
    """Stop the AI stack (docker compose down)."""
    cfg = _get_config()
    args = ["down"]
    if volumes:
        args.append("-v")
    click.echo(f"Stopping AI stack from: {cfg.compose_file}")
    rc = _run_compose(args, cfg.compose_file)
    if rc != 0:
        sys.exit(rc)


@stack.command("ps")
def stack_ps() -> None:
    """Show running container status (docker compose ps)."""
    cfg = _get_config()
    _run_compose(["ps"], cfg.compose_file)


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------


@main.command()
def providers() -> None:
    """List configured providers and the active provider."""
    cfg = _get_config()

    click.echo("Configured providers:\n")

    # Static list from the known provider modules; active = what OpenAI-compat exposes.
    known: list[tuple[str, str, int]] = [
        ("ollama", "http://localhost:11434", 11434),
        ("openai-compat", f"http://localhost:{cfg.api_port}", cfg.api_port),
        ("chromadb", "http://localhost:8000", 8000),
    ]

    col_w = [16, 32, 8]
    click.echo(
        "  ".join(
            [
                _fmt_col("PROVIDER", col_w[0]),
                _fmt_col("URL", col_w[1]),
                _fmt_col("STATUS", col_w[2]),
            ]
        )
    )
    click.echo(_separator(col_w))

    for name, url, _port in known:
        paths = {"ollama": "/api/tags", "chromadb": "/api/v1/heartbeat"}
        probe_url = url + paths.get(name, "/v1/models")
        data = _http_get(probe_url)
        status_str = "UP" if data is not None else "DOWN"
        click.echo(
            "  ".join(
                [
                    _fmt_col(name, col_w[0]),
                    _fmt_col(url, col_w[1]),
                    _fmt_col(status_str, col_w[2]),
                ]
            )
        )

    # Indicate active provider
    click.echo(f"\nActive provider API: http://localhost:{cfg.api_port} (OpenAI-compatible)")


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------


@main.group()
def benchmark() -> None:
    """Performance benchmarking suite for BMT AI OS."""


@benchmark.command("run")
@click.option(
    "--model",
    "-m",
    default="qwen2.5:0.5b",
    show_default=True,
    help="Ollama model tag to benchmark.",
)
@click.option(
    "--embedding-model",
    default="nomic-embed-text",
    show_default=True,
    help="Ollama embedding model for the RAG stage.",
)
@click.option(
    "--ollama-url",
    default=_OLLAMA_BASE,
    show_default=True,
    help="Ollama base URL.",
)
@click.option(
    "--chromadb-url",
    default=_CHROMADB_BASE,
    show_default=True,
    help="ChromaDB base URL.",
)
@click.option(
    "--board",
    default=None,
    help="Board identifier (auto-detected when omitted).",
)
@click.option(
    "--reports-dir",
    default="reports",
    show_default=True,
    help="Directory to write the JSON report into.",
)
def benchmark_run(
    model: str,
    embedding_model: str,
    ollama_url: str,
    chromadb_url: str,
    board: str | None,
    reports_dir: str,
) -> None:
    """Run the full benchmark suite and save results to reports/.

    Runs inference (throughput, first-token latency) and RAG (embed + retrieve
    + generate) benchmarks, then writes a JSON report.
    """
    click.echo(f"Running full benchmark suite (model={model})...")
    try:
        report = _suite.run_full(
            model=model,
            embedding_model=embedding_model,
            ollama_url=ollama_url,
            chromadb_url=chromadb_url,
            board=board,
        )
    except RuntimeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo("\nResults:")
    click.echo(f"  Board:           {report.board}")
    click.echo(f"  Model:           {report.model}")
    click.echo(f"  Throughput:      {report.inference_tok_s:.1f} tok/s")
    click.echo(f"  First token:     {report.first_token_ms:.0f} ms")
    click.echo(f"  RAG query:       {report.rag_query_ms:.0f} ms")
    click.echo(f"  Memory peak:     {report.memory_peak_mb:.0f} MB")

    saved_path = _suite.save_report(report, reports_dir=reports_dir)
    click.echo(f"\nReport saved to: {saved_path}")


@benchmark.command("inference")
@click.option(
    "--model",
    "-m",
    default="qwen2.5:0.5b",
    show_default=True,
    help="Ollama model tag to benchmark.",
)
@click.option(
    "--ollama-url",
    default=_OLLAMA_BASE,
    show_default=True,
    help="Ollama base URL.",
)
@click.option(
    "--board",
    default=None,
    help="Board identifier (auto-detected when omitted).",
)
@click.option(
    "--reports-dir",
    default="reports",
    show_default=True,
    help="Directory to write the JSON report into.",
)
@click.option(
    "--no-save",
    is_flag=True,
    default=False,
    help="Print results only; do not write a report file.",
)
def benchmark_inference(
    model: str,
    ollama_url: str,
    board: str | None,
    reports_dir: str,
    no_save: bool,
) -> None:
    """Benchmark inference throughput and first-token latency only.

    Example: bmt-ai-os benchmark inference --model qwen2.5:0.5b
    """
    click.echo(f"Running inference benchmark (model={model})...")
    try:
        report = _suite.run_inference_only(
            model=model,
            ollama_url=ollama_url,
            board=board,
        )
    except RuntimeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo("\nResults:")
    click.echo(f"  Board:       {report.board}")
    click.echo(f"  Model:       {report.model}")
    click.echo(f"  Throughput:  {report.inference_tok_s:.1f} tok/s")
    click.echo(f"  First token: {report.first_token_ms:.0f} ms")
    click.echo(f"  Total time:  {report.inference_total_ms:.0f} ms")
    click.echo(f"  Memory peak: {report.memory_peak_mb:.0f} MB")

    if not no_save:
        saved_path = _suite.save_report(report, reports_dir=reports_dir)
        click.echo(f"\nReport saved to: {saved_path}")


@benchmark.command("compare")
@click.argument("file1", type=click.Path(exists=True, dir_okay=False))
@click.argument("file2", type=click.Path(exists=True, dir_okay=False))
def benchmark_compare(file1: str, file2: str) -> None:
    """Compare two benchmark report JSON files side by side.

    FILE1 is treated as the baseline (before) and FILE2 as the new result
    (after).  Numeric deltas and percentage changes are shown for all metrics.

    Example: bmt-ai-os benchmark compare reports/old.json reports/new.json
    """
    try:
        comparison = _suite.compare_reports(file1, file2)
    except (OSError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Comparing:\n  before: {file1}\n  after:  {file2}\n")
    click.echo(_suite.format_comparison(comparison))


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@main.command()
def health() -> None:
    """Run health checks on all configured services."""
    cfg = _get_config()

    click.echo("Running health checks...\n")

    all_healthy = True
    col_w = [14, 8, 40]
    click.echo(
        "  ".join(
            [
                _fmt_col("SERVICE", col_w[0]),
                _fmt_col("RESULT", col_w[1]),
                _fmt_col("DETAIL", col_w[2]),
            ]
        )
    )
    click.echo(_separator(col_w))

    for svc in cfg.services:
        data = _http_get(svc.health_url, timeout=cfg.health_timeout)
        if data is not None:
            result = "OK"
            detail = f"responded at {svc.health_url}"
        else:
            result = "FAIL"
            detail = f"no response from {svc.health_url}"
            all_healthy = False

        click.echo(
            "  ".join(
                [
                    _fmt_col(svc.name, col_w[0]),
                    _fmt_col(result, col_w[1]),
                    _fmt_col(detail, col_w[2]),
                ]
            )
        )

    click.echo()
    if all_healthy:
        click.echo("All services healthy.")
    else:
        click.echo("One or more services are DOWN. Run `bmt-ai-os stack up` to start them.")
        sys.exit(1)
