"""System benchmark — CPU, memory, and disk I/O baseline measurements.

Measures key system-level metrics without requiring live AI services.
All measurements use only Python standard library modules (``os``,
``time``, ``platform``, ``resource``) so that they work in any environment,
including CI runners that have no GPU or NPU.

Metric definitions
------------------
cpu_score:
    A synthetic score derived from the time taken to perform a fixed
    number of floating-point operations. Higher is better.
memory_read_mb_s:
    Sequential read throughput from a large in-memory buffer (mmap-style
    byte-array copy). Higher is better.
disk_write_mb_s:
    Sequential write throughput to a temporary file. Higher is better.
disk_read_mb_s:
    Sequential read throughput from the same temporary file. Higher is better.
memory_total_mb:
    Total physical RAM reported by the OS.
memory_available_mb:
    Available (free + reclaimable) RAM at time of measurement.
"""

from __future__ import annotations

import array
import logging
import math
import os
import platform
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Size of the I/O test file: 64 MiB — large enough to be meaningful on ARM64
# embedded targets, small enough to complete quickly in CI (< 2 s on modern SSD).
_IO_BLOCK_SIZE = 64 * 1024 * 1024  # 64 MiB

# Number of floating-point iterations for the CPU micro-benchmark.
_CPU_FLOP_ITERS = 2_000_000


@dataclass
class SystemResult:
    """Results from a single system benchmark run."""

    cpu_score: float
    memory_read_mb_s: float
    disk_write_mb_s: float
    disk_read_mb_s: float
    memory_total_mb: float
    memory_available_mb: float
    platform_info: str

    def to_dict(self) -> dict:
        return {
            "cpu_score": round(self.cpu_score, 2),
            "memory_read_mb_s": round(self.memory_read_mb_s, 1),
            "disk_write_mb_s": round(self.disk_write_mb_s, 1),
            "disk_read_mb_s": round(self.disk_read_mb_s, 1),
            "memory_total_mb": round(self.memory_total_mb, 1),
            "memory_available_mb": round(self.memory_available_mb, 1),
            "platform_info": self.platform_info,
        }


def run(io_block_size: int = _IO_BLOCK_SIZE) -> SystemResult:
    """Run the system benchmark and return a :class:`SystemResult`.

    Parameters
    ----------
    io_block_size:
        Number of bytes to use for disk I/O tests. Defaults to 64 MiB.
    """
    logger.debug("Running CPU micro-benchmark (%d FP iterations)", _CPU_FLOP_ITERS)
    cpu_score = _cpu_benchmark()

    logger.debug("Running in-memory read benchmark (%d bytes)", io_block_size)
    memory_read_mb_s = _memory_read_benchmark(io_block_size)

    logger.debug("Running disk I/O benchmark (%d bytes)", io_block_size)
    disk_write_mb_s, disk_read_mb_s = _disk_io_benchmark(io_block_size)

    total_mb, available_mb = _memory_info()

    return SystemResult(
        cpu_score=cpu_score,
        memory_read_mb_s=memory_read_mb_s,
        disk_write_mb_s=disk_write_mb_s,
        disk_read_mb_s=disk_read_mb_s,
        memory_total_mb=total_mb,
        memory_available_mb=available_mb,
        platform_info=_platform_info(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cpu_benchmark() -> float:
    """Run a synthetic FP workload and return a normalised score.

    The score is the number of iterations completed per millisecond, scaled
    to a convenient range.  The workload is a tight loop of ``math.sqrt`` and
    ``math.sin`` calls, which exercises the FPU pipeline without involving the
    memory subsystem.
    """
    x = 1.0
    t_start = time.perf_counter()
    for i in range(_CPU_FLOP_ITERS):
        x = math.sqrt(abs(math.sin(x + i * 0.0001)))
    elapsed_s = time.perf_counter() - t_start
    # Score = iterations per ms; guard against zero division.
    return _CPU_FLOP_ITERS / (elapsed_s * 1000) if elapsed_s > 0 else 0.0


def _memory_read_benchmark(size: int) -> float:
    """Measure in-memory sequential read throughput in MB/s.

    Allocates a ``bytearray`` of *size* bytes and copies it into a second
    buffer in one call, measuring the time to do so.
    """
    data = bytearray(size)
    # Initialise to avoid lazy allocation on some kernels.
    for i in range(0, size, 4096):
        data[i] = i & 0xFF

    t_start = time.perf_counter()
    _ = bytearray(data)  # single-copy read
    elapsed_s = time.perf_counter() - t_start

    mb = size / (1024 * 1024)
    return mb / elapsed_s if elapsed_s > 0 else 0.0


def _disk_io_benchmark(size: int) -> tuple[float, float]:
    """Write then read a temporary file and return (write_mb_s, read_mb_s).

    Uses ``os.fsync`` after writing to ensure data hits the storage device
    rather than staying in the OS page cache.
    """
    # Build a buffer using a typed array for speed (avoids Python object
    # overhead compared to a list comprehension).
    block = array.array("B", bytes(size))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bmt_bench") as f:
        tmp_path = Path(f.name)

    try:
        # --- Write ---
        t_start = time.perf_counter()
        with open(tmp_path, "wb") as fh:
            fh.write(block)
            fh.flush()
            os.fsync(fh.fileno())
        write_elapsed = time.perf_counter() - t_start

        # --- Read ---
        t_start = time.perf_counter()
        _ = tmp_path.read_bytes()
        read_elapsed = time.perf_counter() - t_start

    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    mb = size / (1024 * 1024)
    write_mb_s = mb / write_elapsed if write_elapsed > 0 else 0.0
    read_mb_s = mb / read_elapsed if read_elapsed > 0 else 0.0
    return write_mb_s, read_mb_s


def _memory_info() -> tuple[float, float]:
    """Return (total_mb, available_mb) from /proc/meminfo on Linux.

    Falls back to ``os.sysconf`` (POSIX) for the total, and 0.0 for
    available on platforms without ``/proc/meminfo`` (macOS, Windows).
    """
    proc_meminfo = Path("/proc/meminfo")
    if proc_meminfo.exists():
        try:
            text = proc_meminfo.read_text(encoding="utf-8")
            values: dict[str, float] = {}
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    try:
                        values[key] = float(parts[1])  # kB
                    except ValueError:
                        pass
            total_kb = values.get("MemTotal", 0.0)
            avail_kb = values.get("MemAvailable", values.get("MemFree", 0.0))
            return total_kb / 1024, avail_kb / 1024
        except OSError:
            pass

    # macOS / non-Linux fallback
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        total_mb = page_size * phys_pages / (1024 * 1024)
        return total_mb, 0.0
    except (AttributeError, ValueError, OSError):
        pass

    return 0.0, 0.0


def _platform_info() -> str:
    """Return a compact platform descriptor string."""
    machine = platform.machine()
    system = platform.system()
    release = platform.release()
    processor = platform.processor() or machine
    return f"{system} {release} {machine} ({processor})"
