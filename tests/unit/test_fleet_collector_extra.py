"""Additional unit tests for bmt_ai_os.fleet.collector.

Focuses on edge cases and paths not covered in test_fleet_collector.py.
"""

from __future__ import annotations

from unittest.mock import patch

from bmt_ai_os.fleet.collector import (
    _cpu_percent_proc,
    _detect_board,
    _get_cpu_model,
    _get_memory_total_mb,
    get_hardware_info,
    get_service_health,
)

# ---------------------------------------------------------------------------
# _get_cpu_model
# ---------------------------------------------------------------------------


class TestGetCpuModel:
    def test_parses_model_name_from_cpuinfo(self):
        # "model name" must appear before "processor" so it matches first
        cpuinfo = "model name\t: ARM Cortex-A76\nprocessor\t: 0\n"
        with patch("pathlib.Path.read_text", return_value=cpuinfo):
            result = _get_cpu_model()
        assert "ARM Cortex-A76" in result

    def test_parses_hardware_field(self):
        cpuinfo = "Hardware\t: BCM2712\n"
        with patch("pathlib.Path.read_text", return_value=cpuinfo):
            result = _get_cpu_model()
        assert "BCM2712" in result

    def test_falls_back_to_platform_on_error(self):
        with patch("pathlib.Path.read_text", side_effect=OSError):
            result = _get_cpu_model()
        assert isinstance(result, str)

    def test_returns_nonempty_string(self):
        result = _get_cpu_model()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _detect_board
# ---------------------------------------------------------------------------


class TestDetectBoardExtra:
    def test_empty_device_tree_falls_back(self):
        with patch("bmt_ai_os.fleet.collector._read_file_stripped", return_value=""):
            result = _detect_board()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_arm64_without_device_tree(self):
        with (
            patch("bmt_ai_os.fleet.collector._read_file_stripped", return_value=""),
            patch("platform.machine", return_value="aarch64"),
            patch("platform.processor", return_value=""),
        ):
            result = _detect_board()
        assert result == "arm64-generic"

    def test_apple_silicon_detected(self):
        with (
            patch("bmt_ai_os.fleet.collector._read_file_stripped", return_value=""),
            patch("platform.machine", return_value="aarch64"),
            patch("platform.processor", return_value="apple m2"),
        ):
            result = _detect_board()
        assert result == "apple-silicon"


# ---------------------------------------------------------------------------
# _get_memory_total_mb
# ---------------------------------------------------------------------------


class TestGetMemoryTotalMbExtra:
    def test_parses_meminfo_correctly(self):
        meminfo = "MemTotal:       8192000 kB\nMemFree:        4000000 kB\n"
        with patch("pathlib.Path.read_text", return_value=meminfo):
            result = _get_memory_total_mb()
        assert result == 8000  # 8192000 / 1024

    def test_returns_zero_on_value_error(self):
        meminfo = "MemTotal: INVALID kB\n"
        with patch("pathlib.Path.read_text", return_value=meminfo):
            result = _get_memory_total_mb()
        assert result == 0

    def test_returns_zero_if_memtotal_missing(self):
        meminfo = "MemFree: 1000000 kB\n"
        with patch("pathlib.Path.read_text", return_value=meminfo):
            result = _get_memory_total_mb()
        assert result == 0


# ---------------------------------------------------------------------------
# _cpu_percent_proc
# ---------------------------------------------------------------------------


class TestCpuPercentProc:
    def test_returns_float(self):
        result = _cpu_percent_proc()
        assert isinstance(result, float)

    def test_returns_0_to_100_range(self):
        result = _cpu_percent_proc()
        assert 0.0 <= result <= 100.0

    def test_zero_delta_returns_zero(self):
        # Simulate both reads returning the same values (delta = 0)
        stat_content = "cpu  100 0 50 850 0 0 0 0 0 0\n"
        with patch("pathlib.Path.read_text", return_value=stat_content):
            result = _cpu_percent_proc()
        assert result == 0.0


# ---------------------------------------------------------------------------
# get_hardware_info
# ---------------------------------------------------------------------------


class TestGetHardwareInfoExtra:
    def test_arch_from_platform(self):
        with patch("platform.machine", return_value="aarch64"):
            info = get_hardware_info()
        assert info["arch"] == "aarch64"

    def test_cpu_cores_positive(self):
        info = get_hardware_info()
        assert info["cpu_cores"] >= 1

    def test_hostname_nonempty(self):
        info = get_hardware_info()
        assert len(info["hostname"]) > 0

    def test_disk_total_gb_non_negative(self):
        info = get_hardware_info()
        assert info["disk_total_gb"] >= 0.0


# ---------------------------------------------------------------------------
# get_service_health extra
# ---------------------------------------------------------------------------


class TestGetServiceHealthExtra:
    def test_probes_both_services(self):
        probed_urls = []

        def capture_probe(url):
            probed_urls.append(url)
            return True

        with patch("bmt_ai_os.fleet.collector._probe", side_effect=capture_probe):
            get_service_health()

        assert any("11434" in url for url in probed_urls)
        assert any("8000" in url for url in probed_urls)

    def test_result_has_exactly_two_services(self):
        with patch("bmt_ai_os.fleet.collector._probe", return_value=True):
            result = get_service_health()
        assert len(result) == 2

    def test_result_keys_are_service_names(self):
        with patch("bmt_ai_os.fleet.collector._probe", return_value=False):
            result = get_service_health()
        assert "ollama" in result
        assert "chromadb" in result
