"""BMT AI OS CLI — `bmt-ai-os` command entry point.

Provides subcommands for managing the AI stack, models, providers,
interactive chat, and OTA updates. Uses synchronous HTTP (requests) and
subprocess for docker compose operations.
"""

import os
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


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


@main.command()
@click.option("-s", "--service", default="controller", help="Service name")
@click.option("-n", "--tail", "tail_n", default=50, type=int, help="Last N lines")
@click.option("--json", "json_mode", is_flag=True, help="Raw JSON output")
@click.option("--log-dir", default=None, help="Override log directory")
def logs(service: str, tail_n: int, json_mode: bool, log_dir: str | None) -> None:
    """View service logs."""
    import json as json_mod
    from pathlib import Path

    search_dirs = [Path(log_dir)] if log_dir else [Path("/var/log/bmt"), Path("/tmp/bmt-logs")]
    log_file = None
    for d in search_dirs:
        candidate = d / f"{service}.log"
        if candidate.exists():
            log_file = candidate
            break

    if not log_file:
        click.echo(f"Log file not found for service '{service}'", err=True)
        paths = ", ".join(str(d / f"{service}.log") for d in search_dirs)
        click.echo(f"Searched: {paths}", err=True)
        sys.exit(1)

    lines = log_file.read_text().splitlines()
    lines = lines[-tail_n:] if tail_n < len(lines) else lines

    for line in lines:
        if not line.strip():
            continue
        if json_mode:
            click.echo(line)
        else:
            try:
                rec = json_mod.loads(line)
                ts = rec.get("ts", "")
                level = rec.get("level", "").ljust(8)
                msg = rec.get("msg", "")
                tid = rec.get("trace_id", "")
                tid_str = f"  [trace_id={tid}]" if tid else ""
                click.echo(f"{ts}  {level}  {msg}{tid_str}")
            except (json_mod.JSONDecodeError, TypeError):
                click.echo(line)


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
# user management
# ---------------------------------------------------------------------------


@main.group()
def user() -> None:
    """Manage BMT AI OS users (authentication / RBAC)."""


@user.command("create")
@click.argument("username")
@click.option(
    "--role",
    "-r",
    default="viewer",
    show_default=True,
    type=click.Choice(["admin", "operator", "viewer"], case_sensitive=False),
    help="Role to assign to the new user.",
)
@click.option(
    "--db",
    default=None,
    envvar="BMT_AUTH_DB",
    help="Path to the auth SQLite database (default: /tmp/bmt-auth.db).",
)
def user_create(username: str, role: str, db: str | None) -> None:
    """Create a new user USERNAME and prompt for a password.

    Example: bmt-ai-os user create alice --role admin
    """
    from bmt_ai_os.controller.auth import UserStore

    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if not password:
        click.echo("Error: password must not be empty.", err=True)
        sys.exit(1)

    store = UserStore(db_path=db)
    try:
        created = store.create_user(username, password, role)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"User '{created.username}' created with role '{created.role.value}'.")


@user.command("list")
@click.option(
    "--db",
    default=None,
    envvar="BMT_AUTH_DB",
    help="Path to the auth SQLite database.",
)
def user_list(db: str | None) -> None:
    """List all registered users."""
    from bmt_ai_os.controller.auth import UserStore

    store = UserStore(db_path=db)
    users = store.list_users()

    if not users:
        click.echo("No users registered.")
        return

    col_w = [20, 10, 28]
    click.echo(
        "  ".join(
            [
                _fmt_col("USERNAME", col_w[0]),
                _fmt_col("ROLE", col_w[1]),
                _fmt_col("CREATED AT", col_w[2]),
            ]
        )
    )
    click.echo(_separator(col_w))
    for u in users:
        click.echo(
            "  ".join(
                [
                    _fmt_col(u.username, col_w[0]),
                    _fmt_col(u.role.value, col_w[1]),
                    _fmt_col(u.created_at[:19], col_w[2]),
                ]
            )
        )


