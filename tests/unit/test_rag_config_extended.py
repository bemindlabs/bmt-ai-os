"""Extended unit tests for bmt_ai_os.rag.config.RAGConfig.

Covers environment variable overrides, field validation, and edge cases
not covered in the existing test_rag_query.py.
"""

from __future__ import annotations

from bmt_ai_os.rag.config import RAGConfig

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestRAGConfigDefaults:
    def test_chromadb_url_default(self):
        cfg = RAGConfig()
        assert cfg.chromadb_url == "http://localhost:8000"

    def test_ollama_url_default(self):
        cfg = RAGConfig()
        assert cfg.ollama_url == "http://localhost:11434"

    def test_embedding_model_default(self):
        cfg = RAGConfig()
        assert cfg.embedding_model == "nomic-embed-text"

    def test_chunk_size_default(self):
        cfg = RAGConfig()
        assert cfg.chunk_size == 512

    def test_chunk_overlap_default(self):
        cfg = RAGConfig()
        assert cfg.chunk_overlap == 64

    def test_top_k_default(self):
        cfg = RAGConfig()
        assert cfg.top_k == 5

    def test_temperature_default(self):
        cfg = RAGConfig()
        assert cfg.temperature == 0.7

    def test_top_p_default(self):
        cfg = RAGConfig()
        assert cfg.top_p == 0.9

    def test_max_tokens_default(self):
        cfg = RAGConfig()
        assert cfg.max_tokens == 2048

    def test_llm_timeout_default(self):
        cfg = RAGConfig()
        assert cfg.llm_timeout == 120

    def test_embed_timeout_default(self):
        cfg = RAGConfig()
        assert cfg.embed_timeout == 30

    def test_prompt_template_default_none(self):
        cfg = RAGConfig()
        assert cfg.prompt_template is None

    def test_llm_model_contains_qwen(self):
        cfg = RAGConfig()
        assert "qwen" in cfg.llm_model


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestRAGConfigEnvOverrides:
    def test_chromadb_url_env(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_CHROMADB_URL", "http://chroma:9000")
        cfg = RAGConfig()
        assert cfg.chromadb_url == "http://chroma:9000"

    def test_ollama_url_env(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_OLLAMA_URL", "http://ollama-server:11434")
        cfg = RAGConfig()
        assert cfg.ollama_url == "http://ollama-server:11434"

    def test_embedding_model_env(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_EMBEDDING_MODEL", "mxbai-embed-large")
        cfg = RAGConfig()
        assert cfg.embedding_model == "mxbai-embed-large"

    def test_llm_model_env(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_LLM_MODEL", "llama3:70b")
        cfg = RAGConfig()
        assert cfg.llm_model == "llama3:70b"

    def test_env_override_does_not_affect_non_env_fields(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_CHROMADB_URL", "http://custom:8000")
        cfg = RAGConfig()
        # Non-env fields should still use defaults
        assert cfg.chunk_size == 512
        assert cfg.top_k == 5


# ---------------------------------------------------------------------------
# Direct construction
# ---------------------------------------------------------------------------


class TestRAGConfigDirect:
    def test_custom_chunk_size(self):
        cfg = RAGConfig(chunk_size=1024)
        assert cfg.chunk_size == 1024

    def test_custom_chunk_overlap(self):
        cfg = RAGConfig(chunk_overlap=128)
        assert cfg.chunk_overlap == 128

    def test_custom_top_k(self):
        cfg = RAGConfig(top_k=10)
        assert cfg.top_k == 10

    def test_custom_temperature(self):
        cfg = RAGConfig(temperature=0.1)
        assert cfg.temperature == 0.1

    def test_custom_max_tokens(self):
        cfg = RAGConfig(max_tokens=4096)
        assert cfg.max_tokens == 4096

    def test_custom_prompt_template(self):
        cfg = RAGConfig(prompt_template="/etc/bmt/prompt.txt")
        assert cfg.prompt_template == "/etc/bmt/prompt.txt"

    def test_custom_timeouts(self):
        cfg = RAGConfig(llm_timeout=60, embed_timeout=10)
        assert cfg.llm_timeout == 60
        assert cfg.embed_timeout == 10

    def test_full_custom_construction(self):
        cfg = RAGConfig(
            chromadb_url="http://chroma:9000",
            ollama_url="http://ollama:11434",
            embedding_model="nomic-embed-text",
            chunk_size=256,
            chunk_overlap=32,
            top_k=3,
            llm_model="phi3:mini",
            temperature=0.5,
            top_p=0.95,
            max_tokens=1024,
            llm_timeout=90,
            embed_timeout=15,
        )
        assert cfg.chromadb_url == "http://chroma:9000"
        assert cfg.chunk_size == 256
        assert cfg.top_k == 3
        assert cfg.llm_model == "phi3:mini"
