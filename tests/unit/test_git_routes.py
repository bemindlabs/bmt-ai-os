"""Unit tests for bmt_ai_os.controller.git_routes.

Tests cover:
- _parse_porcelain_status: various status code combinations
- _parse_diff_stat: addition/deletion counting from unified diff
- _require_git_repo: missing workspace and non-repo errors
- _sanitize_path: traversal and injection rejection
- GET /api/v1/git/status: happy-path and error cases
- GET /api/v1/git/diff: happy-path, file-scoped, truncation
- GET /api/v1/git/diff/staged: mirrors diff endpoint
- POST /api/v1/git/stage: files list and all=true variants
- POST /api/v1/git/unstage: happy-path and missing-files error
- POST /api/v1/git/commit: successful commit and validation
- GET /api/v1/git/log: parsing and limit clamping
- GET /api/v1/git/branches: branch list parsing
- POST /api/v1/git/checkout: valid branch, create flag, invalid name
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch):
    """Inject a JWT secret so auth middleware doesn't block requests."""
    monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-git-routes-tests32!")


@pytest.fixture()
def client():
    """Return a TestClient bound to the main FastAPI app."""
    from bmt_ai_os.controller.api import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fake_repo(tmp_path, monkeypatch):
    """Create a fake workspace directory with a .git subdirectory."""
    repo = tmp_path / "workspace"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("BMT_WORKSPACE_DIR", str(repo))
    monkeypatch.setenv("BMT_ENV", "dev")
    return repo


# ---------------------------------------------------------------------------
# Pure-logic unit tests (no subprocess)
# ---------------------------------------------------------------------------


class TestParsePorcelainStatus:
    def _call(self, raw: str) -> dict:
        from bmt_ai_os.controller.git_routes import _parse_porcelain_status

        return _parse_porcelain_status(raw)

    def test_empty_string(self):
        result = self._call("")
        assert result == {"modified": [], "staged": [], "untracked": []}

    def test_untracked_file(self):
        result = self._call("?? new_file.py")
        assert "new_file.py" in result["untracked"]
        assert result["modified"] == []
        assert result["staged"] == []

    def test_staged_new_file(self):
        result = self._call("A  staged.py")
        assert "staged.py" in result["staged"]
        assert result["untracked"] == []

    def test_modified_unstaged(self):
        result = self._call(" M unstaged.py")
        assert "unstaged.py" in result["modified"]
        assert result["staged"] == []

    def test_modified_staged_and_unstaged(self):
        # 'MM' means staged modification AND an additional unstaged modification
        result = self._call("MM both.py")
        assert "both.py" in result["staged"]
        assert "both.py" in result["modified"]

    def test_nul_separated_entries(self):
        # -z format uses NUL separators
        raw = "?? a.txt\x00 M b.txt\x00A  c.txt\x00"
        result = self._call(raw)
        assert "a.txt" in result["untracked"]
        assert "b.txt" in result["modified"]
        assert "c.txt" in result["staged"]

    def test_deleted_staged(self):
        result = self._call("D  deleted.py")
        assert "deleted.py" in result["staged"]

    def test_short_entry_skipped(self):
        # Entries shorter than 3 chars should not raise
        result = self._call("M")
        assert result["modified"] == []


class TestParseDiffStat:
    def _call(self, diff: str) -> list:
        from bmt_ai_os.controller.git_routes import _parse_diff_stat

        return _parse_diff_stat(diff)

    def test_empty_diff(self):
        assert self._call("") == []

    def test_single_file_additions_and_deletions(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+added line\n"
            " context\n"
            "-removed line\n"
            "+another addition\n"
        )
        result = self._call(diff)
        assert len(result) == 1
        entry = result[0]
        assert entry["path"] == "foo.py"
        assert entry["additions"] == 2
        assert entry["deletions"] == 1

    def test_multiple_files(self):
        diff = "+++ b/alpha.py\n+line1\n+++ b/beta.py\n-removed\n"
        result = self._call(diff)
        paths = {e["path"] for e in result}
        assert "alpha.py" in paths
        assert "beta.py" in paths


class TestRequireGitRepo:
    def test_missing_workspace_raises_404(self, tmp_path):
        from bmt_ai_os.controller.git_routes import _require_git_repo

        with pytest.raises(HTTPException) as exc_info:
            _require_git_repo(tmp_path / "nonexistent")
        assert exc_info.value.status_code == 404

    def test_non_git_directory_raises_400(self, tmp_path):
        from bmt_ai_os.controller.git_routes import _require_git_repo

        (tmp_path / "workspace").mkdir()
        with pytest.raises(HTTPException) as exc_info:
            _require_git_repo(tmp_path / "workspace")
        assert exc_info.value.status_code == 400

    def test_valid_git_repo_returns_path(self, tmp_path):
        from bmt_ai_os.controller.git_routes import _require_git_repo

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        result = _require_git_repo(repo)
        assert result == repo.resolve()