@user.command("delete")
@click.argument("username")
@click.option(
    "--db",
    default=None,
    envvar="BMT_AUTH_DB",
    help="Path to the auth SQLite database.",
)
@click.confirmation_option(prompt="Are you sure you want to delete this user?")
def user_delete(username: str, db: str | None) -> None:
    """Delete user USERNAME from the store."""
    from bmt_ai_os.controller.auth import UserStore

    store = UserStore(db_path=db)
    if store.delete_user(username):
        click.echo(f"User '{username}' deleted.")
    else:
        click.echo(f"Error: user '{username}' not found.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# tls
# ---------------------------------------------------------------------------


@main.group()
def tls() -> None:
    """TLS certificate management for BMT AI OS."""


@tls.command("setup")
@click.option(
    "--cert-dir",
    default=None,
    envvar="BMT_TLS_DIR",
    help="Directory to store certificate files (default: /data/secrets/tls or /tmp/bmt-tls).",
)
@click.option(
    "--hostname",
    default=None,
    envvar="BMT_TLS_HOSTNAME",
    help="Hostname / CN for the certificate (default: system hostname).",
)
@click.option(
    "--days",
    default=365,
    show_default=True,
    type=int,
    help="Certificate validity in days.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing certificate and key.",
)
def tls_setup(cert_dir: str | None, hostname: str | None, days: int, force: bool) -> None:
    """Generate a self-signed TLS certificate for the controller API.

    Example: bmt-ai-os tls setup --hostname my-device.local --days 730
    """
    from pathlib import Path

    try:
        from bmt_ai_os.tls.certs import generate_self_signed
    except ImportError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if cert_dir is None:
        prod = Path("/data/secrets/tls")
        dev = Path("/tmp/bmt-tls")
        try:
            prod.mkdir(parents=True, exist_ok=True)
            probe = prod / ".write_probe"
            probe.touch()
            probe.unlink()
            base = prod
        except OSError:
            base = dev
    else:
        base = Path(cert_dir)

    cert_path = base / "server.crt"
    key_path = base / "server.key"

    if cert_path.exists() and key_path.exists() and not force:
        click.echo(f"Certificates already exist in {base}.")
        click.echo("Use --force to overwrite.")
        return

    if hostname is None:
        import socket

        try:
            hostname = socket.gethostname() or "localhost"
        except OSError:
            hostname = "localhost"

    try:
        generate_self_signed(cert_path, key_path, hostname=hostname, days=days)
    except Exception as exc:
        click.echo(f"Error generating certificate: {exc}", err=True)
        sys.exit(1)

    click.echo("Certificate generated successfully.")
    click.echo(f"  Cert : {cert_path}")
    click.echo(f"  Key  : {key_path}")
    click.echo(f"  CN   : {hostname}")
    click.echo(f"  Days : {days}")
    click.echo()
    click.echo("To enable TLS, set in your environment:")
    click.echo("  BMT_TLS_ENABLED=true")
    click.echo(f"  BMT_TLS_CERT={cert_path}")
    click.echo(f"  BMT_TLS_KEY={key_path}")


@tls.command("status")
def tls_status() -> None:
    """Show current TLS configuration and certificate details (expiry, CN).

    Example: bmt-ai-os tls status
    """
    import datetime
    from pathlib import Path

    from bmt_ai_os.tls.config import load_tls_config

    cfg = load_tls_config()

    click.echo("TLS Configuration")
    click.echo("=" * 50)
    click.echo(f"  Enabled       : {cfg.enabled}")
    click.echo(f"  Port          : {cfg.port}")
    click.echo(f"  Redirect HTTP : {cfg.redirect_http}")

    cert_display = cfg.resolved_cert() or cfg.cert_path or "(not set)"
    key_display = cfg.resolved_key() or cfg.key_path or "(not set)"
    click.echo(f"  Certificate   : {cert_display}")
    click.echo(f"  Key           : {key_display}")

    cert_path = cfg.resolved_cert() or cfg.cert_path
    if cert_path:
        p = Path(cert_path)
        if p.exists():
            try:
                from cryptography import x509

                cert_obj = x509.load_pem_x509_certificate(p.read_bytes())

                cn_attrs = cert_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
                cn = cn_attrs[0].value if cn_attrs else "(unknown)"

                not_after = cert_obj.not_valid_after_utc
                now = datetime.datetime.now(datetime.timezone.utc)
                remaining = (not_after - now).days

                click.echo()
                click.echo("Certificate Details")
                click.echo("=" * 50)
                click.echo(f"  CN            : {cn}")
                click.echo(
                    f"  Not before    : {cert_obj.not_valid_before_utc.strftime('%Y-%m-%d')}"
                )
                click.echo(f"  Expires       : {not_after.strftime('%Y-%m-%d')}")
                click.echo(f"  Days remaining: {remaining}")
                if remaining <= 30:
                    click.echo(
                        "  WARNING: Certificate expires soon. "
                        "Run `bmt-ai-os tls setup --force` to renew.",
                        err=True,
                    )

                try:
                    san_ext = cert_obj.extensions.get_extension_for_class(
                        x509.SubjectAlternativeName
                    )
                    sans: list[str] = san_ext.value.get_values_for_type(x509.DNSName) + [
                        str(ip) for ip in san_ext.value.get_values_for_type(x509.IPAddress)
                    ]
                    click.echo(f"  SANs          : {', '.join(sans)}")
                except x509.extensions.ExtensionNotFound:
                    pass

            except ImportError:
                click.echo("  (install 'cryptography>=43.0' for certificate details)")
            except Exception as exc:
                click.echo(f"  (error reading certificate: {exc})")
        else:
            click.echo()
            click.echo(f"  Certificate file not found: {cert_path}")
            click.echo("  Run `bmt-ai-os tls setup` to generate one.")
    else:
        click.echo()
        if not cfg.enabled:
            click.echo("TLS is disabled. Set BMT_TLS_ENABLED=true to enable.")
        else:
            click.echo("No certificate configured. Run `bmt-ai-os tls setup`.")


# ---------------------------------------------------------------------------
# plugin
# ---------------------------------------------------------------------------


@main.group()
def plugin() -> None:
    """Manage BMT AI OS plugins."""


@plugin.command("list")
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_PLUGIN_STATE",
    help="Path to plugin state JSON file (default: /tmp/bmt-plugins.json).",
)
def plugin_list(state_file: str | None) -> None:
    """Show all discovered plugins and their enabled/disabled state."""
    from bmt_ai_os.plugins.manager import PluginManager

    kwargs = {"state_file": state_file} if state_file else {}
    manager = PluginManager(**kwargs)
    plugins = manager.list_plugins()

    if not plugins:
        click.echo("No plugins discovered.")
        click.echo("Hint: install a package that declares entry-points in 'bmt_ai_os.plugins'.")
        return

    col_w = [28, 12, 16, 8]
    click.echo(
        "  ".join(
            [
                _fmt_col("NAME", col_w[0]),
                _fmt_col("VERSION", col_w[1]),
                _fmt_col("HOOK", col_w[2]),
                _fmt_col("ENABLED", col_w[3]),
            ]
        )
    )
    click.echo(_separator(col_w))
    for p in plugins:
        click.echo(
            "  ".join(
                [
                    _fmt_col(p.name, col_w[0]),
                    _fmt_col(p.version, col_w[1]),
                    _fmt_col(p.hook_type.value, col_w[2]),
                    _fmt_col("yes" if p.enabled else "no", col_w[3]),
                ]
            )
        )


