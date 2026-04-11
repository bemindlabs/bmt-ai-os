"""Security tests for the RAG ingest endpoint and request validation.

Covers:
- Collection name validation (regex ^[a-zA-Z0-9_-]{1,100}$)
- QueryRequest.question max_length enforcement
- Path traversal protection in the ingest endpoint
- Symlink traversal blocked via Path.resolve()
- Requests outside the whitelist return 403
- Relative paths rejected by IngestRequest validator
- BMT_INGEST_ALLOWED_DIRS env-var parsing in RAGConfig
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers / thin app fixture
# ---------------------------------------------------------------------------


def _make_client(allowed_dirs: list[str] | None = None) -> TestClient:
    """Return a TestClient whose _config has the given allowed_ingest_dirs."""
    from fastapi import FastAPI

    import bmt_ai_os.controller.rag_routes as rag_mod

    # Reload so module-level _config is freshly constructed.
    importlib.reload(rag_mod)

    if allowed_dirs is not None:
        resolved = [Path(d).resolve() for d in allowed_dirs]
        rag_mod._config.allowed_ingest_dirs = resolved
    else:
        rag_mod._config.allowed_ingest_dirs = []

    app = FastAPI()
    app.include_router(rag_mod.router, prefix="/rag")
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Collection name validation
# ---------------------------------------------------------------------------


class TestCollectionNameValidation:
    """Collection name must match ^[a-zA-Z0-9_-]{1,100}$."""

    @pytest.mark.parametrize(
        "name",
        [
            "default",
            "my-collection",
            "col_123",
            "A" * 100,
            "a",
        ],
    )
    def test_valid_collection_names_accepted(self, name: str) -> None:
        from bmt_ai_os.controller.rag_routes import IngestRequest

        req = IngestRequest(path="/tmp/docs", collection=name)
        assert req.collection == name

    @pytest.mark.parametrize(
        "bad_name",
        [
            "",  # empty
            " spaces ",  # whitespace
            "../etc/passwd",  # traversal
            "col/subdir",  # slash
            "col;drop",  # semicolon
            "A" * 101,  # too long
            "col\x00null",  # null byte
        ],
    )
    def test_invalid_collection_names_rejected(self, bad_name: str) -> None:
        from bmt_ai_os.controller.rag_routes import IngestRequest, QueryRequest

        with pytest.raises(ValidationError):
            IngestRequest(path="/tmp/docs", collection=bad_name)

        with pytest.raises(ValidationError):
            QueryRequest(question="q", collection=bad_name)


# ---------------------------------------------------------------------------
# QueryRequest.question max_length
# ---------------------------------------------------------------------------


class TestQuestionMaxLength:
    def test_question_within_limit_accepted(self) -> None:
        from bmt_ai_os.controller.rag_routes import QueryRequest

        req = QueryRequest(question="x" * 5000)
        assert len(req.question) == 5000

    def test_question_over_limit_rejected(self) -> None:
        from bmt_ai_os.controller.rag_routes import QueryRequest

        with pytest.raises(ValidationError):
            QueryRequest(question="x" * 5001)

    def test_empty_question_accepted(self) -> None:
        from bmt_ai_os.controller.rag_routes import QueryRequest

        req = QueryRequest(question="")
        assert req.question == ""


# ---------------------------------------------------------------------------
# IngestRequest path validator
# ---------------------------------------------------------------------------


class TestIngestRequestPathValidator:
    def test_absolute_path_accepted(self) -> None:
        from bmt_ai_os.controller.rag_routes import IngestRequest

        req = IngestRequest(path="/tmp/docs")
        assert req.path == "/tmp/docs"

    def test_relative_path_rejected(self) -> None:
        from bmt_ai_os.controller.rag_routes import IngestRequest

        with pytest.raises(ValidationError, match="absolute"):
            IngestRequest(path="relative/path")

    def test_dot_dot_relative_rejected(self) -> None:
        from bmt_ai_os.controller.rag_routes import IngestRequest

        with pytest.raises(ValidationError, match="absolute"):
            IngestRequest(path="../etc/passwd")


# ---------------------------------------------------------------------------
# Path traversal protection in the ingest endpoint
# ---------------------------------------------------------------------------


class TestIngestPathTraversal:
    def test_path_inside_allowed_dir_returns_accepted(self, tmp_path: Path) -> None:
        allowed = str(tmp_path)
        target = str(tmp_path / "subdir")
        client = _make_client(allowed_dirs=[allowed])

        resp = client.post("/rag/ingest", json={"path": target, "collection": "col1"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_path_outside_allowed_dir_returns_403(self, tmp_path: Path) -> None:
        allowed = str(tmp_path / "safe")
        target = "/etc/passwd"
        client = _make_client(allowed_dirs=[allowed])

        resp = client.post("/rag/ingest", json={"path": target, "collection": "col1"})
        assert resp.status_code == 403

    def test_no_allowed_dirs_configured_returns_403(self, tmp_path: Path) -> None:
        client = _make_client(allowed_dirs=[])

        resp = client.post("/rag/ingest", json={"path": str(tmp_path), "collection": "col1"})
        assert resp.status_code == 403
        assert "BMT_INGEST_ALLOWED_DIRS" in resp.json()["detail"]

    def test_dot_dot_traversal_blocked(self, tmp_path: Path) -> None:
        """A path like /allowed/safe/../../../etc must be blocked."""
        allowed = str(tmp_path / "safe")
        # Construct a path that looks inside safe but escapes via ..
        traversal = str(tmp_path / "safe" / ".." / ".." / "etc" / "passwd")
        client = _make_client(allowed_dirs=[allowed])

        resp = client.post("/rag/ingest", json={"path": traversal, "collection": "col1"})
        assert resp.status_code == 403

    def test_symlink_traversal_blocked(self, tmp_path: Path) -> None:
        """A symlink inside an allowed dir that points outside must be blocked."""
        allowed_dir = tmp_path / "safe"
        allowed_dir.mkdir()
        outside_dir = tmp_path / "secret"
        outside_dir.mkdir()

        symlink = allowed_dir / "link"
        symlink.symlink_to(outside_dir)

        client = _make_client(allowed_dirs=[str(allowed_dir)])

        # The symlink target resolves to outside_dir, which is not under allowed_dir
        resp = client.post("/rag/ingest", json={"path": str(symlink), "collection": "col1"})
        assert resp.status_code == 403

    def test_multiple_allowed_dirs_first_matches(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        target_in_b = str(dir_b / "docs")
        client = _make_client(allowed_dirs=[str(dir_a), str(dir_b)])

        resp = client.post("/rag/ingest", json={"path": target_in_b, "collection": "col1"})
        assert resp.status_code == 200

    def test_path_exactly_equal_to_allowed_dir_accepted(self, tmp_path: Path) -> None:
        client = _make_client(allowed_dirs=[str(tmp_path)])

        resp = client.post("/rag/ingest", json={"path": str(tmp_path), "collection": "col1"})
        assert resp.status_code == 200

    def test_invalid_collection_returns_422(self, tmp_path: Path) -> None:
        client = _make_client(allowed_dirs=[str(tmp_path)])

        resp = client.post(
            "/rag/ingest",
            json={"path": str(tmp_path), "collection": "bad/name"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# RAGConfig: BMT_INGEST_ALLOWED_DIRS parsing
# ---------------------------------------------------------------------------


class TestRAGConfigAllowedIngestDirs:
    def test_empty_env_var_gives_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BMT_INGEST_ALLOWED_DIRS", raising=False)
        # Re-import config module to pick up env change
        import importlib

        import bmt_ai_os.rag.config as cfg_mod

        importlib.reload(cfg_mod)
        cfg = cfg_mod.RAGConfig()
        assert cfg.allowed_ingest_dirs == []

    def test_single_dir_parsed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("BMT_INGEST_ALLOWED_DIRS", str(tmp_path))
        import importlib

        import bmt_ai_os.rag.config as cfg_mod

        importlib.reload(cfg_mod)
        cfg = cfg_mod.RAGConfig()
        assert cfg.allowed_ingest_dirs == [tmp_path.resolve()]

    def test_multiple_dirs_parsed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        monkeypatch.setenv("BMT_INGEST_ALLOWED_DIRS", f"{dir_a}:{dir_b}")
        import importlib

        import bmt_ai_os.rag.config as cfg_mod

        importlib.reload(cfg_mod)
        cfg = cfg_mod.RAGConfig()
        assert cfg.allowed_ingest_dirs == [dir_a.resolve(), dir_b.resolve()]

    def test_whitespace_only_env_gives_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BMT_INGEST_ALLOWED_DIRS", "   ")
        import importlib

        import bmt_ai_os.rag.config as cfg_mod

        importlib.reload(cfg_mod)
        cfg = cfg_mod.RAGConfig()
        assert cfg.allowed_ingest_dirs == []
