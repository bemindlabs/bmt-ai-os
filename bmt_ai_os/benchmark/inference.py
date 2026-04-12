"""Inference benchmark — measures throughput (tok/s) and first-token latency.

Uses the Ollama /api/generate endpoint with streaming enabled so that first-token
latency can be captured independently from total generation time.  All timing uses
``time.perf_counter()`` for sub-millisecond resolution.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

# Prompt that reliably produces a multi-token response without requiring any
# context; short enough to keep benchmark runs fast.
_BENCH_PROMPT = (
    "Write a concise explanation of how transformer attention works. "
    "Use exactly three numbered points."
)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_GENERATE_TIMEOUT = 300  # seconds — large models on ARM64 can be slow


@dataclass
class InferenceResult:
    """Results from a single inference benchmark run."""

    model: str
    prompt_tokens: int
    generated_tokens: int
    first_token_ms: float
    total_ms: float
    throughput_tok_s: float
    memory_peak_mb: float

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "generated_tokens": self.generated_tokens,
            "first_token_ms": round(self.first_token_ms, 1),
            "total_ms": round(self.total_ms, 1),
            "throughput_tok_s": round(self.throughput_tok_s, 2),
            "memory_peak_mb": round(self.memory_peak_mb, 1),
        }


def run(
    model: str,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    prompt: str = _BENCH_PROMPT,
    warmup: bool = True,
) -> InferenceResult:
    """Benchmark inference for *model* and return an :class:`InferenceResult`.

    Parameters
    ----------
    model:
        Ollama model tag, e.g. ``"qwen2.5:0.5b"``.
    ollama_url:
        Base URL of the Ollama service.
    prompt:
        Prompt text to use for the benchmark.
    warmup:
        When ``True``, run one silent warmup generation before timing.
        This avoids cold-start model-load latency polluting the result.
    """
    base = ollama_url.rstrip("/")

    if warmup:
        logger.debug("Running warmup generation for %s", model)
        _generate_stream(base, model, "Hello.", collect_tokens=False)

    logger.debug("Starting timed inference benchmark for %s", model)
    first_token_ms, generated_tokens, total_ms = _generate_stream(
        base, model, prompt, collect_tokens=True
    )

    # Derive throughput; guard against zero division on very fast responses.
    throughput = generated_tokens / (total_ms / 1000.0) if total_ms > 0 else 0.0

    # Read memory usage from Ollama process info (best-effort).
    memory_peak_mb = _read_model_memory_mb(base, model)

    return InferenceResult(
        model=model,
        prompt_tokens=_count_prompt_tokens(prompt),
        generated_tokens=generated_tokens,
        first_token_ms=first_token_ms,
        total_ms=total_ms,
        throughput_tok_s=throughput,
        memory_peak_mb=memory_peak_mb,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_stream(
    base_url: str,
    model: str,
    prompt: str,
    collect_tokens: bool = True,
) -> tuple[float, int, float]:
    """Call ``/api/generate`` with streaming and return timing metrics.

    Returns
    -------
    tuple[float, int, float]
        ``(first_token_ms, token_count, total_ms)``
    """
    url = f"{base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0.0},  # deterministic output for reproducibility
    }

    first_token_ms = 0.0
    token_count = 0
    t_start = time.perf_counter()
    first_seen = False

    try:
        with requests.post(url, json=payload, stream=True, timeout=_GENERATE_TIMEOUT) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                if collect_tokens and not first_seen and chunk.get("response"):
                    first_token_ms = (time.perf_counter() - t_start) * 1000
                    first_seen = True

                if collect_tokens:
                    token_count += 1

                if chunk.get("done"):
                    # Ollama reports eval_count (generated tokens) in the final chunk.
                    if collect_tokens and chunk.get("eval_count"):
                        token_count = int(chunk["eval_count"])
                    break
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    total_ms = (time.perf_counter() - t_start) * 1000
    return first_token_ms, token_count, total_ms


def _read_model_memory_mb(base_url: str, model: str) -> float:
    """Return approximate VRAM/RAM used by *model* in MB.

    Ollama exposes loaded model info via ``/api/ps``.  Falls back to 0.0 if
    the endpoint is unavailable or the model is not listed.
    """
    try:
        resp = requests.get(f"{base_url}/api/ps", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        for entry in data.get("models", []):
            if entry.get("name") == model or entry.get("model") == model:
                size_vram = entry.get("size_vram", 0) or 0
                size = entry.get("size", 0) or 0
                total_bytes = size_vram if size_vram else size
                return total_bytes / (1024 * 1024)
    except Exception:  # noqa: BLE001
        logger.debug("Could not determine model size", exc_info=True)
    return 0.0


def _count_prompt_tokens(text: str) -> int:
    """Rough token count estimate: split on whitespace (≈ BPE token count)."""
    return len(text.split())