@plugin.command("enable")
@click.argument("name")
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_PLUGIN_STATE",
    help="Path to plugin state JSON file.",
)
def plugin_enable(name: str, state_file: str | None) -> None:
    """Enable plugin NAME."""
    from bmt_ai_os.plugins.manager import PluginManager

    kwargs = {"state_file": state_file} if state_file else {}
    manager = PluginManager(**kwargs)
    try:
        manager.enable(name)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Plugin '{name}' enabled.")


@plugin.command("disable")
@click.argument("name")
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_PLUGIN_STATE",
    help="Path to plugin state JSON file.",
)
def plugin_disable(name: str, state_file: str | None) -> None:
    """Disable plugin NAME."""
    from bmt_ai_os.plugins.manager import PluginManager

    kwargs = {"state_file": state_file} if state_file else {}
    manager = PluginManager(**kwargs)
    try:
        manager.disable(name)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Plugin '{name}' disabled.")


# ---------------------------------------------------------------------------
# fleet
# ---------------------------------------------------------------------------

_FLEET_STATE_FILE = "/tmp/bmt-fleet-state.json"


def _load_fleet_state() -> dict:
    """Load persisted fleet registration state, or return empty dict."""
    import json as _json
    from pathlib import Path

    try:
        raw = Path(_FLEET_STATE_FILE).read_text()
        return _json.loads(raw)
    except (OSError, ValueError):
        return {}