class TestSanitizePath:
    def _call(self, path: str, workspace: Path) -> str:
        from bmt_ai_os.controller.git_routes import _sanitize_path

        return _sanitize_path(path, workspace)

    def test_empty_path_returns_empty(self, tmp_path):
        assert self._call("", tmp_path) == ""

    def test_valid_relative_path(self, tmp_path):
        result = self._call("src/main.py", tmp_path)
        assert result == "src/main.py"

    def test_traversal_raises_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            self._call("../../etc/passwd", tmp_path)
        assert exc_info.value.status_code == 400

    def test_semicolon_in_path_raises_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            self._call("file;rm -rf /", tmp_path)
        assert exc_info.value.status_code == 400

    def test_pipe_in_path_raises_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            self._call("file|cat /etc/passwd", tmp_path)
        assert exc_info.value.status_code == 400

    def test_backtick_in_path_raises_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            self._call("file`id`", tmp_path)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Endpoint tests (subprocess mocked)
# ---------------------------------------------------------------------------


def _make_run_git(responses: list[tuple[int, str, str]]):
    """Return an AsyncMock that yields successive (rc, stdout, stderr) tuples."""
    call_count = [0]

    async def _mock(*args, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]

    return _mock


class TestStatusEndpoint:
    def test_happy_path(self, client, fake_repo):
        status_output = " M modified.py\x00A  staged.py\x00?? new.py\x00"
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            side_effect=_make_run_git(
                [
                    (0, "main\n", ""),  # rev-parse HEAD
                    (0, status_output, ""),  # status --porcelain -z
                ]
            ),
        ):
            resp = client.get("/api/v1/git/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["branch"] == "main"
        assert "modified.py" in body["modified"]
        assert "staged.py" in body["staged"]
        assert "new.py" in body["untracked"]

    def test_not_a_git_repo(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("BMT_WORKSPACE_DIR", str(tmp_path / "notarepo"))
        (tmp_path / "notarepo").mkdir()
        resp = client.get("/api/v1/git/status")
        assert resp.status_code == 400

    def test_git_status_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            side_effect=_make_run_git(
                [
                    (0, "main\n", ""),
                    (128, "", "fatal: not a repo"),
                ]
            ),
        ):
            resp = client.get("/api/v1/git/status")
        assert resp.status_code == 500


class TestDiffEndpoint:
    def test_unstaged_diff(self, client, fake_repo):
        diff_text = "+++ b/foo.py\n+new line\n"
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, diff_text, "")),
        ):
            resp = client.get("/api/v1/git/diff")
        assert resp.status_code == 200
        body = resp.json()
        assert body["diff"] == diff_text
        assert len(body["files"]) == 1

    def test_diff_with_path(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "", "")),
        ):
            resp = client.get("/api/v1/git/diff", params={"path": "src/app.py"})
        assert resp.status_code == 200

    def test_diff_truncated_at_1mb(self, client, fake_repo):
        big_diff = "+" + "x" * (1024 * 1024 + 100)
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, big_diff, "")),
        ):
            resp = client.get("/api/v1/git/diff")
        assert resp.status_code == 200
        body = resp.json()
        assert "truncated" in body["diff"]

    def test_diff_command_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(2, "", "fatal error")),
        ):
            resp = client.get("/api/v1/git/diff")
        assert resp.status_code == 500


class TestDiffStagedEndpoint:
    def test_staged_diff(self, client, fake_repo):
        diff_text = "+++ b/bar.py\n+staged line\n"
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, diff_text, "")),
        ):
            resp = client.get("/api/v1/git/diff/staged")
        assert resp.status_code == 200
        body = resp.json()
        assert body["diff"] == diff_text

    def test_staged_diff_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(128, "", "fatal")),
        ):
            resp = client.get("/api/v1/git/diff/staged")
        assert resp.status_code == 500


class TestStageEndpoint:
    def test_stage_specific_files(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "", "")),
        ):
            resp = client.post("/api/v1/git/stage", json={"files": ["a.py", "b.py"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "a.py" in body["staged"]

    def test_stage_all(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "", "")),
        ):
            resp = client.post("/api/v1/git/stage", json={"all": True})
        assert resp.status_code == 200
        assert resp.json()["all"] is True

    def test_stage_missing_params(self, client, fake_repo):
        resp = client.post("/api/v1/git/stage", json={})
        assert resp.status_code == 422

    def test_stage_git_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(1, "", "error: pathspec did not match")),
        ):
            resp = client.post("/api/v1/git/stage", json={"files": ["missing.py"]})
        assert resp.status_code == 500


