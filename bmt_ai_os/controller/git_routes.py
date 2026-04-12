"""Git integration endpoints for the Code Editor.

GET  /api/v1/git/status       — git status (modified, staged, untracked files)
GET  /api/v1/git/diff          — git diff (unstaged changes)
GET  /api/v1/git/diff/staged   — git diff --staged
POST /api/v1/git/stage         — git add <files>
POST /api/v1/git/unstage       — git restore --staged <files>
POST /api/v1/git/commit        — git commit -m "<message>"
GET  /api/v1/git/log            — git log (last N commits)
GET  /api/v1/git/branches       — list branches
POST /api/v1/git/checkout       — switch branch
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/git", tags=["git"])

# Limit diff output to 1 MB to prevent runaway responses
_MAX_DIFF_BYTES = 1 * 1024 * 1024

# Git porcelain status codes → human-readable state
_STAGED_CODES = {"A", "M", "D", "R", "C"}
_UNSTAGED_CODES = {"M", "D"}


# ---------------------------------------------------------------------------
# Workspace / repo helpers
# ---------------------------------------------------------------------------


def _get_workspace() -> Path:
    """Return the workspace directory from environment or defaults."""
    env = os.environ.get("BMT_ENV", "production")
    default = str(Path.home() / "workspace") if env == "dev" else "/data/workspace"
    workspace = os.environ.get("BMT_WORKSPACE_DIR", default)
    return Path(workspace)


def _require_git_repo(workspace: Path) -> Path:
    """Validate workspace exists and is a git repository.

    Returns the resolved workspace path.
    Raises HTTPException(400) when the path is not a git repo.
    Raises HTTPException(404) when the path does not exist.
    """
    if not workspace.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Workspace directory not found: {workspace}",
        )

    git_dir = workspace / ".git"
    if not git_dir.exists():
        raise HTTPException(
            status_code=400,
            detail="Workspace is not a git repository.",
        )

    return workspace.resolve()


def _sanitize_path(path: str, workspace: Path) -> str:
    """Sanitize a file path to prevent path traversal outside workspace.

    Returns the path string suitable for passing to git commands.
    Raises HTTPException(400) for invalid or traversal paths.
    """
    if not path:
        return path

    # Resolve against workspace and confirm it stays inside
    try:
        resolved = (workspace / path.lstrip("/")).resolve()
        resolved.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Path '{path}' is outside the workspace directory.",
        )

    # Reject shell-special characters to prevent injection
    if re.search(r"[;&|`$<>]", path):
        raise HTTPException(
            status_code=400,
            detail="Path contains invalid characters.",
        )

    return path


async def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a git command in *cwd* and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_porcelain_status(raw: str) -> dict:
    """Parse ``git status --porcelain=v1`` output into categorised lists.

    Each NUL-terminated record is two status characters followed by the path
    (and optional renamed path after a NUL when using ``-z``).
    Falls back to line-by-line parsing when NUL separators are absent.
    """
    modified: list[str] = []
    staged: list[str] = []
    untracked: list[str] = []

    if not raw:
        return {"modified": modified, "staged": staged, "untracked": untracked}

    # ``git status --porcelain -z`` separates entries with NUL bytes.
    # Split on NUL; filter empty strings produced by trailing NUL.
    if "\x00" in raw:
        entries = [e for e in raw.split("\x00") if e]
    else:
        entries = [line for line in raw.splitlines() if line]

    for entry in entries:
        if len(entry) < 3:
            continue  # malformed — skip

        x = entry[0]  # index (staged) status
        y = entry[1]  # worktree (unstaged) status
        path = entry[3:]  # skip the two status chars + space

        # Untracked
        if x == "?" and y == "?":
            untracked.append(path)
            continue

        # Staged changes
        if x in _STAGED_CODES:
            staged.append(path)

        # Unstaged changes (worktree differs from index)
        if y in _UNSTAGED_CODES:
            modified.append(path)

    return {"modified": modified, "staged": staged, "untracked": untracked}


def _parse_diff_stat(diff_output: str) -> list[dict]:
    """Extract per-file addition/deletion counts from diff output.

    Scans for lines matching the ``+++ b/<path>`` header and the
    ``@@ … @@ `` hunk headers to build a summary.  Falls back to a simpler
    approach using ``--stat`` style lines when available.
    """
    files: dict[str, dict] = {}
    current_file: str | None = None

    for line in diff_output.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            if current_file not in files:
                files[current_file] = {"path": current_file, "additions": 0, "deletions": 0}
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            files[current_file]["additions"] += 1
        elif line.startswith("-") and not line.startswith("---") and current_file:
            files[current_file]["deletions"] += 1

    return list(files.values())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def git_status() -> dict:
    """Return the current git status of the workspace.

    Response fields:
    - ``branch``: current branch name
    - ``staged``: files with staged changes
    - ``modified``: files with unstaged modifications
    - ``untracked``: files not tracked by git
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    # Resolve current branch
    rc, branch_out, _ = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace)
    branch = branch_out.strip() if rc == 0 else "unknown"

    # Porcelain status with NUL terminators for safe parsing
    rc, status_out, stderr = await _run_git(["status", "--porcelain", "-z"], workspace)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git status failed: {stderr.strip()}")

    parsed = _parse_porcelain_status(status_out)
    parsed["branch"] = branch
    return parsed