def _save_fleet_state(state: dict) -> None:
    """Persist fleet registration state to a file."""
    import json as _json
    from pathlib import Path

    Path(_FLEET_STATE_FILE).write_text(_json.dumps(state, indent=2))


@main.group()
def fleet() -> None:
    """Fleet management — register this device and manage server communication."""


@fleet.command("register")
@click.option(
    "--server",
    required=True,
    metavar="URL",
    help="Fleet server base URL, e.g. https://fleet.example.com",
)
@click.option(
    "--device-id",
    default=None,
    help="Override auto-detected device ID.",
)
def fleet_register(server: str, device_id: str | None) -> None:
    """Enroll this device with the fleet server.

    Sends a registration request to SERVER and saves the server URL and
    device ID locally so subsequent commands can use them without flags.

    Example: bmt-ai-os fleet register --server https://fleet.example.com
    """
    import os as _os

    from bmt_ai_os.fleet.collector import get_device_id as _get_device_id
    from bmt_ai_os.fleet.collector import get_hardware_info

    resolved_id = device_id or _os.environ.get("BMT_FLEET_DEVICE_ID") or _get_device_id()
    server_url = server.rstrip("/")

    click.echo(f"Registering device {resolved_id} with fleet server: {server_url}")

    hardware = get_hardware_info()
    payload = {
        "device_id": resolved_id,
        "hostname": hardware.get("hostname", ""),
        "arch": hardware.get("arch", ""),
        "board": hardware.get("board", ""),
        "hardware": hardware,
    }

    url = f"{server_url}/api/v1/fleet/register"
    result = _http_post(url, payload)
    if result is None:
        click.echo(
            f"Warning: fleet server at {server_url} did not respond — "
            "saving config locally anyway.",
            err=True,
        )
    else:
        click.echo(f"Server responded: {result}")

    state = {"server_url": server_url, "device_id": resolved_id}
    _save_fleet_state(state)
    click.echo(f"Fleet config saved to {_FLEET_STATE_FILE}")
    click.echo(f"Device ID : {resolved_id}")
    click.echo(f"Server URL: {server_url}")


@fleet.command("status")
def fleet_status() -> None:
    """Show fleet connection status for this device.

    Displays the registered server URL, device ID, and the result of a
    lightweight connectivity probe to the fleet server.
    """
    import os as _os

    state = _load_fleet_state()
    server_url = state.get("server_url") or _os.environ.get("BMT_FLEET_SERVER", "")
    device_id = state.get("device_id") or _os.environ.get("BMT_FLEET_DEVICE_ID", "")

    if not server_url:
        click.echo(
            "Not registered. Run: bmt-ai-os fleet register --server <url>",
            err=True,
        )
        sys.exit(1)

    if not device_id:
        from bmt_ai_os.fleet.collector import get_device_id as _get_device_id

        device_id = _get_device_id()

    click.echo("Fleet Status")
    click.echo("=" * 40)
    click.echo(f"  Device ID : {device_id}")
    click.echo(f"  Server URL: {server_url}")

    # Probe the server health endpoint (best-effort).
    data = _http_get(f"{server_url}/api/v1/fleet/health")
    if data is not None:
        click.echo("  Connection: OK")
    else:
        fallback = _http_get(f"{server_url}/health")
        if fallback is not None:
            click.echo("  Connection: OK (via /health)")
        else:
            click.echo("  Connection: UNREACHABLE")


