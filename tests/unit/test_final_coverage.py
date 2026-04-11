"""Final coverage tests to reach >= 1100 total unit tests.

Covers remaining edge cases across multiple modules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# providers/config: CircuitBreakerSettings
# ---------------------------------------------------------------------------


class TestCircuitBreakerSettings:
    def test_defaults(self):
        from bmt_ai_os.providers.config import CircuitBreakerSettings

        s = CircuitBreakerSettings()
        assert s.failure_threshold == 3
        assert s.cooldown_seconds == 60.0
        assert s.half_open_max_requests == 1

    def test_custom(self):
        from bmt_ai_os.providers.config import CircuitBreakerSettings

        s = CircuitBreakerSettings(
            failure_threshold=5, cooldown_seconds=30.0, half_open_max_requests=2
        )
        assert s.failure_threshold == 5
        assert s.cooldown_seconds == 30.0
        assert s.half_open_max_requests == 2


# ---------------------------------------------------------------------------
# rag/query: SourceAttribution edge cases
# ---------------------------------------------------------------------------


class TestSourceAttributionExtra:
    def test_position_zero(self):
        from bmt_ai_os.rag.query import SourceAttribution

        sa = SourceAttribution(filename="f.md", chunk_text="text", relevance_score=0.9, position=0)
        assert sa.to_dict()["position"] == 0

    def test_negative_relevance_score(self):
        from bmt_ai_os.rag.query import SourceAttribution

        sa = SourceAttribution(filename="f.md", chunk_text="t", relevance_score=-0.1, position=0)
        d = sa.to_dict()
        assert d["score"] == round(-0.1, 4)

    def test_chunk_text_preserved(self):
        from bmt_ai_os.rag.query import SourceAttribution

        sa = SourceAttribution(
            filename="f.md", chunk_text="important context", relevance_score=0.5, position=1
        )
        assert sa.to_dict()["chunk"] == "important context"


# ---------------------------------------------------------------------------
# fleet/models: FleetCommand edge cases
# ---------------------------------------------------------------------------


class TestFleetCommandExtra:
    def test_from_dict_with_extra_keys(self):
        from bmt_ai_os.fleet.models import FleetCommand

        # Extra keys in the dict should be ignored
        cmd = FleetCommand.from_dict({"action": "update", "unknown_key": "value", "params": {}})
        assert cmd.action == "update"

    def test_command_id_defaults_empty(self):
        from bmt_ai_os.fleet.models import FleetCommand

        cmd = FleetCommand.from_dict({"action": "update"})
        assert cmd.command_id == ""

    def test_is_noop_for_none(self):
        from bmt_ai_os.fleet.models import FleetCommand

        cmd = FleetCommand(action=None)
        assert cmd.is_noop() is True

    def test_is_noop_false_for_update(self):
        from bmt_ai_os.fleet.models import FleetCommand

        cmd = FleetCommand(action="update")
        assert cmd.is_noop() is False


# ---------------------------------------------------------------------------
# controller/health: HealthStatus enum
# ---------------------------------------------------------------------------


class TestHealthStatusEnum:
    def test_healthy_value(self):
        from bmt_ai_os.controller.health import HealthStatus

        assert HealthStatus.HEALTHY == "healthy"

    def test_unhealthy_value(self):
        from bmt_ai_os.controller.health import HealthStatus

        assert HealthStatus.UNHEALTHY == "unhealthy"

    def test_unknown_value(self):
        from bmt_ai_os.controller.health import HealthStatus

        assert HealthStatus.UNKNOWN == "unknown"

    def test_is_str_enum(self):
        from bmt_ai_os.controller.health import HealthStatus

        assert isinstance(HealthStatus.HEALTHY, str)


# ---------------------------------------------------------------------------
# controller/health: CircuitState enum
# ---------------------------------------------------------------------------


class TestCircuitStateEnum:
    def test_closed_value(self):
        from bmt_ai_os.controller.health import CircuitState

        assert CircuitState.CLOSED == "closed"

    def test_open_value(self):
        from bmt_ai_os.controller.health import CircuitState

        assert CircuitState.OPEN == "open"

    def test_half_open_value(self):
        from bmt_ai_os.controller.health import CircuitState

        assert CircuitState.HALF_OPEN == "half_open"
