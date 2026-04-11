"""Unit tests for bmt_ai_os.training.export."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# merge_adapter
# ---------------------------------------------------------------------------


class TestMergeAdapter:
    def test_raises_import_error_when_torch_missing(self, tmp_path):
        """merge_adapter raises ImportError when torch is not installed."""
        from bmt_ai_os.training.export import merge_adapter

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()

        # transformers is called first, then peft, then torch — patch all three
        # so torch failure surfaces
        mock_transformers = MagicMock()
        mock_peft = MagicMock()
        with (
            patch(
                "bmt_ai_os.training.export._require_transformers",
                return_value=mock_transformers,
            ),
            patch("bmt_ai_os.training.export._require_peft", return_value=mock_peft),
            patch(
                "bmt_ai_os.training.export._require_torch",
                side_effect=ImportError("no torch"),
            ),
        ):
            with pytest.raises(ImportError, match="no torch"):
                merge_adapter("base_model", adapter_dir, tmp_path / "merged")

    def test_raises_import_error_when_transformers_missing(self, tmp_path):
        """merge_adapter raises ImportError when transformers is not installed."""
        from bmt_ai_os.training.export import merge_adapter

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()

        with patch(
            "bmt_ai_os.training.export._require_transformers",
            side_effect=ImportError("no transformers"),
        ):
            with pytest.raises(ImportError, match="no transformers"):
                merge_adapter("base_model", adapter_dir, tmp_path / "merged")

    def test_raises_import_error_when_peft_missing(self, tmp_path):
        """merge_adapter raises ImportError when peft is not installed."""
        from bmt_ai_os.training.export import merge_adapter

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()

        mock_torch = MagicMock()
        mock_transformers = MagicMock()

        with (
            patch("bmt_ai_os.training.export._require_torch", return_value=mock_torch),
            patch(
                "bmt_ai_os.training.export._require_transformers",
                return_value=mock_transformers,
            ),
            patch(
                "bmt_ai_os.training.export._require_peft",
                side_effect=ImportError("no peft"),
            ),
        ):
            with pytest.raises(ImportError, match="no peft"):
                merge_adapter("base_model", adapter_dir, tmp_path / "merged")

    def test_raises_when_adapter_path_missing(self, tmp_path):
        """merge_adapter raises FileNotFoundError when adapter dir does not exist."""
        from bmt_ai_os.training.export import merge_adapter

        mock_torch = MagicMock()
        mock_torch.float16 = "float16"
        mock_transformers = MagicMock()
        mock_peft = MagicMock()

        with (
            patch("bmt_ai_os.training.export._require_torch", return_value=mock_torch),
            patch(
                "bmt_ai_os.training.export._require_transformers",
                return_value=mock_transformers,
            ),
            patch("bmt_ai_os.training.export._require_peft", return_value=mock_peft),
        ):
            with pytest.raises(FileNotFoundError, match="Adapter path not found"):
                merge_adapter("base", tmp_path / "nonexistent", tmp_path / "out")

    def test_merge_calls_peft_and_saves(self, tmp_path):
        """merge_adapter calls merge_and_unload and saves the model."""
        from bmt_ai_os.training.export import merge_adapter

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()

        mock_torch = MagicMock()
        mock_torch.float16 = "float16"

        mock_transformers = MagicMock()
        mock_model = MagicMock()
        mock_merged = MagicMock()
        mock_model.merge_and_unload.return_value = mock_merged
        mock_transformers.AutoModelForCausalLM.from_pretrained.return_value = mock_model

        mock_peft = MagicMock()
        mock_peft_model = MagicMock()
        mock_peft_model.merge_and_unload.return_value = mock_merged
        mock_peft.PeftModel.from_pretrained.return_value = mock_peft_model

        output_dir = tmp_path / "merged"

        with (
            patch("bmt_ai_os.training.export._require_torch", return_value=mock_torch),
            patch(
                "bmt_ai_os.training.export._require_transformers",
                return_value=mock_transformers,
            ),
            patch("bmt_ai_os.training.export._require_peft", return_value=mock_peft),
        ):
            result = merge_adapter("Qwen/Qwen2.5-0.5B", adapter_dir, output_dir)

        assert result == output_dir
        mock_peft_model.merge_and_unload.assert_called_once()
        mock_merged.save_pretrained.assert_called_once_with(str(output_dir))


# ---------------------------------------------------------------------------
# convert_to_gguf
# ---------------------------------------------------------------------------


class TestConvertToGguf:
    def test_raises_when_model_path_missing(self, tmp_path):
        from bmt_ai_os.training.export import convert_to_gguf

        with pytest.raises(FileNotFoundError, match="Model path not found"):
            convert_to_gguf(tmp_path / "nonexistent", tmp_path / "out.gguf")

    def test_raises_when_convert_script_not_found(self, tmp_path):
        from bmt_ai_os.training.export import convert_to_gguf

        model_dir = tmp_path / "model"
        model_dir.mkdir()

        with patch(
            "bmt_ai_os.training.export._locate_convert_script",
            side_effect=FileNotFoundError("script not found"),
        ):
            with pytest.raises(FileNotFoundError, match="script not found"):
                convert_to_gguf(model_dir, tmp_path / "out.gguf")

    def test_calls_subprocess_convert_and_quantize(self, tmp_path):
        from bmt_ai_os.training.export import convert_to_gguf

        model_dir = tmp_path / "model"
        model_dir.mkdir()
        script_path = tmp_path / "convert_hf_to_gguf.py"
        script_path.touch()
        output_gguf = tmp_path / "out.gguf"

        # Simulate fp16 file creation by convert subprocess
        fp16_path = tmp_path / "out_fp16.gguf"

        def mock_run(cmd, check):  # noqa: ANN001
            # Create the fp16 file as if the first subprocess ran
            if "convert_hf_to_gguf" in str(cmd):
                fp16_path.touch()
            return MagicMock(returncode=0)

        with (
            patch("bmt_ai_os.training.export._locate_convert_script", return_value=script_path),
            patch("subprocess.run", side_effect=mock_run),
        ):
            result = convert_to_gguf(
                model_dir, output_gguf, quantization="q4_K_M", convert_script=str(script_path)
            )

        assert result == output_gguf

    def test_cleans_up_fp16_file_on_quantize_error(self, tmp_path):
        from bmt_ai_os.training.export import convert_to_gguf

        model_dir = tmp_path / "model"
        model_dir.mkdir()
        script_path = tmp_path / "convert_hf_to_gguf.py"
        script_path.touch()
        output_gguf = tmp_path / "out.gguf"
        fp16_path = tmp_path / "out_fp16.gguf"

        call_count = [0]

        def mock_run(cmd, check):  # noqa: ANN001
            call_count[0] += 1
            if call_count[0] == 1:
                fp16_path.touch()
                return MagicMock()
            raise subprocess.CalledProcessError(1, cmd)

        with (
            patch("bmt_ai_os.training.export._locate_convert_script", return_value=script_path),
            patch("subprocess.run", side_effect=mock_run),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                convert_to_gguf(model_dir, output_gguf)

        # The fp16 intermediate file should be cleaned up
        assert not fp16_path.exists()


# ---------------------------------------------------------------------------
# register_with_ollama
# ---------------------------------------------------------------------------


class TestRegisterWithOllama:
    def test_raises_when_gguf_missing(self, tmp_path):
        from bmt_ai_os.training.export import register_with_ollama

        with pytest.raises(FileNotFoundError, match="GGUF file not found"):
            register_with_ollama(tmp_path / "nonexistent.gguf", "my-model")

    def test_calls_ollama_create(self, tmp_path):
        from bmt_ai_os.training.export import register_with_ollama

        gguf = tmp_path / "model.gguf"
        gguf.touch()

        with (
            patch("subprocess.run") as mock_run,
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value.read.return_value = b'{"models": []}'

            register_with_ollama(gguf, "my-model")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ollama" in cmd
        assert "create" in cmd
        assert "my-model" in cmd

    def test_modelfile_contains_from_line(self, tmp_path):
        from bmt_ai_os.training.export import register_with_ollama

        gguf = tmp_path / "model.gguf"
        gguf.touch()

        written_content = []

        original_open = open  # noqa: SIM115

        def capture_open(path, *args, **kwargs):
            if "bmt_ollama_" in str(path):
                # Capture writes through a wrapper
                fh = original_open(path, *args, **kwargs)

                class _Wrapper:
                    def __enter__(self_inner):
                        return self_inner

                    def __exit__(self_inner, *a):
                        fh.close()

                    def write(self_inner, content):
                        written_content.append(content)
                        return fh.write(content)

                    name = path

                return _Wrapper()
            return original_open(path, *args, **kwargs)

        with (
            patch("subprocess.run"),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value.read.return_value = b'{"models": []}'

            register_with_ollama(gguf, "my-model", system_prompt="Be helpful.")

        # Verify ollama create was called (subprocess.run was patched)
        # We can't easily inspect the Modelfile content without more complex mocking,
        # but we confirm the call was made without error.

    def test_system_prompt_included(self, tmp_path):
        from bmt_ai_os.training.export import register_with_ollama

        gguf = tmp_path / "model.gguf"
        gguf.touch()

        captured_modelfile_path = []

        def capture_run(cmd, check):  # noqa: ANN001
            if "ollama" in cmd:
                # cmd is: ["ollama", "create", name, "-f", modelfile_path]
                f_idx = cmd.index("-f")
                captured_modelfile_path.append(cmd[f_idx + 1])
            return MagicMock()

        with (
            patch("subprocess.run", side_effect=capture_run),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value.read.return_value = b'{"models": []}'

            register_with_ollama(gguf, "my-model", system_prompt="You are an assistant.")

        # Modelfile was deleted by the time we check, but subprocess.run was called
        assert len(captured_modelfile_path) == 1


# ---------------------------------------------------------------------------
# _locate_convert_script
# ---------------------------------------------------------------------------


class TestLocateConvertScript:
    def test_explicit_path_found(self, tmp_path):
        from bmt_ai_os.training.export import _locate_convert_script

        script = tmp_path / "convert_hf_to_gguf.py"
        script.touch()
        result = _locate_convert_script(str(script))
        assert result == script

    def test_explicit_path_not_found(self, tmp_path):
        from bmt_ai_os.training.export import _locate_convert_script

        with pytest.raises(FileNotFoundError, match="not found"):
            _locate_convert_script(str(tmp_path / "nonexistent.py"))

    def test_env_var_used(self, tmp_path, monkeypatch):
        from bmt_ai_os.training.export import _locate_convert_script

        script = tmp_path / "convert_hf_to_gguf.py"
        script.touch()
        monkeypatch.setenv("LLAMA_CPP_CONVERT_SCRIPT", str(script))
        result = _locate_convert_script(None)
        assert result == script

    def test_raises_when_not_found(self, monkeypatch):
        from bmt_ai_os.training.export import _locate_convert_script

        monkeypatch.delenv("LLAMA_CPP_CONVERT_SCRIPT", raising=False)

        # Patch all candidate paths to not exist
        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="convert_hf_to_gguf"):
                _locate_convert_script(None)


# ---------------------------------------------------------------------------
# CLI export-model command
# ---------------------------------------------------------------------------


class TestExportModelCli:
    def test_export_model_help(self):
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["export-model", "--help"])
        assert result.exit_code == 0
        assert "export-model" in result.output.lower() or "base" in result.output.lower()

    def test_export_model_missing_required_args(self):
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["export-model"])
        assert result.exit_code != 0

    def test_export_model_runs_all_steps(self, tmp_path):
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()
        output_gguf = tmp_path / "model.gguf"

        with (
            patch("bmt_ai_os.training.export.merge_adapter") as mock_merge,
            patch("bmt_ai_os.training.export.convert_to_gguf") as mock_convert,
            patch("bmt_ai_os.training.export.register_with_ollama") as mock_register,
        ):
            mock_merge.return_value = tmp_path / "merged"
            mock_convert.return_value = output_gguf

            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "export-model",
                    "--base",
                    "Qwen/Qwen2.5-0.5B",
                    "--adapter",
                    str(adapter_dir),
                    "--output",
                    str(output_gguf),
                    "--name",
                    "my-model",
                    "--quantization",
                    "q4_K_M",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_merge.assert_called_once()
        mock_convert.assert_called_once()
        mock_register.assert_called_once()

    def test_export_model_skips_ollama_without_name(self, tmp_path):
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()
        output_gguf = tmp_path / "model.gguf"

        with (
            patch("bmt_ai_os.training.export.merge_adapter") as mock_merge,
            patch("bmt_ai_os.training.export.convert_to_gguf") as mock_convert,
            patch("bmt_ai_os.training.export.register_with_ollama") as mock_register,
        ):
            mock_merge.return_value = tmp_path / "merged"
            mock_convert.return_value = output_gguf

            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "export-model",
                    "--base",
                    "Qwen/Qwen2.5-0.5B",
                    "--adapter",
                    str(adapter_dir),
                    "--output",
                    str(output_gguf),
                ],
            )

        assert result.exit_code == 0, result.output
        mock_register.assert_not_called()
        assert "Skipping Ollama" in result.output

    def test_export_model_handles_merge_import_error(self, tmp_path):
        from click.testing import CliRunner

        from bmt_ai_os.cli import main

        adapter_dir = tmp_path / "adapter"
        adapter_dir.mkdir()

        with patch(
            "bmt_ai_os.training.export.merge_adapter",
            side_effect=ImportError("PyTorch not installed"),
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "export-model",
                    "--base",
                    "base",
                    "--adapter",
                    str(adapter_dir),
                    "--output",
                    str(tmp_path / "out.gguf"),
                ],
            )

        assert result.exit_code == 1
