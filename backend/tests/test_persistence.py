"""Vérifie les vrais fichiers SQLite, les instantanés et la reprise après redémarrage."""

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from planning.api import jobs as jobs_module
from planning.api.jobs import JobManager, job_view
from planning.api.schemas import EXAMPLE_TOURNAMENT, JobStatus
from planning.domain import Tournament
from planning.main import create_app
from planning.persistence import Store
from planning.planner import PlanningReport, plan


def wait_for_result(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result: dict[str, Any] = client.get(f"/api/schedules/{job_id}").json()
        if JobStatus(result["status"]).finished:
            return result
        time.sleep(0.01)
    raise AssertionError("La génération n'a pas terminé.")


def test_tournament_crud_and_missing_resources(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "planning.db")) as client:
        assert client.get("/api/tournaments").json() == []
        created = client.post("/api/tournaments", json=EXAMPLE_TOURNAMENT)
        assert created.status_code == 201
        saved = created.json()
        tournament_id = saved["id"]
        path = f"/api/tournaments/{tournament_id}"
        assert saved["schedules_count"] == 0
        assert client.get(path).json() == saved
        updated = client.put(path, json={**EXAMPLE_TOURNAMENT, "name": "Coupe d'hiver"})
        assert updated.status_code == 200
        assert updated.json()["tournament"]["name"] == "Coupe d'hiver"
        assert updated.json()["created_at"] == saved["created_at"]
        assert client.post("/api/tournaments", json={"name": "incomplet"}).status_code == 422
        assert client.get(f"{path}/schedules").json() == []
        assert client.delete(path).status_code == 204
        assert client.get("/api/tournaments").json() == []
        assert client.get(path).status_code == 404
        assert client.get(f"{path}/schedules").status_code == 404
        assert client.put(path, json=EXAMPLE_TOURNAMENT).status_code == 404
        assert client.delete(path).status_code == 404
        assert (
            client.post(
                "/api/schedules",
                json={
                    "tournament": EXAMPLE_TOURNAMENT,
                    "tournament_id": tournament_id,
                },
            ).status_code
            == 404
        )


def test_history_survives_restart_and_keeps_each_tournament_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "planning.db"
    with TestClient(create_app(database_path=database)) as client:
        first = client.post(
            "/api/schedules",
            json={
                "tournament": EXAMPLE_TOURNAMENT,
                "timeout_seconds": 3,
            },
        ).json()
        tournament_id = first["tournament_id"]
        old_result = wait_for_result(client, first["job_id"])
        assert old_result["status"] == "solved"
        changed = {
            **EXAMPLE_TOURNAMENT,
            "name": "Tournoi modifié",
            "fields": [
                {"id": "NOUVEAU", "name": "Nouveau terrain"},
            ],
        }
        second = client.post(
            "/api/schedules",
            json={
                "tournament": changed,
                "tournament_id": tournament_id,
                "timeout_seconds": 4,
            },
        ).json()
        wait_for_result(client, second["job_id"])

    with TestClient(create_app(database_path=database)) as client:
        [saved] = client.get("/api/tournaments").json()
        assert saved["id"] == tournament_id
        assert saved["tournament"]["name"] == "Tournoi modifié"
        assert saved["schedules_count"] == 2
        history = client.get(f"/api/tournaments/{tournament_id}/schedules").json()
        assert [item["job_id"] for item in history] == [second["job_id"], first["job_id"]]
        assert history[0]["tournament"]["fields"][0]["id"] == "NOUVEAU"
        assert history[1]["tournament"]["fields"][0]["id"] == "T1"
        assert history[1]["stats"] == old_result["stats"]
        assert history[1]["schedule"] == old_result["schedule"]
        assert history[1]["solver_parameters"] == {
            "algorithm": "backtracking",
            "timeout_seconds": 3,
        }
        assert history[1]["score"] is None  # le score souple arrive dans l'issue #12
        assert client.get(f"/api/schedules/{first['job_id']}").json() == old_result
        assert client.delete(f"/api/schedules/{first['job_id']}").json() == old_result
        assert client.delete(f"/api/tournaments/{tournament_id}").status_code == 204
        assert client.get(f"/api/schedules/{first['job_id']}").status_code == 404
        assert client.get(f"/api/schedules/{second['job_id']}").status_code == 404


def test_tournament_histories_are_separate(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "planning.db")) as client:
        first = client.post("/api/schedules", json={"tournament": EXAMPLE_TOURNAMENT}).json()
        second = client.post("/api/schedules", json={"tournament": EXAMPLE_TOURNAMENT}).json()
        wait_for_result(client, first["job_id"])
        wait_for_result(client, second["job_id"])
        assert first["tournament_id"] != second["tournament_id"]
        for created in (first, second):
            history = client.get(f"/api/tournaments/{created['tournament_id']}/schedules").json()
            assert [item["job_id"] for item in history] == [created["job_id"]]


def test_active_tournament_cannot_be_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def blocking_plan(tournament: Tournament, **kwargs: Any) -> PlanningReport:
        release.wait(5)
        return plan(tournament, **kwargs)

    monkeypatch.setattr(jobs_module, "plan", blocking_plan)
    with TestClient(create_app(database_path=tmp_path / "planning.db")) as client:
        created = client.post("/api/schedules", json={"tournament": EXAMPLE_TOURNAMENT}).json()
        path = f"/api/tournaments/{created['tournament_id']}"
        try:
            assert client.delete(path).status_code == 409
            assert client.get(path).status_code == 200
        finally:
            release.set()
        wait_for_result(client, created["job_id"])
        assert client.delete(path).status_code == 204


def test_evicted_jobs_remain_available_in_sqlite(tmp_path: Path) -> None:
    store = Store(tmp_path / "planning.db")
    manager = JobManager(store, max_workers=1, max_jobs=1)
    tournament = Tournament.model_validate(EXAMPLE_TOURNAMENT)
    try:
        first = manager.submit(tournament, 3)
        assert first.future is not None
        first.future.result(timeout=5)
        second = manager.submit(tournament, 3, first.tournament_id)
        assert second.future is not None
        second.future.result(timeout=5)
        assert manager.get(first.id) is None
        persisted = manager.view(first.id)
        assert persisted is not None and persisted.status is JobStatus.SOLVED
    finally:
        manager.shutdown()
        store.close()


def test_interrupted_jobs_are_recovered_after_crash(tmp_path: Path) -> None:
    database = tmp_path / "planning.db"
    store = Store(database)
    tournament = Tournament.model_validate(EXAMPLE_TOURNAMENT)
    saved = store.save_tournament(tournament)
    # Représente le dernier état écrit avant l'arrêt brutal du processus.
    job = jobs_module.Job(
        id="interrupted",
        tournament=tournament,
        tournament_id=saved.id,
        timeout_seconds=3,
        status=JobStatus.RUNNING,
    )
    store.add_schedule(job_view(job), tournament)
    store.close()
    recovered = Store(database)
    try:
        result = recovered.get_schedule(job.id)
        assert result is not None
        assert result.status is JobStatus.CANCELLED
        assert result.finished_at is not None
        assert result.error is not None and "redémarrage" in result.error
        assert recovered.delete_tournament(saved.id)
    finally:
        recovered.close()
