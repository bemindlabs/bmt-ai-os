"""BMT AI OS Controller — AI stack lifecycle orchestration.

Manages Ollama, ChromaDB, and other AI-stack containers defined in
docker-compose.yml. Provides health checking, auto-restart with
circuit breakers, and an HTTP API for status and control.
"""

import argparse
import logging
import signal
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


class BMTAIOSController:
    """Orchestrates AI stack containers on BMT AI OS."""

    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self.client = docker.from_env()
        self.health_checker = HealthChecker(config)
        self._shutdown_event = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._restart_counts: dict[str, int] = {
            svc.name: 0 for svc in config.services
        }
        self._start_time = time.time()

    # --- Compose helpers ---

    def _compose_cmd(self, *args: str) -> list[str]:
        """Build a docker compose command list."""
        return [
            "docker", "compose",
            "-f", self.config.compose_file,
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

            statuses.append({
                "name": svc.name,
                "container_name": svc.container_name,
                "state": info.get("state", "unknown"),
                "health": last_health.status.value if last_health else "unknown",
                "uptime_seconds": info.get("uptime_seconds"),
                "restarts": self._restart_counts.get(svc.name, 0),
                "circuit_breaker": circuit.value,
                "last_check_ms": round(last_health.response_time_ms, 1) if last_health else None,
                "last_error": last_health.error if last_health and last_health.error else None,
            })
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
                    logger.debug("Service %s healthy (%.0fms)", result.service, result.response_time_ms)
                else:
                    logger.warning(
                        "Service %s unhealthy: %s", result.service, result.error
                    )
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

        # Start background health checks
        self.start_health_checks()

        # Attach controller to API and run the HTTP server
        set_controller(self)
        uvicorn.run(
            app,
            host=self.config.api_host,
            port=self.config.api_port,
            log_level=self.config.log_level.lower(),
        )


def _setup_logging(config: ControllerConfig) -> None:
    """Configure structured logging to stdout and log file."""
    fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    log_path = Path(config.log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.log_file))
    except OSError:
        # Cannot write to log file (e.g. /var/log not writable), stdout only
        pass

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format=fmt,
        handlers=handlers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="BMT AI OS Controller")
    parser.add_argument(
        "-c", "--config",
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