@fleet.command("heartbeat")
@click.option(
    "--server",
    default=None,
    metavar="URL",
    envvar="BMT_FLEET_SERVER",
    help="Fleet server URL (overrides saved registration).",
)
def fleet_heartbeat(server: str | None) -> None:
    """Send one heartbeat to the fleet server and print any returned command.

    Useful for testing connectivity and verifying that the server receives
    correct device telemetry without starting the background agent.

    Example: bmt-ai-os fleet heartbeat
    """
    import os as _os

    from bmt_ai_os.fleet.agent import FleetAgent

    state = _load_fleet_state()
    server_url = server or state.get("server_url") or _os.environ.get("BMT_FLEET_SERVER", "")
    device_id = state.get("device_id") or _os.environ.get("BMT_FLEET_DEVICE_ID")

    if not server_url:
        click.echo(
            "No fleet server configured. Run: bmt-ai-os fleet register --server <url>",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Sending heartbeat to: {server_url}")

    agent = FleetAgent(server_url=server_url, device_id=device_id)
    try:
        cmd = agent.send_heartbeat()
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo("Heartbeat sent successfully.")
    if not cmd.is_noop():
        click.echo(f"Server returned command: action={cmd.action!r} params={cmd.params}")
    else:
        click.echo("No command from server.")


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


# ---------------------------------------------------------------------------
# update (OTA)
# ---------------------------------------------------------------------------

_DEFAULT_OTA_SERVER = os.environ.get(
    "BMT_OTA_SERVER_URL",
    "https://releases.bemindlabs.com/bmt-ai-os/latest.json",
)


@main.group()
def update() -> None:
    """OTA update commands (A/B slot switching)."""


@update.command("check")
@click.option(
    "--server",
    default=_DEFAULT_OTA_SERVER,
    show_default=True,
    envvar="BMT_OTA_SERVER_URL",
    help="Release-info endpoint URL.",
)
def update_check(server: str) -> None:
    """Check whether a newer OS image is available.

    Queries the release server and prints the available version (if any).
    No download or write is performed.

    Example: bmt-ai-os update check
    """
    from bmt_ai_os.ota.engine import check_update, get_current_slot

    current_slot = get_current_slot()
    click.echo(f"Current slot : {current_slot}")
    click.echo(f"Querying     : {server}")

    info = check_update(server, current_version=__version__)
    if info is None:
        click.echo("No update available (already up to date or server unreachable).")
        return

    click.echo("\nUpdate available:")
    click.echo(f"  Version      : {info.version}")
    click.echo(f"  URL          : {info.url}")
    click.echo(f"  SHA-256      : {info.sha256}")
    if info.size_bytes:
        click.echo(f"  Size         : {info.size_bytes / 1_048_576:.1f} MB")
    if info.release_notes:
        click.echo(f"  Release notes: {info.release_notes}")
    click.echo("\nRun `bmt-ai-os update apply` to download and apply the update.")


@update.command("apply")
@click.option(
    "--server",
    default=_DEFAULT_OTA_SERVER,
    show_default=True,
    envvar="BMT_OTA_SERVER_URL",
    help="Release-info endpoint URL.",
)
@click.option(
    "--image-url",
    default=None,
    help="Direct image URL (skips the check step when provided).",
)
@click.option(
    "--sha256",
    "expected_sha256",
    default=None,
    help="Expected SHA-256 hex digest (required with --image-url).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Use file-backed slot store instead of writing to a block device.",
)
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_OTA_STATE_PATH",
    help="Override OTA state file path.",
)
def update_apply(
    server: str,
    image_url: str | None,
    expected_sha256: str | None,
    dry_run: bool,
    state_file: str | None,
) -> None:
    """Download and apply an OS update to the standby slot.

    The device will NOT reboot automatically.  After the next reboot,
    run `bmt-ai-os update confirm` to mark the new slot as healthy.

    Example: bmt-ai-os update apply --dry-run
    """
    import tempfile

    from bmt_ai_os.ota.engine import (
        UpdateInfo,
        apply_update,
        check_update,
        download_image,
        get_current_slot,
    )
    from bmt_ai_os.ota.state import StateManager

    sm = StateManager(path=state_file) if state_file else StateManager()
    current_slot = get_current_slot(sm)
    standby_slot = "b" if current_slot == "a" else "a"

    click.echo(f"Current slot : {current_slot}")
    click.echo(f"Target slot  : {standby_slot}")

    # Resolve image metadata.
    if image_url and expected_sha256:
        info = UpdateInfo(version="(manual)", url=image_url, sha256=expected_sha256)
    else:
        click.echo(f"Checking for updates at: {server}")
        info = check_update(server, current_version=__version__)
        if info is None:
            click.echo("No update available or server unreachable.")
            return
        click.echo(f"Update found : version {info.version}")

    # Download to a temp file.
    with tempfile.TemporaryDirectory(prefix="bmt-ota-") as tmpdir:
        dest = os.path.join(tmpdir, "update.img")

        click.echo(f"Downloading  : {info.url}")

        def _progress(received: int, total: int) -> None:
            if total:
                pct = received / total * 100
                click.echo(
                    f"\r  {received // 1_048_576} / {total // 1_048_576} MB  ({pct:.1f}%)",
                    nl=False,
                )
            else:
                click.echo(f"\r  {received // 1_048_576} MB received", nl=False)

        ok = download_image(info.url, dest, info.sha256, progress_cb=_progress)
        click.echo()  # newline after progress
        if not ok:
            click.echo("Error: download or checksum verification failed.", err=True)
            sys.exit(1)

        click.echo("Download OK.  Applying to standby slot...")
        ok = apply_update(dest, standby_slot, dry_run=dry_run, state_manager=sm)

    if not ok:
        click.echo("Error: failed to write image to standby slot.", err=True)
        sys.exit(1)

    click.echo(f"Update applied to slot '{standby_slot}'.")
    click.echo("Reboot the device, then run `bmt-ai-os update confirm` to confirm the new boot.")


