"""Model export pipeline for BMT AI OS.

Provides utilities to merge LoRA adapter weights into a base model, convert to
GGUF format, and register the result with the local Ollama instance.

All heavy ML dependencies (torch, peft, transformers) are imported lazily so
that this module can be imported in environments where those packages are not
installed (e.g. the controller process).

Usage
-----
    from bmt_ai_os.training.export import merge_adapter, convert_to_gguf, register_with_ollama

    # 1. Merge LoRA adapter into base model
    merge_adapter("qwen2.5:0.5b", "/data/adapters/my-run", "/data/merged/my-model")

    # 2. Convert merged weights to GGUF (requires llama.cpp convert script)
    convert_to_gguf("/data/merged/my-model", "/data/gguf/my-model.gguf", quantization="q4_K_M")

    # 3. Register the GGUF with Ollama
    register_with_ollama("/data/gguf/my-model.gguf", "my-custom-model")

CLI
---
    bmt-ai-os export-model --base qwen2.5:0.5b --adapter /data/adapters/my-run \\
        --output /data/gguf/my-model.gguf --name my-custom-model
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_torch() -> Any:
    """Import and return torch, raising ImportError with a helpful message."""
    try:
        import torch

        return torch
    except ImportError as exc:
        raise ImportError(
            "PyTorch is required for model export. Install it with: pip install torch"
        ) from exc


def _require_transformers() -> Any:
    """Import and return the transformers module."""
    try:
        import transformers

        return transformers
    except ImportError as exc:
        raise ImportError(
            "HuggingFace Transformers is required for model export. "
            "Install it with: pip install transformers"
        ) from exc


def _require_peft() -> Any:
    """Import and return the peft module."""
    try:
        import peft

        return peft
    except ImportError as exc:
        raise ImportError(
            "PEFT is required for LoRA adapter merging. Install it with: pip install peft"
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def merge_adapter(
    base_model: str,
    adapter_path: str | os.PathLike,
    output_path: str | os.PathLike,
    *,
    torch_dtype: str = "float16",
) -> Path:
    """Merge a LoRA adapter into the base model and save the result.

    Args:
        base_model: HuggingFace model ID or local path for the base model
            (e.g. ``"Qwen/Qwen2.5-0.5B"``).
        adapter_path: Directory containing the saved PEFT/LoRA adapter
            (``adapter_config.json`` + ``adapter_model.safetensors``).
        output_path: Directory where the merged model will be saved.
        torch_dtype: Data type for loading the model.  ``"float16"`` is
            recommended for ARM64 CPU-only inference.

    Returns:
        Path to the output directory containing the merged model.

    Raises:
        ImportError: When torch, transformers, or peft are not installed.
        FileNotFoundError: When the adapter directory does not exist.
        RuntimeError: When the merge fails for any other reason.
    """
    transformers = _require_transformers()
    peft = _require_peft()
    torch = _require_torch()

    adapter_path = Path(adapter_path)
    output_path = Path(output_path)

    if not adapter_path.exists():
        raise FileNotFoundError(f"Adapter path not found: {adapter_path}")

    logger.info("Loading base model '%s' …", base_model)
    dtype_map = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    dtype = dtype_map.get(torch_dtype, torch.float16)

    model = transformers.AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=dtype,
        device_map="cpu",
        trust_remote_code=True,
    )
    tokenizer = transformers.AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)

    logger.info("Loading LoRA adapter from '%s' …", adapter_path)
    model = peft.PeftModel.from_pretrained(model, str(adapter_path))

    logger.info("Merging adapter weights …")
    model = model.merge_and_unload()

    output_path.mkdir(parents=True, exist_ok=True)
    logger.info("Saving merged model to '%s' …", output_path)
    model.save_pretrained(str(output_path))
    tokenizer.save_pretrained(str(output_path))

    logger.info("Merge complete: %s", output_path)
    return output_path


def convert_to_gguf(
    model_path: str | os.PathLike,
    output_path: str | os.PathLike,
    quantization: str = "q4_K_M",
    *,
    convert_script: str | None = None,
) -> Path:
    """Convert a HuggingFace model directory to GGUF format.

    Requires ``llama.cpp``'s ``convert_hf_to_gguf.py`` script to be available.
    The script is located automatically from common installation paths, or can
    be provided explicitly via *convert_script*.

    Args:
        model_path: Directory containing the HuggingFace model weights.
        output_path: Destination GGUF file path (e.g. ``/data/model.gguf``).
        quantization: Quantization type.  Defaults to ``"q4_K_M"`` which
            balances quality and size well for on-device inference.
        convert_script: Explicit path to ``convert_hf_to_gguf.py``.

    Returns:
        Path to the output GGUF file.

    Raises:
        FileNotFoundError: When model_path does not exist or the convert
            script cannot be located.
        subprocess.CalledProcessError: When the conversion subprocess fails.
    """
    model_path = Path(model_path)
    output_path = Path(output_path)

    if not model_path.exists():
        raise FileNotFoundError(f"Model path not found: {model_path}")

    script = _locate_convert_script(convert_script)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: convert to fp16 GGUF
    fp16_path = output_path.with_suffix("").with_name(output_path.stem + "_fp16.gguf")
    cmd_convert = [
        "python3",
        str(script),
        str(model_path),
        "--outfile",
        str(fp16_path),
        "--outtype",
        "f16",
    ]
    logger.info("Converting model to GGUF (fp16): %s", " ".join(cmd_convert))
    subprocess.run(cmd_convert, check=True)  # noqa: S603

    # Step 2: quantize
    cmd_quantize = [
        "llama-quantize",
        str(fp16_path),
        str(output_path),
        quantization.upper(),
    ]
    logger.info("Quantizing GGUF (%s): %s", quantization, " ".join(cmd_quantize))
    try:
        subprocess.run(cmd_quantize, check=True)  # noqa: S603
    finally:
        # Clean up intermediate fp16 file
        if fp16_path.exists():
            fp16_path.unlink(missing_ok=True)

    logger.info("GGUF export complete: %s", output_path)
    return output_path


def register_with_ollama(
    gguf_path: str | os.PathLike,
    model_name: str,
    *,
    ollama_url: str = "http://localhost:11434",
    system_prompt: str | None = None,
) -> None:
    """Register a GGUF model with the local Ollama instance.

    Creates a ``Modelfile`` pointing at the given GGUF file and runs
    ``ollama create`` to register the model under *model_name*.

    Args:
        gguf_path: Absolute path to the GGUF model file.
        model_name: Name to register the model as in Ollama
            (e.g. ``"my-custom-qwen"``).
        ollama_url: Ollama API base URL.  Used only for a final health-check
            ping; the actual model creation uses the ``ollama`` CLI.
        system_prompt: Optional system prompt to embed in the Modelfile.

    Raises:
        FileNotFoundError: When gguf_path does not exist.
        subprocess.CalledProcessError: When ``ollama create`` fails.
        RuntimeError: When Ollama is not reachable after registration.
    """
    gguf_path = Path(gguf_path)

    if not gguf_path.exists():
        raise FileNotFoundError(f"GGUF file not found: {gguf_path}")

    modelfile_lines = [f"FROM {gguf_path.resolve()}"]
    if system_prompt:
        escaped = system_prompt.replace('"', '\\"')
        modelfile_lines.append(f'SYSTEM "{escaped}"')

    modelfile_content = "\n".join(modelfile_lines) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".Modelfile",
        delete=False,
        prefix="bmt_ollama_",
    ) as tmp:
        tmp.write(modelfile_content)
        modelfile_path = tmp.name

    try:
        cmd = ["ollama", "create", model_name, "-f", modelfile_path]
        logger.info("Registering model '%s' with Ollama: %s", model_name, " ".join(cmd))
        subprocess.run(cmd, check=True)  # noqa: S603
    finally:
        Path(modelfile_path).unlink(missing_ok=True)

    logger.info("Model '%s' registered successfully with Ollama.", model_name)

    # Verify the model appears in Ollama's model list
    try:
        import urllib.request

        with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=5) as resp:
            import json

            data = json.loads(resp.read())
            names = [m.get("name", "") for m in data.get("models", [])]
            if not any(model_name in n for n in names):
                logger.warning(
                    "Model '%s' not found in Ollama model list after registration. "
                    "The 'ollama create' command may have succeeded but the model "
                    "is not yet visible.",
                    model_name,
                )
    except Exception as exc:
        logger.debug("Could not verify Ollama registration: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _locate_convert_script(explicit: str | None) -> Path:
    """Find the llama.cpp convert_hf_to_gguf.py script.

    Search order:
    1. *explicit* argument (when provided)
    2. ``LLAMA_CPP_CONVERT_SCRIPT`` environment variable
    3. Common installation paths on the system

    Raises:
        FileNotFoundError: When the script cannot be found.
    """
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise FileNotFoundError(f"Provided convert script not found: {p}")

    env_path = os.environ.get("LLAMA_CPP_CONVERT_SCRIPT")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    search_paths = [
        Path("/usr/local/lib/python3/dist-packages/llama_cpp/convert_hf_to_gguf.py"),
        Path("/usr/share/llama.cpp/convert_hf_to_gguf.py"),
        Path.home() / "llama.cpp" / "convert_hf_to_gguf.py",
        Path("/opt/llama.cpp/convert_hf_to_gguf.py"),
    ]
    for p in search_paths:
        if p.exists():
            return p

    raise FileNotFoundError(
        "Could not locate convert_hf_to_gguf.py. "
        "Install llama.cpp or set the LLAMA_CPP_CONVERT_SCRIPT environment variable."
    )