class TestUnstageEndpoint:
    def test_unstage_files(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "", "")),
        ):
            resp = client.post("/api/v1/git/unstage", json={"files": ["staged.py"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "staged.py" in body["unstaged"]

    def test_unstage_empty_files_list(self, client, fake_repo):
        resp = client.post("/api/v1/git/unstage", json={"files": []})
        assert resp.status_code == 422

    def test_unstage_git_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(1, "", "error")),
        ):
            resp = client.post("/api/v1/git/unstage", json={"files": ["x.py"]})
        assert resp.status_code == 500


class TestCommitEndpoint:
    def test_successful_commit(self, client, fake_repo):
        commit_output = "[main abc1234] Add feature\n 2 files changed, 10 insertions(+)\n"
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, commit_output, "")),
        ):
            resp = client.post("/api/v1/git/commit", json={"message": "Add feature"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["hash"] == "abc1234"
        assert body["message"] == "Add feature"
        assert body["files_changed"] == 2

    def test_empty_message_rejected(self, client, fake_repo):
        resp = client.post("/api/v1/git/commit", json={"message": ""})
        assert resp.status_code == 422

    def test_whitespace_only_message_rejected(self, client, fake_repo):
        resp = client.post("/api/v1/git/commit", json={"message": "   "})
        assert resp.status_code == 422

    def test_commit_git_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(1, "", "nothing to commit")),
        ):
            resp = client.post("/api/v1/git/commit", json={"message": "empty"})
        assert resp.status_code == 400


class TestLogEndpoint:
    def test_returns_commits(self, client, fake_repo):
        log_output = (
            "abc123|First commit|Alice|2026-04-01 10:00:00 +0000\n"
            "def456|Second commit|Bob|2026-04-02 11:00:00 +0000\n"
        )
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, log_output, "")),
        ):
            resp = client.get("/api/v1/git/log")
        assert resp.status_code == 200
        commits = resp.json()["commits"]
        assert len(commits) == 2
        assert commits[0]["hash"] == "abc123"
        assert commits[0]["author"] == "Alice"

    def test_limit_clamped_to_100(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "", "")),
        ) as mock_git:
            resp = client.get("/api/v1/git/log", params={"limit": 9999})
        assert resp.status_code == 200
        # Verify the -n argument passed to git was clamped
        call_args = mock_git.call_args[0][0]  # first positional arg = args list
        assert "-n100" in call_args

    def test_log_git_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(128, "", "fatal")),
        ):
            resp = client.get("/api/v1/git/log")
        assert resp.status_code == 500


class TestBranchesEndpoint:
    def test_list_branches(self, client, fake_repo):
        branch_output = "main|abc123|*\ndevelop|def456| \nfeature/my-feature|ghi789| \n"
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, branch_output, "")),
        ):
            resp = client.get("/api/v1/git/branches")
        assert resp.status_code == 200
        body = resp.json()
        assert body["current"] == "main"
        names = [b["name"] for b in body["branches"]]
        assert "main" in names
        assert "develop" in names
        assert "feature/my-feature" in names
        # current branch has current=True
        main_branch = next(b for b in body["branches"] if b["name"] == "main")
        assert main_branch["current"] is True

    def test_branches_git_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(128, "", "fatal")),
        ):
            resp = client.get("/api/v1/git/branches")
        assert resp.status_code == 500


class TestCheckoutEndpoint:
    def test_checkout_existing_branch(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "Switched to branch 'develop'\n", "")),
        ):
            resp = client.post("/api/v1/git/checkout", json={"branch": "develop"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["branch"] == "develop"
        assert body["status"] == "ok"
        assert body["created"] is False

    def test_checkout_create_new_branch(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(0, "Switched to a new branch 'feature/x'\n", "")),
        ):
            resp = client.post("/api/v1/git/checkout", json={"branch": "feature/x", "create": True})
        assert resp.status_code == 200
        assert resp.json()["created"] is True

    def test_empty_branch_name_rejected(self, client, fake_repo):
        resp = client.post("/api/v1/git/checkout", json={"branch": ""})
        assert resp.status_code == 422

    def test_invalid_branch_name_with_dotdot(self, client, fake_repo):
        resp = client.post("/api/v1/git/checkout", json={"branch": "../evil"})
        assert resp.status_code == 400

    def test_invalid_branch_name_with_semicolon(self, client, fake_repo):
        resp = client.post("/api/v1/git/checkout", json={"branch": "branch;rm -rf /"})
        assert resp.status_code == 400

    def test_checkout_git_failure(self, client, fake_repo):
        with patch(
            "bmt_ai_os.controller.git_routes._run_git",
            new=AsyncMock(return_value=(1, "", "error: pathspec 'missing' did not match")),
        ):
            resp = client.post("/api/v1/git/checkout", json={"branch": "missing"})
        assert resp.status_code == 400
