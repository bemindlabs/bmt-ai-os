"""BMT AI OS Controller — AI stack lifecycle orchestration.

Manages Ollama, ChromaDB, and other AI-stack containers defined in
docker-compose.yml. Provides health checking, auto-restart with
circuit breakers, and an HTTP API for status and control.
"""

import argparse
import importlib
import logging
import signal
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import docker
import uvicorn

from .api import app, set_controller
from .config import ControllerConfig, ServiceDef, load_config
from .health import HealthChecker, HealthStatus

logger = logging.getLogger("bmt-controller")

# Maps docker-compose service names to (module_path, class_name) for dynamic import.
# To add a new provider, add an entry here — no other changes required.
_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "ollama": ("bmt_ai_os.providers.ollama", "OllamaProvider"),
}


class BMTAIOSController:
    """Orchestrates AI stack containers on BMT AI OS."""

    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self.client = docker.from_env()
        self.health_checker = HealthChecker(config)
        self._shutdown_event = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._restart_counts: dict[str, int] = {svc.name: 0 for svc in config.services}
        self._start_time = time.time()

    # --- Compose helpers ---

    def _compose_cmd(self, *args: str) -> list[str]:
        """Build a docker compose command list."""
        return [
            "docker",
            "compose",
            "-f",
            self.config.compose_file,
            *args,
        ]

    def _run_compose(self, *args: str) -> subprocess.CompletedProcess:
        """Run a docker compose command and return the result."""
        cmd = self._compose_cmd(*args)
        logger.info("Running: %s", " ".join(cmd))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    # --- Stack lifecycle ---

    def start_stack(self) -> None:
        """Start all AI stack services via docker compose."""
        logger.info("Starting AI stack from %s", self.config.compose_file)
        result = self._run_compose("up", "-d")
        if result.returncode != 0:
            logger.error("Failed to start stack: %s", result.stderr)
        else:
            logger.info("AI stack started successfully")

    def stop_stack(self) -> None:
        """Stop all AI stack services via docker compose."""
        logger.info("Stopping AI stack")
        result = self._run_compose("down")
        if result.returncode != 0:
            logger.error("Failed to stop stack: %s", result.stderr)
        else:
            logger.info("AI stack stopped")

    def restart_stack(self) -> None:
        """Restart the entire AI stack."""
        logger.info("Restarting AI stack")
        self.stop_stack()
        self.start_stack()

    def restart_service(self, name: str) -> bool:
        """Restart a single AI stack service by name."""
        svc = self._find_service(name)
        if not svc:
            logger.error("Unknown service: %s", name)
            return False

        logger.info("Restarting service %s (container: %s)", name, svc.container_name)
        result = self._run_compose("restart", name)
        if result.returncode != 0:
            logger.error("Failed to restart %s: %s", name, result.stderr)
            return False

        self._restart_counts[name] = self._restart_counts.get(name, 0) + 1
        self.health_checker.reset_failures(name)
        logger.info("Service %s restarted (total restarts: %d)", name, self._restart_counts[name])
        return True

    # --- Status ---

    def get_status(self) -> list[dict]:
        """Return JSON-serializable status of all managed services."""
        statuses = []
        for svc in self.config.services:
            info = self._get_container_info(svc)
            history = self.health_checker.get_history(svc.name)
            last_health = history[-1] if history else None
            circuit = self.health_checker.get_circuit_state(svc.name)

            statuses.append(
                {
                    "name": svc.name,
                    "container_name": svc.container_name,
                    "state": info.get("state", "unknown"),
                    "health": last_health.status.value if last_health else "unknown",
                    "uptime_seconds": info.get("uptime_seconds"),
                    "restarts": self._restart_counts.get(svc.name, 0),
                    "circuit_breaker": circuit.value,
                    "last_check_ms": round(last_health.response_time_ms, 1)
                    if last_health
                    else None,
                    "last_error": last_health.error if last_health and last_health.error else None,
                }
            )
        return statuses

    def _get_container_info(self, svc: ServiceDef) -> dict:
        """Get container state and uptime from Docker."""
        try:
            container = self.client.containers.get(svc.container_name)
            state = container.status  # running, exited, paused, etc.
            started_at = container.attrs.get("State", {}).get("StartedAt", "")
            uptime = None
            if started_at and state == "running":
                try:
                    start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    uptime = (datetime.now(timezone.utc) - start_dt).total_seconds()
                except (ValueError, TypeError):
                    pass
            return {"state": state, "uptime_seconds": uptime}
        except docker.errors.NotFound:
            return {"state": "not_found", "uptime_seconds": None}
        except docker.errors.DockerException as exc:
            logger.warning("Docker error checking %s: %s", svc.name, exc)
            return {"state": "error", "uptime_seconds": None}

    def _find_service(self, name: str) -> ServiceDef | None:
        for svc in self.config.services:
            if svc.name == name:
                return svc
        return None

    # --- Health check loop ---

    def _health_loop(self) -> None:
        """Background thread: periodically check services and auto-restart."""
        logger.info(
            "Health check loop started (interval=%ds, max_restarts=%d)",
            self.config.health_interval,
            self.config.max_restarts,
        )
        while not self._shutdown_event.is_set():
            results = self.health_checker.check_all()
            for result in results:
                if result.status == HealthStatus.HEALTHY:
                    logger.debug(
                        "Service %s healthy (%.0fms)",
                        result.service,
                        result.response_time_ms,
                    )
                else:
                    logger.warning("Service %s unhealthy: %s", result.service, result.error)
                    if self.health_checker.needs_restart(result.service):
                        logger.info("Auto-restarting %s", result.service)
                        self.restart_service(result.service)

            self._shutdown_event.wait(timeout=self.config.health_interval)

        logger.info("Health check loop stopped")

    def start_health_checks(self) -> None:
        """Start the background health check thread."""
        self._health_thread = threading.Thread(
            target=self._health_loop, name="health-check", daemon=True
        )
        self._health_thread.start()

    def stop_health_checks(self) -> None:
        """Signal the health check thread to stop and wait for it."""
        self._shutdown_event.set()
        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=10)

    # --- Provider registration ---

    def _register_providers(self) -> None:
        """Auto-register LLM providers based on running AI-stack services.

        Each service whose name appears in _PROVIDER_MAP is imported and
        registered dynamically.  Adding a new provider only requires an entry
        in that map — no code changes here are needed.
        """
        try:
            from bmt_ai_os.providers.registry import get_registry

            registry = get_registry()

            for svc in self.config.services:
                mapping = _PROVIDER_MAP.get(svc.name)
                if mapping is None:
                    continue

                module_path, class_name = mapping
                try:
                    module = importlib.import_module(module_path)
                    provider_cls = getattr(module, class_name)
                    base_url = f"http://localhost:{svc.port}"
                    provider = provider_cls(base_url=base_url)
                    registry.register(svc.name, provider)
                    logger.info(
                        "Registered provider '%s' (%s) at %s",
                        svc.name,
                        class_name,
                        base_url,
                    )
                except Exception as exc:
                    logger.warning("Failed to register provider '%s': %s", svc.name, exc)

            logger.info(
                "Provider registry: %s (active: %s)",
                registry.list(),
                registry.active_name,
            )
        except Exception as exc:
            logger.warning("Provider registration failed: %s", exc)

    # --- Signal handling & main loop ---

    def _handle_signal(self, signum: int, _frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, initiating graceful shutdown", sig_name)
        self.shutdown()

    def shutdown(self) -> None:
        """Graceful shutdown: stop health checks, stop stack, exit."""
        logger.info("Shutting down controller")
        self.stop_health_checks()
        self.stop_stack()
        logger.info("Controller shutdown complete")

    def run(self) -> None:
        """Main entry point: start stack, health checks, and API server."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("BMT AI OS Controller v0.1.0 starting")
        logger.info("Compose file: %s", self.config.compose_file)
        logger.info("API server: %s:%d", self.config.api_host, self.config.api_port)

        # Start the AI stack
        self.start_stack()

        # Register LLM providers from running services
        self._register_providers()

        # Start background health checks
        self.start_health_checks()

        # Resolve TLS settings (opt-in via BMT_TLS_ENABLED=true).
        from bmt_ai_os.tls.config import load_tls_config

        tls_cfg = load_tls_config()

        # Attach controller to API and run the server (HTTP or HTTPS).
        set_controller(self)

        if tls_cfg.enabled:
            cert = tls_cfg.resolved_cert()
            key = tls_cfg.resolved_key()

            if not cert or not key:
                logger.error(
                    "TLS is enabled but certificate/key paths could not be resolved. "
                    "Set BMT_TLS_CERT / BMT_TLS_KEY or ensure auto-generation succeeds."
                )
                sys.exit(1)

            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            try:
                ssl_ctx.load_cert_chain(certfile=cert, keyfile=key)
            except (ssl.SSLError, OSError) as exc:
                logger.error("Failed to load TLS certificate/key: %s", exc)
                sys.exit(1)

            logger.info(
                "TLS enabled — HTTPS on %s:%d (cert=%s)",
                self.config.api_host,
                tls_cfg.port,
                cert,
            )
            uvicorn.run(
                app,
                host=self.config.api_host,
                port=tls_cfg.port,
                log_level=self.config.log_level.lower(),
                ssl_certfile=cert,
                ssl_keyfile=key,
            )
        else:
            logger.info("TLS disabled — HTTP only (set BMT_TLS_ENABLED=true to enable)")
            uvicorn.run(
                app,
                host=self.config.api_host,
                port=self.config.api_port,
                log_level=self.config.log_level.lower(),
            )


def _setup_logging(config: ControllerConfig) -> None:
    """Configure structured JSON logging with rotation for all subsystems.

    Uses :func:`bmt_ai_os.logging.configure_log_streams` to create separate
    rotating log files for controller, providers, health, and rag streams.
    Falls back to stdout when the log directory is not writable.

    Format is controlled by the ``BMT_LOG_FORMAT`` env variable:
    - ``json`` (default) — machine-parseable JSON for log aggregators
    - ``text`` — human-readable format for interactive use
    """
    from bmt_ai_os.logging import configure_log_streams

    log_dir = Path(config.log_file).parent

    configure_log_streams(
        log_dir=log_dir,
        level=config.log_level,
    )

    # Also configure the root bmt-controller logger so existing logger.info()
    # calls in this module route through the structured handler.
    from bmt_ai_os.logging import setup_logging

    setup_logging(
        "bmt-controller",
        log_dir=log_dir,
        level=config.log_level,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="BMT AI OS Controller")
    parser.add_argument(
        "-c",
        "--config",
        help="Path to controller.yml config file",
        default=None,
    )
    args = parser.parse_args()

    config = load_config(args.config)
    _setup_logging(config)

    controller = BMTAIOSController(config)
    controller.run()


if __name__ == "__main__":
    main()
