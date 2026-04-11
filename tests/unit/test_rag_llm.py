"""Unit tests for bmt_ai_os.rag.llm.OllamaLLM.

All HTTP calls are mocked — no live Ollama required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.llm import OllamaLLM

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> RAGConfig:
    return RAGConfig(
        ollama_url="http://localhost:11434",
        llm_model="qwen2.5-coder:7b",
        temperature=0.7,
        top_p=0.9,
        max_tokens=512,
    )


@pytest.fixture()
def llm(config: RAGConfig) -> OllamaLLM:
    return OllamaLLM(config)


def _mock_complete_response(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"message": {"role": "assistant", "content": content}}
    return mock_resp


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestOllamaLLMConstruction:
    def test_base_url_trailing_slash_stripped(self):
        cfg = RAGConfig(ollama_url="http://localhost:11434/")
        llm = OllamaLLM(cfg)
        assert llm.base_url == "http://localhost:11434"

    def test_base_url_no_trailing_slash(self):
        cfg = RAGConfig(ollama_url="http://localhost:11434")
        llm = OllamaLLM(cfg)
        assert llm.base_url == "http://localhost:11434"


# ---------------------------------------------------------------------------
# generate — non-streaming
# ---------------------------------------------------------------------------


class TestGenerateNonStreaming:
    def test_returns_content_string(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("Hello, world!")):
            result = llm.generate("What is Python?")
        assert result == "Hello, world!"

    def test_uses_default_model(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("prompt")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "qwen2.5-coder:7b"

    def test_uses_override_model(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("prompt", model="llama3:8b")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "llama3:8b"

    def test_passes_temperature(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("prompt", temperature=0.1)
        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["temperature"] == 0.1

    def test_passes_top_p(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("prompt", top_p=0.5)
        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["top_p"] == 0.5

    def test_passes_max_tokens(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("prompt", max_tokens=256)
        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["num_predict"] == 256

    def test_uses_config_defaults_when_not_overridden(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("prompt")
        payload = mock_post.call_args[1]["json"]
        assert payload["options"]["temperature"] == 0.7
        assert payload["options"]["top_p"] == 0.9
        assert payload["options"]["num_predict"] == 512

    def test_prompt_in_messages(self, llm: OllamaLLM) -> None:
        with patch("requests.post", return_value=_mock_complete_response("ok")) as mock_post:
            llm.generate("Tell me about ARM64")
        payload = mock_post.call_args[1]["json"]
        assert payload["messages"][0]["content"] == "Tell me about ARM64"
        assert payload["messages"][0]["role"] == "user"

    def test_raises_on_http_error(self, llm: OllamaLLM) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                llm.generate("prompt")

    def test_empty_content_returned(self, llm: OllamaLLM) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"message": {}}
        with patch("requests.post", return_value=mock_resp):
            result = llm.generate("prompt")
        assert result == ""


# ---------------------------------------------------------------------------
# generate — streaming
# ---------------------------------------------------------------------------


class TestGenerateStreaming:
    def test_returns_generator(self, llm: OllamaLLM) -> None:
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}).encode(),
            json.dumps({"message": {"content": " world"}, "done": True}).encode(),
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = [ln.decode() for ln in lines]
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.post", return_value=mock_resp):
            gen = llm.generate("prompt", stream=True)

        assert hasattr(gen, "__iter__")

    def test_yields_tokens(self, llm: OllamaLLM) -> None:
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = lines
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.post", return_value=mock_resp):
            tokens = list(llm.generate("prompt", stream=True))
        assert "Hello" in tokens
        assert " world" in tokens

    def test_stops_on_done(self, llm: OllamaLLM) -> None:
        lines = [
            json.dumps({"message": {"content": "first"}, "done": False}),
            json.dumps({"message": {"content": "second"}, "done": True}),
            json.dumps({"message": {"content": "third"}, "done": False}),  # should not be yielded
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = lines
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.post", return_value=mock_resp):
            tokens = list(llm.generate("prompt", stream=True))
        assert "third" not in tokens

    def test_skips_empty_tokens(self, llm: OllamaLLM) -> None:
        lines = [
            json.dumps({"message": {"content": ""}, "done": False}),
            json.dumps({"message": {"content": "data"}, "done": True}),
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = lines
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.post", return_value=mock_resp):
            tokens = list(llm.generate("prompt", stream=True))
        assert "" not in tokens
