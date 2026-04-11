"""Multi-channel message delivery for BMT AI OS.

Architecture
------------
- ``Channel`` — abstract base class that all channels implement.
- ``WebhookChannel`` — delivers messages via HTTP POST to a URL.
- ``FileChannel`` — appends messages to a log file.
- ``ChannelRouter`` — dispatches messages to one or more channels based on a
  configuration list (e.g., loaded from ``controller.yml``).

Configuration example (controller.yml)::

    messaging:
      channels:
        - type: webhook
          name: alerts
          url: https://hooks.example.com/notify
          headers:
            Authorization: "Bearer secret"
          timeout: 10

        - type: file
          name: audit
          path: /var/log/bmt-messages.log

Usage::

    from bmt_ai_os.messaging.channels import ChannelRouter

    router = ChannelRouter.from_config(config["messaging"]["channels"])
    result = router.send_message(recipient="ops", content="Deployment complete.")
"""

from __future__ import annotations

import abc
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delivery result
# ---------------------------------------------------------------------------


@dataclass
class DeliveryResult:
    """Outcome of a single message delivery attempt."""

    channel_name: str
    success: bool
    error: str | None = None
    status_code: int | None = None  # HTTP status for webhook channels


@dataclass
class RoutingResult:
    """Aggregate result of routing a message to all configured channels."""

    recipient: str
    content: str
    results: list[DeliveryResult] = field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        return bool(self.results) and all(r.success for r in self.results)

    @property
    def any_successful(self) -> bool:
        return any(r.success for r in self.results)

    @property
    def failures(self) -> list[DeliveryResult]:
        return [r for r in self.results if not r.success]


# ---------------------------------------------------------------------------
# Abstract Channel
# ---------------------------------------------------------------------------


class Channel(abc.ABC):
    """Abstract interface for a message delivery channel.

    Subclasses must implement :meth:`send_message`.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abc.abstractmethod
    def send_message(self, recipient: str, content: str) -> DeliveryResult:
        """Send *content* to *recipient* and return a :class:`DeliveryResult`.

        Parameters
        ----------
        recipient:
            Identifier for the target (e.g. email address, Slack user, topic).
        content:
            The message payload as a plain string.

        Returns
        -------
        DeliveryResult
            Delivery outcome — never raises; errors are captured in the result.
        """


# ---------------------------------------------------------------------------
# WebhookChannel
# ---------------------------------------------------------------------------


class WebhookChannel(Channel):
    """Delivers messages by POSTing JSON to an HTTP endpoint.

    Parameters
    ----------
    name:
        Channel label used in routing results and logs.
    url:
        The webhook URL to POST to.
    headers:
        Optional additional HTTP headers (e.g. ``Authorization``).
    timeout:
        Request timeout in seconds (default: 10).
    """

    def __init__(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> None:
        super().__init__(name)
        if not url:
            raise ValueError(f"WebhookChannel '{name}': url must not be empty")
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout

    @property
    def url(self) -> str:
        return self._url

    def send_message(self, recipient: str, content: str) -> DeliveryResult:
        """POST a JSON payload to the configured webhook URL."""
        payload = {
            "recipient": recipient,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "bmt-ai-os",
        }
        body = json.dumps(payload).encode()

        req = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "bmt-ai-os/messaging")
        for header_name, header_value in self._headers.items():
            req.add_header(header_name, header_value)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
            logger.debug("WebhookChannel '%s': POST %s → %d", self.name, self._url, status)
            return DeliveryResult(
                channel_name=self.name,
                success=200 <= status < 300,
                status_code=status,
                error=None if 200 <= status < 300 else f"HTTP {status}",
            )
        except urllib.error.HTTPError as exc:
            logger.warning(
                "WebhookChannel '%s': HTTP error %d for %s", self.name, exc.code, self._url
            )
            return DeliveryResult(
                channel_name=self.name,
                success=False,
                status_code=exc.code,
                error=f"HTTP {exc.code}: {exc.reason}",
            )
        except Exception as exc:
            logger.warning("WebhookChannel '%s': %s", self.name, exc)
            return DeliveryResult(
                channel_name=self.name,
                success=False,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# FileChannel
# ---------------------------------------------------------------------------


class FileChannel(Channel):
    """Appends messages to a log file in JSON-lines format.

    Parameters
    ----------
    name:
        Channel label.
    path:
        Filesystem path to the log file.  Parent directories are created
        automatically on first write.
    """

    def __init__(self, name: str, path: str) -> None:
        super().__init__(name)
        if not path:
            raise ValueError(f"FileChannel '{name}': path must not be empty")
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def send_message(self, recipient: str, content: str) -> DeliveryResult:
        """Append a JSON-lines record to the configured file."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recipient": recipient,
            "content": content,
            "source": "bmt-ai-os",
        }
        line = json.dumps(record, ensure_ascii=False)

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            logger.debug("FileChannel '%s': wrote to %s", self.name, self._path)
            return DeliveryResult(channel_name=self.name, success=True)
        except OSError as exc:
            logger.warning("FileChannel '%s': %s", self.name, exc)
            return DeliveryResult(channel_name=self.name, success=False, error=str(exc))