@router.get("/diff")
async def git_diff(path: str = "") -> dict:
    """Return unstaged diff for the workspace (or a specific file).

    Query param ``path`` restricts the diff to a single file.
    Response fields:
    - ``diff``: raw unified diff text (truncated to 1 MB)
    - ``files``: per-file addition/deletion summary
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    cmd = ["diff"]
    if path:
        safe_path = _sanitize_path(path, workspace)
        cmd += ["--", safe_path]

    rc, diff_out, stderr = await _run_git(cmd, workspace)
    if rc not in (0, 1):  # git diff exits 1 when there are differences
        raise HTTPException(status_code=500, detail=f"git diff failed: {stderr.strip()}")

    # Truncate to 1 MB
    if len(diff_out.encode("utf-8")) > _MAX_DIFF_BYTES:
        diff_out = diff_out.encode("utf-8")[:_MAX_DIFF_BYTES].decode("utf-8", errors="replace")
        diff_out += "\n... (diff truncated at 1 MB)"

    return {
        "diff": diff_out,
        "files": _parse_diff_stat(diff_out),
    }


@router.get("/diff/staged")
async def git_diff_staged(path: str = "") -> dict:
    """Return staged (cached) diff for the workspace (or a specific file).

    Query param ``path`` restricts the diff to a single file.
    Response fields mirror ``GET /diff``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    cmd = ["diff", "--staged"]
    if path:
        safe_path = _sanitize_path(path, workspace)
        cmd += ["--", safe_path]

    rc, diff_out, stderr = await _run_git(cmd, workspace)
    if rc not in (0, 1):
        raise HTTPException(status_code=500, detail=f"git diff --staged failed: {stderr.strip()}")

    if len(diff_out.encode("utf-8")) > _MAX_DIFF_BYTES:
        diff_out = diff_out.encode("utf-8")[:_MAX_DIFF_BYTES].decode("utf-8", errors="replace")
        diff_out += "\n... (diff truncated at 1 MB)"

    return {
        "diff": diff_out,
        "files": _parse_diff_stat(diff_out),
    }


@router.post("/stage")
async def git_stage(request: Request) -> dict:
    """Stage files for the next commit.

    Body:
    - ``files``: list of relative file paths to stage, OR
    - ``all``: ``true`` to stage all changes (equivalent to ``git add -A``)

    Returns ``{ "staged": <list of paths>, "status": "ok" }``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    body = await request.json()
    stage_all = body.get("all", False)
    files: list[str] = body.get("files", [])

    if stage_all:
        cmd = ["add", "-A"]
    elif files:
        safe_files = [_sanitize_path(f, workspace) for f in files]
        cmd = ["add", "--"] + safe_files
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide 'files' list or set 'all' to true.",
        )

    rc, _, stderr = await _run_git(cmd, workspace)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git add failed: {stderr.strip()}")

    return {
        "status": "ok",
        "staged": files if not stage_all else [],
        "all": stage_all,
    }


@router.post("/unstage")
async def git_unstage(request: Request) -> dict:
    """Unstage files (remove from staging area, keep working-tree changes).

    Body:
    - ``files``: list of relative file paths to unstage

    Returns ``{ "unstaged": <list of paths>, "status": "ok" }``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    body = await request.json()
    files: list[str] = body.get("files", [])

    if not files:
        raise HTTPException(status_code=422, detail="Provide a non-empty 'files' list.")

    safe_files = [_sanitize_path(f, workspace) for f in files]
    rc, _, stderr = await _run_git(["restore", "--staged", "--"] + safe_files, workspace)
    if rc != 0:
        detail = f"git restore --staged failed: {stderr.strip()}"
        raise HTTPException(status_code=500, detail=detail)

    return {"status": "ok", "unstaged": files}


