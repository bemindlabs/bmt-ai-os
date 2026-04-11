"""System information collector for the fleet agent.

All functions are synchronous and have no external dependencies beyond the
stdlib and ``requests``.  ``psutil`` is used when available for accurate
resource metrics; if not installed the collector falls back to reading
``/proc`` directly (works on Linux/ARM64 targets).
"""

from __future__ import annotations

import logging
import os
import platform
import re
import socket
import uuid
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_MACHINE_ID_PATHS = [
    Path("/etc/machine-id"),
    Path("/var/lib/dbus/machine-id"),
]

_OLLAMA_BASE = "http://localhost:11434"
_CHROMADB_BASE = "http://localhost:8000"
_PROBE_TIMEOUT = 3  # seconds


# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------


def get_device_id() -> str:
    """Return a stable unique identifier for this device.

    Reads ``/etc/machine-id`` (standard on Linux/Alpine/systemd) or falls
    back to generating a UUID that is written to ``/tmp/bmt-device-id`` so
    it survives the process lifetime on hosts that lack ``machine-id``.
    """
    for path in _MACHINE_ID_PATHS:
        try:
            content = path.read_text().strip()
            if content:
                return content
        except OSError:
            pass

    # Fallback: persistent file in /tmp (survives reboots only when /tmp is
    # a real filesystem, but it's good enough for development/test).
    fallback = Path("/tmp/bmt-device-id")
    try:
        if fallback.exists():
            content = fallback.read_text().strip()
            if content:
                return content
        generated = str(uuid.uuid4())
        fallback.write_text(generated)
        return generated
    except OSError:
        # Last resort — ephemeral UUID (changes on each call, but safe).
        return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Hardware information
# ---------------------------------------------------------------------------


def _read_file_stripped(path: str) -> str:
    """Return stripped text from *path*, or empty string on error."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _detect_board() -> str:
    """Best-effort board identification from /proc/device-tree or uname."""
    model = _read_file_stripped("/proc/device-tree/model")
    if model:
        return model

    # Apple Silicon running Asahi Linux
    machine = platform.machine().lower()
    processor = platform.processor().lower()
    if "arm" in machine or "aarch64" in machine:
        if "apple" in processor:
            return "apple-silicon"
        return "arm64-generic"

    return platform.machine() or "unknown"


def _get_cpu_model() -> str:
    """Read CPU model from /proc/cpuinfo or platform."""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        for line in cpuinfo.splitlines():
            if re.match(r"(model name|Model name|Hardware|Processor)\s*:", line, re.I):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown"


def _get_cpu_cores() -> int:
    """Return the number of logical CPU cores."""
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _get_memory_total_mb() -> int:
    """Read total physical memory in MiB from /proc/meminfo."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return kb // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _get_disk_total_gb(path: str = "/") -> float:
    """Return total disk size for *path* in GiB."""
    try:
        st = os.statvfs(path)
        total_bytes = st.f_blocks * st.f_frsize
        return round(total_bytes / (1024**3), 1)
    except OSError:
        return 0.0


def get_hardware_info() -> dict[str, Any]:
    """Collect static hardware details.

    Returns a dict with keys: board, cpu_model, cpu_cores, memory_total_mb,
    disk_total_gb, arch, hostname.
    """
    return {
        "board": _detect_board(),
        "cpu_model": _get_cpu_model(),
        "cpu_cores": _get_cpu_cores(),
        "memory_total_mb": _get_memory_total_mb(),
        "disk_total_gb": _get_disk_total_gb(),
        "arch": platform.machine(),
        "hostname": socket.gethostname(),
    }


# ---------------------------------------------------------------------------
# Service health
# ---------------------------------------------------------------------------


def _probe(url: str) -> bool:
    """Return True if *url* responds with a 2xx status within the timeout."""
    try:
        resp = requests.get(url, timeout=_PROBE_TIMEOUT)
        return resp.ok
    except Exception:
        return False


def get_service_health() -> dict[str, str]:
    """Probe Ollama and ChromaDB endpoints.

    Returns a dict mapping service name to ``"up"`` or ``"down"``.
    """
    probes: dict[str, str] = {
        "ollama": f"{_OLLAMA_BASE}/api/tags",
        "chromadb": f"{_CHROMADB_BASE}/api/v1/heartbeat",
    }
    return {name: ("up" if _probe(url) else "down") for name, url in probes.items()}


# ---------------------------------------------------------------------------
# Loaded models
# ---------------------------------------------------------------------------


def get_loaded_models() -> list[str]:
    """Return the list of Ollama model names currently available.

    Returns an empty list when Ollama is unreachable.
    """
    try:
        resp = requests.get(f"{_OLLAMA_BASE}/api/tags", timeout=_PROBE_TIMEOUT)
        if resp.ok:
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Resource usage
# ---------------------------------------------------------------------------


def _cpu_percent_proc() -> float:
    """Estimate CPU usage from /proc/stat (two samples, 100 ms apart)."""
    import time

    def _read_stat() -> tuple[int, int]:
        try:
            line = Path("/proc/stat").read_text().splitlines()[0]
            parts = line.split()
            # user nice system idle iowait irq softirq steal guest guest_nice
            nums = [int(p) for p in parts[1:]]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            total = sum(nums)
            return idle, total
        except (OSError, ValueError, IndexError):
            return 0, 1  # avoid division by zero

    idle1, total1 = _read_stat()
    time.sleep(0.1)
    idle2, total2 = _read_stat()

    delta_total = total2 - total1
    delta_idle = idle2 - idle1
    if delta_total == 0:
        return 0.0
    return round((1.0 - delta_idle / delta_total) * 100, 1)


def _memory_percent_proc() -> float:
    """Return used memory percentage from /proc/meminfo."""
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            key, value_str = line.split(":", 1)
            try:
                info[key.strip()] = int(value_str.split()[0])
            except (ValueError, IndexError):
                pass
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        if total == 0:
            return 0.0
        return round((1.0 - available / total) * 100, 1)
    except (OSError, ValueError):
        return 0.0


def _disk_percent(path: str = "/") -> float:
    """Return used disk percentage for *path*."""
    try:
        st = os.statvfs(path)
        total = st.f_blocks
        free = st.f_bavail
        if total == 0:
            return 0.0
        return round((1.0 - free / total) * 100, 1)
    except OSError:
        return 0.0


def get_resource_usage() -> dict[str, float]:
    """Return current CPU, memory, and disk usage as percentages.

    Tries ``psutil`` first for accuracy; falls back to /proc parsing so
    the collector works on Alpine Linux without pip extras.

    Returns a dict with keys: cpu_percent, memory_percent, disk_percent.
    """
    try:
        import psutil  # type: ignore[import]

        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        return {
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(mem, 1),
            "disk_percent": round(disk, 1),
        }
    except ImportError:
        pass

    return {
        "cpu_percent": _cpu_percent_proc(),
        "memory_percent": _memory_percent_proc(),
        "disk_percent": _disk_percent(),
    }
