"""Unit tests for bmt_ai_os.controller.discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmt_ai_os.controller.discovery import (
    DiscoveredProvider,
    _probe_port,
    auto_register_discovered,
    run_discovery,
    scan_local_providers,
)
from bmt_ai_os.providers.registry import reset_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discovered(
    name: str = "ollama",
    port: int = 11434,
    provider_type: str = "ollama",
    latency_ms: float = 10.0,
    already_registered: bool = False,
) -> DiscoveredProvider:
    return DiscoveredProvider(
        name=name,
        port=port,
        base_url=f"http://localhost:{port}",
        provider_type=provider_type,
        latency_ms=latency_ms,
        already_registered=already_registered,
    )


# ---------------------------------------------------------------------------
# DiscoveredProvider.to_dict
# ---------------------------------------------------------------------------


class TestDiscoveredProviderToDict:
    def test_to_dict_includes_required_keys(self):
        d = _make_discovered()
        result = d.to_dict()
        assert result["name"] == "ollama"
        assert result["port"] == 11434
        assert result["provider_type"] == "ollama"
        assert result["discovered"] is True
        assert "latency_ms" in result
        assert "already_registered" in result
        assert "registered_now" in result

    def test_latency_rounded(self):
        d = _make_discovered(latency_ms=12.3456)
        assert d.to_dict()["latency_ms"] == 12.35

    def test_error_none_by_default(self):
        d = _make_discovered()
        assert d.to_dict()["error"] is None

    def test_registered_now_false_by_default(self):
        d = _make_discovered()
        assert d.to_dict()["registered_now"] is False


# ---------------------------------------------------------------------------
# _probe_port
# ---------------------------------------------------------------------------


class TestProbePort:
    @pytest.mark.asyncio
    async def test_reachable_returns_true(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            ok, latency, err = await _probe_port(11434, "/api/tags")

        assert ok is True
        assert err is None
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_connection_refused_returns_false(self):
        import aiohttp

        with patch(
            "aiohttp.ClientSession",
            side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("refused")
            ),
        ):
            ok, latency, err = await _probe_port(9999, "/health")

        assert ok is False
        assert err is not None

    @pytest.mark.asyncio
    async def test_server_error_returns_false(self):
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            ok, latency, err = await _probe_port(8001, "/health")

        assert ok is False
        assert "500" in (err or "")

    @pytest.mark.asyncio
    async def test_non_500_status_returns_true(self):
        """Status codes < 500 (e.g. 404) are treated as reachable."""
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            ok, _, err = await _probe_port(11434, "/api/tags")

        assert ok is True
        assert err is None


# ---------------------------------------------------------------------------
# scan_local_providers
# ---------------------------------------------------------------------------


class TestScanLocalProviders:
    @pytest.mark.asyncio
    async def test_returns_discovered_for_reachable_port(self):
        async def fake_probe(port, path):
            if port == 11434:
                return True, 5.0, None
            return False, 2.0, "refused"

        with patch("bmt_ai_os.controller.discovery._probe_port", side_effect=fake_probe):
            results = await scan_local_providers()

        assert len(results) == 1
        assert results[0].port == 11434
        assert results[0].provider_type == "ollama"
        assert results[0].latency_ms == 5.0

    @pytest.mark.asyncio
    async def test_returns_empty_when_nothing_reachable(self):
        async def fake_probe(port, path):
            return False, 1.0, "refused"

        with patch("bmt_ai_os.controller.discovery._probe_port", side_effect=fake_probe):
            results = await scan_local_providers()

        assert results == []

    @pytest.mark.asyncio
    async def test_multiple_ports_discovered(self):
        async def fake_probe(port, path):
            return True, 8.0, None  # all ports respond

        with patch("bmt_ai_os.controller.discovery._probe_port", side_effect=fake_probe):
            results = await scan_local_providers()

        assert len(results) == 3
        ports = {r.port for r in results}
        assert 11434 in ports
        assert 8001 in ports
        assert 8002 in ports


# ---------------------------------------------------------------------------
# auto_register_discovered
# ---------------------------------------------------------------------------


class TestAutoRegisterDiscovered:
    @pytest.fixture(autouse=True)
    def reset(self):
        reset_registry()
        yield
        reset_registry()

    @pytest.mark.asyncio
    async def test_registers_new_provider(self):
        mock_provider = MagicMock()
        mock_cls = MagicMock(return_value=mock_provider)
        mock_module = MagicMock()
        mock_module.OllamaProvider = mock_cls

        with patch("importlib.import_module", return_value=mock_module):
            discovered = [_make_discovered()]
            await auto_register_discovered(discovered)

        from bmt_ai_os.providers.registry import get_registry

        assert "ollama" in get_registry().list()
        assert discovered[0].registered_now is True
        assert discovered[0].already_registered is False

    @pytest.mark.asyncio
    async def test_skips_already_registered(self):
        from bmt_ai_os.providers.registry import get_registry

        mock_prov = MagicMock()
        get_registry().register("ollama", mock_prov)

        discovered = [_make_discovered()]
        await auto_register_discovered(discovered)

        assert discovered[0].already_registered is True
        assert discovered[0].registered_now is False

    @pytest.mark.asyncio
    async def test_handles_import_error_gracefully(self):
        with patch("importlib.import_module", side_effect=ImportError("no module")):
            discovered = [_make_discovered()]
            # Should not raise
            await auto_register_discovered(discovered)

        assert discovered[0].error is not None
        assert discovered[0].registered_now is False


# ---------------------------------------------------------------------------
# run_discovery (integration of scan + register)
# ---------------------------------------------------------------------------


class TestRunDiscovery:
    @pytest.fixture(autouse=True)
    def reset(self):
        reset_registry()
        yield
        reset_registry()

    @pytest.mark.asyncio
    async def test_run_discovery_returns_list(self):
        async def fake_probe(port, path):
            return False, 1.0, "refused"

        with patch("bmt_ai_os.controller.discovery._probe_port", side_effect=fake_probe):
            results = await run_discovery()

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_run_discovery_registers_found_providers(self):
        async def fake_probe(port, path):
            if port == 11434:
                return True, 5.0, None
            return False, 1.0, "refused"

        mock_provider = MagicMock()
        mock_cls = MagicMock(return_value=mock_provider)
        mock_module = MagicMock()
        mock_module.OllamaProvider = mock_cls

        with (
            patch("bmt_ai_os.controller.discovery._probe_port", side_effect=fake_probe),
            patch("importlib.import_module", return_value=mock_module),
        ):
            results = await run_discovery()

        assert len(results) == 1
        assert results[0].registered_now is True
