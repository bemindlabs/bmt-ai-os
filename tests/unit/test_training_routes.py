"""Unit tests for bmt_ai_os.controller.training_routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the training store at a fresh temp DB for each test."""
    db = str(tmp_path / "test-training.db")
    monkeypatch.setenv("BMT_TRAINING_DB", db)

    from bmt_ai_os.controller import training_routes

    # Reset the module-level singleton so each test gets a fresh manager
    training_routes._default_manager = None
    training_routes._init_db(db)
    yield db
    training_routes._default_manager = None


@pytest.fixture()
def client():
    """Return a TestClient for the controller FastAPI app."""
    from bmt_ai_os.controller.api import app

    return TestClient(app)


@pytest.fixture()
def job_payload():
    return {
        "model": "qwen2.5:0.5b",
        "dataset": "alpaca_cleaned",
        "config": {
            "learning_rate": 0.0002,
            "num_epochs": 2,
            "batch_size": 4,
        },
    }


# ---------------------------------------------------------------------------
# POST /api/v1/training/jobs
# ---------------------------------------------------------------------------


class TestCreateTrainingJob:
    def test_create_returns_201(self, client, job_payload):
        resp = client.post("/api/v1/training/jobs", json=job_payload)
        assert resp.status_code == 201

    def test_create_body_fields(self, client, job_payload):
        resp = client.post("/api/v1/training/jobs", json=job_payload)
        body = resp.json()
        assert body["model"] == "qwen2.5:0.5b"
        assert body["dataset"] == "alpaca_cleaned"
        assert body["status"] == "pending"
        assert body["progress"] == 0.0
        assert body["id"].startswith("job_")

    def test_create_uses_default_config(self, client):
        resp = client.post(
            "/api/v1/training/jobs",
            json={"model": "qwen2.5:1.5b", "dataset": "my_dataset"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["config"]["num_epochs"] == 3
        assert body["config"]["lora_rank"] == 16

    def test_create_missing_model_rejected(self, client):
        resp = client.post("/api/v1/training/jobs", json={"dataset": "data"})
        assert resp.status_code == 422

    def test_create_missing_dataset_rejected(self, client):
        resp = client.post("/api/v1/training/jobs", json={"model": "qwen2.5:0.5b"})
        assert resp.status_code == 422

    def test_create_invalid_learning_rate(self, client):
        resp = client.post(
            "/api/v1/training/jobs",
            json={"model": "m", "dataset": "d", "config": {"learning_rate": -1}},
        )
        assert resp.status_code == 422

    def test_create_invalid_epoch_zero(self, client):
        resp = client.post(
            "/api/v1/training/jobs",
            json={"model": "m", "dataset": "d", "config": {"num_epochs": 0}},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/training/jobs
# ---------------------------------------------------------------------------


class TestListTrainingJobs:
    def test_empty_list(self, client):
        resp = client.get("/api/v1/training/jobs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["jobs"] == []
        assert body["total"] == 0

    def test_lists_created_jobs(self, client, job_payload):
        client.post("/api/v1/training/jobs", json=job_payload)
        client.post("/api/v1/training/jobs", json=job_payload)
        resp = client.get("/api/v1/training/jobs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
        assert len(resp.json()["jobs"]) == 2

    def test_filter_by_status(self, client, job_payload):
        client.post("/api/v1/training/jobs", json=job_payload)
        resp = client.get("/api/v1/training/jobs?status=pending")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_filter_by_invalid_status(self, client):
        resp = client.get("/api/v1/training/jobs?status=bogus")
        assert resp.status_code == 422

    def test_pagination(self, client, job_payload):
        for _ in range(5):
            client.post("/api/v1/training/jobs", json=job_payload)
        resp = client.get("/api/v1/training/jobs?page=1&page_size=2")
        body = resp.json()
        assert body["total"] == 5
        assert len(body["jobs"]) == 2
        assert body["page"] == 1
        assert body["page_size"] == 2

    def test_pagination_second_page(self, client, job_payload):
        for _ in range(5):
            client.post("/api/v1/training/jobs", json=job_payload)
        resp = client.get("/api/v1/training/jobs?page=2&page_size=3")
        body = resp.json()
        assert len(body["jobs"]) == 2  # 5 - 3 = 2 remaining


# ---------------------------------------------------------------------------
# GET /api/v1/training/jobs/{id}
# ---------------------------------------------------------------------------


class TestGetTrainingJob:
    def test_get_existing_job(self, client, job_payload):
        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/training/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == job_id
        assert body["model"] == job_payload["model"]
        assert body["dataset"] == job_payload["dataset"]

    def test_get_nonexistent_job(self, client):
        resp = client.get("/api/v1/training/jobs/job_doesnotexist")
        assert resp.status_code == 404

    def test_detail_includes_config(self, client, job_payload):
        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/training/jobs/{job_id}")
        assert "config" in resp.json()
        assert isinstance(resp.json()["config"], dict)

    def test_detail_includes_timestamps(self, client, job_payload):
        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/training/jobs/{job_id}")
        body = resp.json()
        assert "created_at" in body
        assert "updated_at" in body
        assert body["started_at"] is None
        assert body["completed_at"] is None


# ---------------------------------------------------------------------------
# DELETE /api/v1/training/jobs/{id}
# ---------------------------------------------------------------------------


class TestCancelTrainingJob:
    def test_cancel_pending_job(self, client, job_payload):
        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        resp = client.delete(f"/api/v1/training/jobs/{job_id}")
        assert resp.status_code == 204

    def test_cancel_updates_status(self, client, job_payload):
        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        client.delete(f"/api/v1/training/jobs/{job_id}")
        detail = client.get(f"/api/v1/training/jobs/{job_id}").json()
        assert detail["status"] == "cancelled"

    def test_cancel_nonexistent_job(self, client):
        resp = client.delete("/api/v1/training/jobs/job_ghost")
        assert resp.status_code == 404

    def test_cancel_already_completed_job(self, client, job_payload):
        """Cannot cancel a completed job."""
        from bmt_ai_os.controller.training_routes import get_job_manager

        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        mgr = get_job_manager()
        mgr.update_status(job_id, "running")
        mgr.update_status(job_id, "completed")
        resp = client.delete(f"/api/v1/training/jobs/{job_id}")
        assert resp.status_code == 409

    def test_cancel_already_cancelled_job(self, client, job_payload):
        create_resp = client.post("/api/v1/training/jobs", json=job_payload)
        job_id = create_resp.json()["id"]
        client.delete(f"/api/v1/training/jobs/{job_id}")
        # Second cancel should 409
        resp = client.delete(f"/api/v1/training/jobs/{job_id}")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# TrainingJobManager unit tests
# ---------------------------------------------------------------------------


class TestTrainingJobManager:
    def test_create_and_get(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager

        db = str(tmp_path / "mgr.db")
        from bmt_ai_os.controller.training_routes import _init_db

        _init_db(db)
        mgr = TrainingJobManager(db)
        job = mgr.create_job("model", "dataset", {"lr": 0.001})
        assert job["status"] == "pending"
        fetched = mgr.get_job(job["id"])
        assert fetched is not None
        assert fetched["id"] == job["id"]

    def test_update_status_transition(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        job = mgr.create_job("m", "d", {})
        updated = mgr.update_status(job["id"], "running")
        assert updated["status"] == "running"
        assert updated["started_at"] is not None

    def test_invalid_transition_raises(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        job = mgr.create_job("m", "d", {})
        with pytest.raises(ValueError, match="Cannot transition"):
            mgr.update_status(job["id"], "completed")  # must go pending→running first

    def test_count_by_status(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        mgr.create_job("m", "d", {})
        mgr.create_job("m2", "d2", {})
        counts = mgr.count_by_status()
        assert counts.get("pending", 0) == 2

    def test_update_progress(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        job = mgr.create_job("m", "d", {})
        mgr.update_status(job["id"], "running")
        updated = mgr.update_progress(job["id"], 45.0, current_loss=1.2, tokens_per_sec=150.0)
        assert updated["progress"] == 45.0
        assert updated["current_loss"] == 1.2
        assert updated["tokens_per_sec"] == 150.0

    def test_get_nonexistent_returns_none(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        assert mgr.get_job("no_such_job") is None

    def test_get_latest_metrics_no_jobs(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        metrics = mgr.get_latest_metrics()
        assert metrics["current_loss"] is None
        assert metrics["tokens_per_sec"] is None

    def test_completed_durations(self, tmp_path):
        from bmt_ai_os.controller.training_routes import TrainingJobManager, _init_db

        db = str(tmp_path / "mgr.db")
        _init_db(db)
        mgr = TrainingJobManager(db)
        job = mgr.create_job("m", "d", {})
        mgr.update_status(job["id"], "running")
        mgr.update_status(job["id"], "completed")
        durations = mgr.get_completed_durations()
        # At minimum one entry (may be 0 seconds if very fast)
        assert len(durations) >= 1
