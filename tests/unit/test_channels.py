"""Unit tests for bmt_ai_os.messaging.channels."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from bmt_ai_os.messaging.channels import (
    Channel,
    ChannelRouter,
    DeliveryResult,
    FileChannel,
    RoutingResult,
    WebhookChannel,
)

# ---------------------------------------------------------------------------
# DeliveryResult / RoutingResult
# ---------------------------------------------------------------------------


class TestDeliveryResult:
    def test_success_result(self):
        r = DeliveryResult(channel_name="test", success=True)
        assert r.success
        assert r.error is None

    def test_failure_result(self):
        r = DeliveryResult(channel_name="test", success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"


class TestRoutingResult:
    def test_empty_results(self):
        rr = RoutingResult(recipient="user", content="hello")
        assert not rr.all_successful
        assert not rr.any_successful
        assert rr.failures == []

    def test_all_successful(self):
        rr = RoutingResult(
            recipient="u",
            content="c",
            results=[
                DeliveryResult("ch1", True),
                DeliveryResult("ch2", True),
            ],
        )
        assert rr.all_successful
        assert rr.any_successful

    def test_partial_failure(self):
        rr = RoutingResult(
            recipient="u",
            content="c",
            results=[
                DeliveryResult("ch1", True),
                DeliveryResult("ch2", False, error="network"),
            ],
        )
        assert not rr.all_successful
        assert rr.any_successful
        assert len(rr.failures) == 1

    def test_all_failed(self):
        rr = RoutingResult(
            recipient="u",
            content="c",
            results=[DeliveryResult("ch1", False, error="err")],
        )
        assert not rr.all_successful
        assert not rr.any_successful


# ---------------------------------------------------------------------------
# Channel (abstract)
# ---------------------------------------------------------------------------


class TestChannelAbstract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Channel("test")  # type: ignore[abstract]

    def test_subclass_must_implement_send_message(self):
        class BadChannel(Channel):
            pass

        with pytest.raises(TypeError):
            BadChannel("bad")  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# FileChannel
# ---------------------------------------------------------------------------


class TestFileChannel:
    def test_creates_parent_dirs(self, tmp_path):
        log_path = tmp_path / "deep" / "dir" / "messages.log"
        ch = FileChannel(name="audit", path=str(log_path))
        result = ch.send_message(recipient="ops", content="hello")
        assert result.success
        assert log_path.exists()

    def test_appends_json_lines(self, tmp_path):
        log_path = tmp_path / "msg.log"
        ch = FileChannel(name="log", path=str(log_path))

        ch.send_message("alice", "first message")
        ch.send_message("bob", "second message")

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["recipient"] == "alice"
        assert first["content"] == "first message"
        assert "timestamp" in first

    def test_channel_name_in_result(self, tmp_path):
        ch = FileChannel(name="my-log", path=str(tmp_path / "out.log"))
        result = ch.send_message("r", "c")
        assert result.channel_name == "my-log"

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="path"):
            FileChannel(name="bad", path="")

    def test_unwritable_path_returns_failure(self):
        ch = FileChannel(name="fail", path="/proc/sys/kernel/restricted/no_write.log")
        result = ch.send_message("r", "c")
        # Should not raise — error captured in result
        assert not result.success
        assert result.error is not None

    def test_path_property(self, tmp_path):
        ch = FileChannel(name="log", path=str(tmp_path / "x.log"))
        assert str(ch.path) == str(tmp_path / "x.log")


# ---------------------------------------------------------------------------
# WebhookChannel
# ---------------------------------------------------------------------------


class TestWebhookChannel:
    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="url"):
            WebhookChannel(name="wh", url="")

    def test_url_property(self):
        ch = WebhookChannel(name="wh", url="http://example.com/hook")
        assert ch.url == "http://example.com/hook"

    def test_network_error_captured(self):
        ch = WebhookChannel(name="wh", url="http://127.0.0.1:19999/nonexistent")
        result = ch.send_message("r", "content")
        assert not result.success
        assert result.error is not None

    def test_successful_post(self):
        """Start a minimal HTTP server and verify a 200 response is treated as success."""
        received: list[bytes] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                received.append(self.rfile.read(length))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass  # silence server logs in tests

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request, daemon=True)
        t.start()

        ch = WebhookChannel(name="test-wh", url=f"http://127.0.0.1:{port}/hook")
        result = ch.send_message("ops", "deployment done")

        t.join(timeout=2)
        server.server_close()

        assert result.success
        assert result.status_code == 200
        assert len(received) == 1
        payload = json.loads(received[0])
        assert payload["recipient"] == "ops"
        assert payload["content"] == "deployment done"

    def test_http_error_captured(self):
        """A 4xx/5xx response should produce a failed DeliveryResult."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request, daemon=True)
        t.start()

        ch = WebhookChannel(name="failing-wh", url=f"http://127.0.0.1:{port}/hook")
        result = ch.send_message("r", "c")

        t.join(timeout=2)
        server.server_close()

        assert not result.success
        assert result.status_code == 500

    def test_custom_headers_sent(self):
        """Verify that custom headers are forwarded in the request."""
        headers_received: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                headers_received.append(self.headers.get("X-Custom-Header", ""))
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request, daemon=True)
        t.start()

        ch = WebhookChannel(
            name="hdr-wh",
            url=f"http://127.0.0.1:{port}/hook",
            headers={"X-Custom-Header": "bmt-value"},
        )
        ch.send_message("r", "c")

        t.join(timeout=2)
        server.server_close()

        assert "bmt-value" in headers_received