@update.command("confirm")
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_OTA_STATE_PATH",
    help="Override OTA state file path.",
)
def update_confirm(state_file: str | None) -> None:
    """Confirm the current boot as healthy (reset bootcount).

    Call this after a successful reboot into the new slot to prevent
    automatic rollback to the previous slot.

    Example: bmt-ai-os update confirm
    """
    from bmt_ai_os.ota.engine import confirm_boot
    from bmt_ai_os.ota.state import StateManager

    sm = StateManager(path=state_file) if state_file else StateManager()
    confirm_boot(state_manager=sm)
    state = sm.load()
    click.echo(f"Boot confirmed for slot '{state.current_slot}'.")
    click.echo("Bootcount reset to 0.  Rollback protection disabled.")


@update.command("status")
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_OTA_STATE_PATH",
    help="Override OTA state file path.",
)
def update_status(state_file: str | None) -> None:
    """Show current OTA state (slots, bootcount, last update).

    Example: bmt-ai-os update status
    """
    from bmt_ai_os.ota.engine import get_current_slot
    from bmt_ai_os.ota.state import StateManager

    sm = StateManager(path=state_file) if state_file else StateManager()
    state = sm.load()
    active = get_current_slot(sm)

    click.echo("OTA Update Status")
    click.echo("=" * 40)
    click.echo(f"  Current slot   : {state.current_slot}")
    click.echo(f"  Standby slot   : {state.standby_slot}")
    click.echo(f"  Active slot    : {active}")
    click.echo(f"  Confirmed      : {'yes' if state.confirmed else 'no  (pending confirmation)'}")
    click.echo(f"  Bootcount      : {state.bootcount}")
    click.echo(f"  Last update    : {state.last_update or 'never'}")
    click.echo(f"  State file     : {sm.path}")