@router.post("/commit")
async def git_commit(request: Request) -> dict:
    """Create a commit with the currently staged changes.

    Body:
    - ``message``: commit message (required, non-empty)

    Returns ``{ "hash": str, "message": str, "files_changed": int }``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    body = await request.json()
    message: str = body.get("message", "").strip()

    if not message:
        raise HTTPException(status_code=422, detail="Commit message must not be empty.")

    rc, out, stderr = await _run_git(["commit", "-m", message], workspace)
    if rc != 0:
        err = stderr.strip() or out.strip()
        raise HTTPException(status_code=400, detail=f"git commit failed: {err}")

    # Extract commit hash from output, e.g. "[main abc1234] message"
    commit_hash = ""
    files_changed = 0
    hash_match = re.search(r"\[(?:[^\]]+)\s+([0-9a-f]+)\]", out)
    if hash_match:
        commit_hash = hash_match.group(1)

    # Parse "N files changed" summary line
    files_match = re.search(r"(\d+) file", out)
    if files_match:
        files_changed = int(files_match.group(1))

    return {
        "hash": commit_hash,
        "message": message,
        "files_changed": files_changed,
    }


@router.get("/log")
async def git_log(limit: int = 20) -> dict:
    """Return recent commit history.

    Query param ``limit`` controls the number of commits returned (default 20, max 100).

    Response: ``{ "commits": [{ "hash", "message", "author", "date" }] }``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    # Clamp limit to prevent abuse
    limit = max(1, min(limit, 100))

    rc, out, stderr = await _run_git(
        ["log", "--format=%H|%s|%an|%ai", f"-n{limit}"],
        workspace,
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git log failed: {stderr.strip()}")

    commits = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append(
                {
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                }
            )

    return {"commits": commits}


@router.get("/branches")
async def git_branches() -> dict:
    """Return all local and remote branches.

    Response: ``{ "current": str, "branches": [{ "name", "hash", "current" }] }``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    rc, out, stderr = await _run_git(
        ["branch", "-a", "--format=%(refname:short)|%(objectname:short)|%(HEAD)"],
        workspace,
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git branch failed: {stderr.strip()}")

    branches = []
    current = ""
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        name, commit_hash, head_marker = parts
        is_current = head_marker == "*"
        if is_current:
            current = name
        branches.append(
            {
                "name": name,
                "hash": commit_hash,
                "current": is_current,
            }
        )

    return {"current": current, "branches": branches}


@router.post("/checkout")
async def git_checkout(request: Request) -> dict:
    """Switch to an existing branch or create a new one.

    Body:
    - ``branch``: branch name to check out (required)
    - ``create``: ``true`` to create the branch if it does not exist

    Returns ``{ "branch": str, "status": "ok" }``.
    """
    workspace = _get_workspace()
    _require_git_repo(workspace)

    body = await request.json()
    branch: str = body.get("branch", "").strip()
    create: bool = body.get("create", False)

    if not branch:
        raise HTTPException(status_code=422, detail="Branch name must not be empty.")

    # Validate branch name: no shell-special chars or traversal sequences
    if re.search(r"[;&|`$<> \t]", branch) or ".." in branch:
        raise HTTPException(status_code=400, detail="Invalid branch name.")

    if create:
        cmd = ["checkout", "-b", branch]
    else:
        cmd = ["checkout", branch]

    rc, out, stderr = await _run_git(cmd, workspace)
    if rc != 0:
        raise HTTPException(
            status_code=400,
            detail=f"git checkout failed: {stderr.strip() or out.strip()}",
        )

    return {"branch": branch, "status": "ok", "created": create}