# ---------------------------------------------------------------------------
# ChannelRouter
# ---------------------------------------------------------------------------


class TestChannelRouter:
    def test_empty_router_returns_empty_results(self):
        router = ChannelRouter()
        result = router.send_message("r", "hello")
        assert result.results == []
        assert not result.all_successful

    def test_routes_to_all_channels(self, tmp_path):
        log1 = tmp_path / "ch1.log"
        log2 = tmp_path / "ch2.log"
        router = ChannelRouter(
            [
                FileChannel("ch1", str(log1)),
                FileChannel("ch2", str(log2)),
            ]
        )
        result = router.send_message("ops", "broadcast")
        assert result.all_successful
        assert len(result.results) == 2
        assert log1.exists()
        assert log2.exists()

    def test_add_channel(self, tmp_path):
        router = ChannelRouter()
        router.add_channel(FileChannel("new", str(tmp_path / "new.log")))
        assert "new" in router.channel_names

    def test_remove_channel(self, tmp_path):
        ch = FileChannel("removable", str(tmp_path / "r.log"))
        router = ChannelRouter([ch])
        assert router.remove_channel("removable") is True
        assert "removable" not in router.channel_names

    def test_remove_nonexistent_channel(self):
        router = ChannelRouter()
        assert router.remove_channel("ghost") is False

    def test_channel_names(self, tmp_path):
        router = ChannelRouter(
            [
                FileChannel("a", str(tmp_path / "a.log")),
                FileChannel("b", str(tmp_path / "b.log")),
            ]
        )
        assert router.channel_names == ["a", "b"]

    def test_partial_failure_captured(self, tmp_path):
        """If one channel fails, the others still deliver."""
        good_log = tmp_path / "good.log"
        router = ChannelRouter(
            [
                FileChannel("good", str(good_log)),
                # Bad channel points to an unwritable path
                FileChannel("bad", "/proc/sys/no_write.log"),
            ]
        )
        result = router.send_message("r", "test")
        assert result.any_successful
        assert not result.all_successful
        assert good_log.exists()


# ---------------------------------------------------------------------------
# ChannelRouter.from_config
# ---------------------------------------------------------------------------


class TestChannelRouterFromConfig:
    def test_file_channel_from_config(self, tmp_path):
        configs = [{"type": "file", "name": "audit", "path": str(tmp_path / "audit.log")}]
        router = ChannelRouter.from_config(configs)
        assert "audit" in router.channel_names
        assert isinstance(router._channels[0], FileChannel)

    def test_webhook_channel_from_config(self):
        configs = [
            {
                "type": "webhook",
                "name": "hook",
                "url": "http://example.com/hook",
                "timeout": 5,
            }
        ]
        router = ChannelRouter.from_config(configs)
        assert "hook" in router.channel_names
        ch = router._channels[0]
        assert isinstance(ch, WebhookChannel)
        assert ch.url == "http://example.com/hook"

    def test_unknown_type_skipped(self):
        configs = [{"type": "slack", "name": "slack-ch"}]
        router = ChannelRouter.from_config(configs)
        assert len(router._channels) == 0

    def test_missing_required_key_skipped(self):
        # webhook without url
        configs = [{"type": "webhook", "name": "broken"}]
        router = ChannelRouter.from_config(configs)
        assert len(router._channels) == 0

    def test_empty_config_list(self):
        router = ChannelRouter.from_config([])
        assert len(router._channels) == 0

    def test_mixed_channels_from_config(self, tmp_path):
        configs = [
            {"type": "file", "name": "f1", "path": str(tmp_path / "f1.log")},
            {"type": "webhook", "name": "wh", "url": "http://example.com"},
        ]
        router = ChannelRouter.from_config(configs)
        assert len(router._channels) == 2
        assert router.channel_names == ["f1", "wh"]