@update.command("run")
@click.option(
    "--server",
    default=_DEFAULT_OTA_SERVER,
    show_default=True,
    envvar="BMT_OTA_SERVER_URL",
    help="Release-info endpoint URL.",
)
@click.option(
    "--compose-file",
    default=None,
    envvar="BMT_COMPOSE_FILE",
    help="Docker Compose file for container image updates.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Use file-backed slot store instead of a real block device.",
)
@click.option(
    "--state-file",
    default=None,
    envvar="BMT_OTA_STATE_PATH",
    help="Override OTA state file path.",
)
@click.option(
    "--skip-containers",
    is_flag=True,
    default=False,
    help="Skip the docker compose pull stage.",
)
def update_run(
    server: str,
    compose_file: str | None,
    dry_run: bool,
    state_file: str | None,
    skip_containers: bool,
) -> None:
    """Full system update: OS rootfs + container images.

    Performs three steps in sequence:

    \b
    1. Checks the release server for a newer OS image.
    2. Downloads and writes it to the standby A/B partition.
    3. Pulls updated Docker container images (docker compose pull).

    Model data and ChromaDB data on /data are preserved automatically
    because they live on a separate data partition that is never modified
    during an update.

    After the next reboot, run `bmt-ai-os update confirm` to mark the
    new partition as healthy and disable automatic rollback.

    Example: bmt-ai-os update run --dry-run
    """
    import os as _os

    from bmt_ai_os.ota.state import StateManager
    from bmt_ai_os.update.orchestrator import UpdateOrchestrator

    sm = StateManager(path=state_file) if state_file else StateManager()

    # Resolve compose file: CLI flag > env > config default.
    resolved_compose = compose_file or _os.environ.get(
        "BMT_COMPOSE_FILE",
        str(
            next(
                (
                    p
                    for p in [
                        "/opt/bmt_ai_os/ai-stack/docker-compose.yml",
                        "bmt_ai_os/ai-stack/docker-compose.yml",
                    ]
                    if __import__("pathlib").Path(p).exists()
                ),
                "/opt/bmt_ai_os/ai-stack/docker-compose.yml",
            )
        ),
    )

    click.echo("BMT AI OS — Full System Update")
    click.echo("=" * 45)
    click.echo(f"  Server        : {server}")
    click.echo(f"  Compose file  : {resolved_compose}")
    click.echo(f"  Dry run       : {'yes' if dry_run else 'no'}")
    click.echo(f"  Skip containers: {'yes' if skip_containers else 'no'}")
    click.echo()

    orchestrator = UpdateOrchestrator(
        server_url=server,
        compose_file="" if skip_containers else resolved_compose,
        state_manager=sm,
        dry_run=dry_run,
    )

    result = orchestrator.run()

    # Print stage results.
    for stage in result.stages:
        if stage.skipped:
            status_label = "SKIP"
        elif stage.success:
            status_label = "OK  "
        else:
            status_label = "FAIL"
        click.echo(f"  [{status_label}] {stage.name}: {stage.message}")

    click.echo()
    if result.success:
        if result.new_version:
            click.echo(f"Update to version {result.new_version} applied successfully.")
            click.echo("Reboot the device, then run `bmt-ai-os update confirm`.")
        else:
            click.echo("System is already up to date.  No reboot required.")
    else:
        failed = [s.name for s in result.stages if not s.success and not s.skipped]
        click.echo(f"Update failed at stage(s): {', '.join(failed)}", err=True)
        sys.exit(1)