# ---------------------------------------------------------------------------
# ChannelRouter
# ---------------------------------------------------------------------------


class ChannelRouter:
    """Routes messages to one or more :class:`Channel` instances.

    The router dispatches every ``send_message`` call to **all** registered
    channels, collecting individual :class:`DeliveryResult` objects into a
    :class:`RoutingResult`.

    Parameters
    ----------
    channels:
        An ordered list of channel instances to route through.
    """

    def __init__(self, channels: list[Channel] | None = None) -> None:
        self._channels: list[Channel] = list(channels or [])

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, channel_configs: list[dict[str, Any]]) -> "ChannelRouter":
        """Build a :class:`ChannelRouter` from a list of configuration dicts.

        Each dict must contain at minimum a ``type`` key (``"webhook"`` or
        ``"file"``) and a ``name`` key.

        Webhook config keys:
          - ``url`` (required)
          - ``headers`` (optional, dict)
          - ``timeout`` (optional, int, default 10)

        File config keys:
          - ``path`` (required)

        Unknown ``type`` values are logged and skipped.
        """
        channels: list[Channel] = []
        for cfg in channel_configs:
            channel_type = cfg.get("type", "").lower()
            name = cfg.get("name", channel_type)
            try:
                if channel_type == "webhook":
                    channels.append(
                        WebhookChannel(
                            name=name,
                            url=cfg["url"],
                            headers=cfg.get("headers"),
                            timeout=int(cfg.get("timeout", 10)),
                        )
                    )
                elif channel_type == "file":
                    channels.append(
                        FileChannel(
                            name=name,
                            path=cfg["path"],
                        )
                    )
                else:
                    logger.warning(
                        "ChannelRouter: unknown channel type '%s' — skipping", channel_type
                    )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("ChannelRouter: failed to build channel '%s': %s", name, exc)

        return cls(channels)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_channel(self, channel: Channel) -> None:
        """Register an additional channel at runtime."""
        self._channels.append(channel)

    def remove_channel(self, name: str) -> bool:
        """Remove the first channel with the given *name*.

        Returns True if a channel was removed, False if not found.
        """
        for i, ch in enumerate(self._channels):
            if ch.name == name:
                del self._channels[i]
                return True
        return False

    @property
    def channel_names(self) -> list[str]:
        """Names of all registered channels."""
        return [ch.name for ch in self._channels]

    def send_message(self, recipient: str, content: str) -> RoutingResult:
        """Deliver *content* to *recipient* via all registered channels.

        Parameters
        ----------
        recipient:
            Target identifier passed to each channel's ``send_message``.
        content:
            Message payload.

        Returns
        -------
        RoutingResult
            Aggregated delivery results from all channels.
        """
        result = RoutingResult(recipient=recipient, content=content)

        if not self._channels:
            logger.warning("ChannelRouter.send_message: no channels configured — message dropped")
            return result

        for channel in self._channels:
            delivery = channel.send_message(recipient=recipient, content=content)
            result.results.append(delivery)
            if delivery.success:
                logger.debug("Delivered to channel '%s' (recipient=%r)", channel.name, recipient)
            else:
                logger.warning(
                    "Delivery failed on channel '%s' (recipient=%r): %s",
                    channel.name,
                    recipient,
                    delivery.error,
                )

        return result
