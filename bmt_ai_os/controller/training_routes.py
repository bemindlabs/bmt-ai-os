"""Training job management API for BMT AI OS controller.

Endpoints
---------
POST   /api/v1/training/jobs           — start a new training job
GET    /api/v1/training/jobs           — list all jobs (active, completed, failed)
GET    /api/v1/training/jobs/{id}      — get job details + progress
DELETE /api/v1/training/jobs/{id}      — cancel a running job

Job state machine: pending → running → completed / failed / cancelled

Storage uses a SQLite database at the path set by the ``BMT_TRAINING_DB``
environment variable, defaulting to ``/tmp/bmt-training.db``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/training", tags=["training"])

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/tmp/bmt-training.db"
_ENV_DB_PATH = "BMT_TRAINING_DB"

JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def _db_path() -> str:
    return os.environ.get(_ENV_DB_PATH, _DEFAULT_DB_PATH)


@contextmanager
def _conn(db: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    path = db or _db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_db(db: str | None = None) -> None:
    """Create training jobs table if it does not exist."""
    with _conn(db) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS training_jobs (
                id              TEXT    PRIMARY KEY,
                model           TEXT    NOT NULL,
                dataset         TEXT    NOT NULL,
                config          TEXT    NOT NULL DEFAULT '{}',
                status          TEXT    NOT NULL DEFAULT 'pending',
                progress        REAL    NOT NULL DEFAULT 0.0,
                current_loss    REAL,
                tokens_per_sec  REAL,
                error_message   TEXT,
                created_at      TEXT    NOT NULL,
                started_at      TEXT,
                completed_at    TEXT,
                updated_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_training_jobs_status
                ON training_jobs(status);

            CREATE INDEX IF NOT EXISTS idx_training_jobs_created
                ON training_jobs(created_at DESC);
            """
        )


# Eagerly initialise the database when the module is imported.
try:
    _init_db()
except Exception as _exc:  # pragma: no cover
    logger.warning("Could not initialise training DB at startup: %s", _exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_job_id() -> str:
    """Generate a unique training job ID."""
    return f"job_{uuid.uuid4().hex[:12]}"


def _row_to_job(row: sqlite3.Row) -> dict:
    import json

    config_raw = row["config"]
    try:
        config = json.loads(config_raw) if config_raw else {}
    except (ValueError, TypeError):
        config = {}

    return {
        "id": row["id"],
        "model": row["model"],
        "dataset": row["dataset"],
        "config": config,
        "status": row["status"],
        "progress": float(row["progress"] or 0.0),
        "current_loss": float(row["current_loss"]) if row["current_loss"] is not None else None,
        "tokens_per_sec": (
            float(row["tokens_per_sec"]) if row["tokens_per_sec"] is not None else None
        ),
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TrainingConfig(BaseModel):
    """Optional hyper-parameters for a training job."""

    learning_rate: float = Field(default=2e-4, gt=0)
    num_epochs: int = Field(default=3, ge=1, le=100)
    batch_size: int = Field(default=4, ge=1, le=512)
    lora_rank: int = Field(default=16, ge=1, le=256)
    lora_alpha: int = Field(default=32, ge=1, le=512)
    max_seq_length: int = Field(default=2048, ge=64, le=32768)
    quantization: str = Field(default="q4_K_M")


class TrainingJobCreate(BaseModel):
    model: str = Field(..., min_length=1, description="Base model name (e.g. qwen2.5:0.5b)")
    dataset: str = Field(..., min_length=1, description="Dataset path or HuggingFace dataset ID")
    config: TrainingConfig = Field(default_factory=TrainingConfig)


class TrainingJobSummary(BaseModel):
    id: str
    model: str
    dataset: str
    status: str
    progress: float
    created_at: str
    updated_at: str


class TrainingJobDetail(TrainingJobSummary):
    config: dict
    current_loss: float | None
    tokens_per_sec: float | None
    error_message: str | None
    started_at: str | None
    completed_at: str | None


class TrainingJobListResponse(BaseModel):
    jobs: list[TrainingJobSummary]
    total: int
    page: int
    page_size: int


class TrainingJobUpdateProgress(BaseModel):
    """Internal model for updating job progress (used by training workers)."""

    progress: float = Field(..., ge=0.0, le=100.0)
    current_loss: float | None = None
    tokens_per_sec: float | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Internal job manager — used by Prometheus and training workers
# ---------------------------------------------------------------------------


class TrainingJobManager:
    """Thin wrapper over the SQLite store providing typed access to job state."""

    def __init__(self, db: str | None = None) -> None:
        self._db = db

    # --- Read ---

    def get_job(self, job_id: str) -> dict | None:
        with _conn(self._db) as con:
            row = con.execute("SELECT * FROM training_jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        with _conn(self._db) as con:
            if status:
                total: int = con.execute(
                    "SELECT COUNT(*) FROM training_jobs WHERE status = ?", (status,)
                ).fetchone()[0]
                rows = con.execute(
                    "SELECT * FROM training_jobs WHERE status = ? ORDER BY created_at DESC"
                    " LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                total = con.execute("SELECT COUNT(*) FROM training_jobs").fetchone()[0]
                rows = con.execute(
                    "SELECT * FROM training_jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [_row_to_job(r) for r in rows], total

    def count_by_status(self) -> dict[str, int]:
        with _conn(self._db) as con:
            rows = con.execute(
                "SELECT status, COUNT(*) as cnt FROM training_jobs GROUP BY status"
            ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def get_latest_metrics(self) -> dict:
        """Return the most recent loss and throughput across running jobs."""
        with _conn(self._db) as con:
            row = con.execute(
                "SELECT current_loss, tokens_per_sec FROM training_jobs"
                " WHERE status = 'running' ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return {
                "current_loss": float(row["current_loss"]) if row["current_loss"] else None,
                "tokens_per_sec": float(row["tokens_per_sec"]) if row["tokens_per_sec"] else None,
            }
        return {"current_loss": None, "tokens_per_sec": None}

    def get_completed_durations(self) -> list[float]:
        """Return duration in seconds for all completed/failed/cancelled jobs."""
        with _conn(self._db) as con:
            rows = con.execute(
                "SELECT started_at, completed_at FROM training_jobs"
                " WHERE started_at IS NOT NULL AND completed_at IS NOT NULL"
            ).fetchall()
        durations = []
        for r in rows:
            try:
                start = datetime.fromisoformat(r["started_at"])
                end = datetime.fromisoformat(r["completed_at"])
                durations.append((end - start).total_seconds())
            except (ValueError, TypeError):
                pass
        return durations

    # --- Write ---

    def create_job(self, model: str, dataset: str, config: dict) -> dict:
        import json

        job_id = _generate_job_id()
        now = _now_iso()
        with _conn(self._db) as con:
            con.execute(
                "INSERT INTO training_jobs"
                " (id, model, dataset, config, status, progress, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (job_id, model, dataset, json.dumps(config), "pending", 0.0, now, now),
            )
        logger.info("Created training job %s (model=%s, dataset=%s)", job_id, model, dataset)
        return self.get_job(job_id)  # type: ignore[return-value]

    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> dict | None:
        job = self.get_job(job_id)
        if job is None:
            return None
        if status not in _VALID_TRANSITIONS.get(job["status"], set()):
            raise ValueError(f"Cannot transition job from '{job['status']}' to '{status}'.")
        now = _now_iso()
        started_at = job["started_at"]
        completed_at = job["completed_at"]
        if status == "running" and started_at is None:
            started_at = now
        if status in ("completed", "failed", "cancelled") and completed_at is None:
            completed_at = now

        with _conn(self._db) as con:
            con.execute(
                "UPDATE training_jobs SET status=?, started_at=?, completed_at=?,"
                " error_message=?, updated_at=? WHERE id=?",
                (status, started_at, completed_at, error_message, now, job_id),
            )
        return self.get_job(job_id)

    def update_progress(
        self,
        job_id: str,
        progress: float,
        *,
        current_loss: float | None = None,
        tokens_per_sec: float | None = None,
    ) -> dict | None:
        now = _now_iso()
        with _conn(self._db) as con:
            con.execute(
                "UPDATE training_jobs SET progress=?, current_loss=?, tokens_per_sec=?,"
                " updated_at=? WHERE id=?",
                (progress, current_loss, tokens_per_sec, now, job_id),
            )
        return self.get_job(job_id)


# Module-level singleton
_default_manager: TrainingJobManager | None = None


def get_job_manager(db: str | None = None) -> TrainingJobManager:
    """Return the module-level TrainingJobManager singleton."""
    global _default_manager
    if _default_manager is None:
        _default_manager = TrainingJobManager(db)
    return _default_manager


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/jobs",
    response_model=TrainingJobDetail,
    status_code=201,
    summary="Start a training job",
)
async def create_training_job(body: TrainingJobCreate) -> TrainingJobDetail:
    """Start a new fine-tuning job with the given model, dataset, and config."""
    mgr = get_job_manager()
    job = mgr.create_job(
        model=body.model,
        dataset=body.dataset,
        config=body.config.model_dump(),
    )
    return TrainingJobDetail(**job)


@router.get(
    "/jobs",
    response_model=TrainingJobListResponse,
    summary="List training jobs",
)
async def list_training_jobs(
    status: str | None = Query(default=None, description="Filter by status"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
) -> TrainingJobListResponse:
    """Return a paginated list of training jobs ordered by most recently created."""
    if status is not None and status not in _VALID_TRANSITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter '{status}'. Must be one of: {list(_VALID_TRANSITIONS)}",
        )
    offset = (page - 1) * page_size
    mgr = get_job_manager()
    jobs_raw, total = mgr.list_jobs(status=status, limit=page_size, offset=offset)
    summaries = [
        TrainingJobSummary(
            id=j["id"],
            model=j["model"],
            dataset=j["dataset"],
            status=j["status"],
            progress=j["progress"],
            created_at=j["created_at"],
            updated_at=j["updated_at"],
        )
        for j in jobs_raw
    ]
    return TrainingJobListResponse(
        jobs=summaries,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=TrainingJobDetail,
    summary="Get training job details",
)
async def get_training_job(job_id: str) -> TrainingJobDetail:
    """Return full details and progress for a specific training job."""
    mgr = get_job_manager()
    job = mgr.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found.")
    return TrainingJobDetail(**job)


@router.delete(
    "/jobs/{job_id}",
    status_code=204,
    summary="Cancel a training job",
)
async def cancel_training_job(job_id: str) -> None:
    """Cancel a pending or running training job."""
    mgr = get_job_manager()
    job = mgr.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found.")
    if job["status"] not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot cancel job '{job_id}' in status '{job['status']}'."
                " Only pending or running jobs can be cancelled."
            ),
        )
    mgr.update_status(job_id, "cancelled")
    logger.info("Cancelled training job %s", job_id)
