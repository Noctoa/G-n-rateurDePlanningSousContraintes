import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from planning.api import jobs as jobs_module
from planning.api.schemas import EXAMPLE_TOURNAMENT
from planning.diagnosis import Diagnosis, Feasibility
from planning.domain import Tournament, generate_matches
from planning.main import create_app
from planning.planner import PlanningReport
from planning.solver import SolveResult, SolveStatus

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
FINAL = {"solved", "infeasible", "timeout", "cancelled", "error"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(max_workers=1, database_path=":memory:")) as c:
        yield c


def _dataset(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATASETS / f"{name}.json").read_text(encoding="utf-8"))
    return data


def _wait(client: TestClient, job_id: str, timeout: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, Any] = client.get(f"/api/schedules/{job_id}").json()
        if body["status"] in FINAL:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} toujours en cours après {timeout} s")


# --- Validation --------------------------------------------------------------------------


def test_validate_accepts_a_valid_tournament(client: TestClient) -> None:
    r = client.post("/api/tournaments/validate", json=_dataset("small"))
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["errors"] == []
    assert body["summary"] == {"teams": 6, "fields": 2, "slots": 12, "matches": 15, "places": 24}
    assert body["warnings"] == []


def test_validate_reports_field_errors_without_failing(client: TestClient) -> None:
    data = _dataset("small")
    data["fields"][0]["name"] = ""
    del data["slots"][0]["day"]
    r = client.post("/api/tournaments/validate", json=data)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    errors = {e["location"]: e["message"] for e in body["errors"]}
    assert errors == {
        "fields.0.name": "ne doit pas être vide",
        "slots.0.day": "champ obligatoire manquant",
    }


def test_validate_messages_include_limits(client: TestClient) -> None:
    body = client.post(
        "/api/tournaments/validate", json={"name": "x", "teams": [], "fields": [], "slots": []}
    ).json()
    errors = {e["location"]: e["message"] for e in body["errors"]}
    assert errors["teams"] == "au moins 2 élément(s) attendu(s)"
    assert errors["fields"] == "au moins 1 élément(s) attendu(s)"


def test_validate_reports_each_consistency_error(client: TestClient) -> None:
    # Ces erreurs ne sont visibles qu'une fois les champs individuellement valides.
    data = _dataset("small")
    data["teams"][1]["id"] = data["teams"][0]["id"]
    data["teams"][2]["unavailable_slots"] = ["NOPE"]
    body = client.post("/api/tournaments/validate", json=data).json()
    assert body["valid"] is False
    messages = [e["message"] for e in body["errors"]]
    assert len(messages) == 3
    assert any("en double : LIO" in m for m in messages)
    assert any("créneaux inconnus : NOPE" in m for m in messages)
    assert any("équipe inconnue 'AIG'" in m for m in messages)  # l'incompatibilité LIO/AIG


def test_validate_warns_when_tournament_is_provably_unsolvable(client: TestClient) -> None:
    body = client.post("/api/tournaments/validate", json=_dataset("unsolvable")).json()
    assert body["valid"] is True
    [warning] = body["warnings"]
    assert warning["constraints"][0]["id"] == "H1"
    assert "il manque 3 places" in warning["explanation"]


# --- Jobs de résolution ------------------------------------------------------------------


def test_solved_job_returns_schedule_stats_and_clean_check(client: TestClient) -> None:
    r = client.post("/api/schedules", json={"tournament": _dataset("small"), "timeout_seconds": 5})
    assert r.status_code == 202
    created = r.json()
    assert created["status"] in {"pending", "running", "solved"}

    body = _wait(client, created["job_id"])
    assert body["status"] == "solved"
    assert len(body["schedule"]["assignments"]) == len(body["matches"]) == 15
    assert body["stats"]["nodes"] >= 15
    assert body["violations"] == []
    assert body["diagnosis"]["feasibility"] == "feasible"
    assert body["started_at"] is not None
    assert body["finished_at"] is not None


def test_infeasible_job_returns_diagnosis(client: TestClient) -> None:
    job_id = client.post("/api/schedules", json={"tournament": _dataset("unsolvable")}).json()[
        "job_id"
    ]
    body = _wait(client, job_id)
    assert body["status"] == "infeasible"
    assert body["schedule"] is None
    assert body["stats"] is None  # conclu par pré-vérification, sans recherche
    assert body["diagnosis"]["conflicts"][0]["constraints"][0]["id"] == "H1"


def test_example_from_openapi_is_solvable(client: TestClient) -> None:
    job_id = client.post("/api/schedules", json={"tournament": EXAMPLE_TOURNAMENT}).json()["job_id"]
    assert _wait(client, job_id)["status"] == "solved"


def test_invalid_request_is_rejected_with_422(client: TestClient) -> None:
    r = client.post(
        "/api/schedules", json={"tournament": _dataset("small"), "timeout_seconds": 3600}
    )
    assert r.status_code == 422  # au-delà du plafond serveur
    r = client.post("/api/schedules", json={"tournament": {"name": "vide"}})
    assert r.status_code == 422


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/schedules/nope").status_code == 404
    assert client.delete("/api/schedules/nope").status_code == 404


# --- Annulation et statuts non bloquants -------------------------------------------------


def _fake_report(tournament: Tournament, status: SolveStatus) -> PlanningReport:
    feasibility = Feasibility.UNKNOWN
    return PlanningReport(
        matches=generate_matches(tournament),
        result=SolveResult(status=status, assignment=None),
        diagnosis=Diagnosis(feasibility=feasibility, summary="factice"),
    )


def test_running_job_can_be_cancelled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()

    def endless_plan(tournament: Tournament, **kwargs: Any) -> PlanningReport:
        started.set()
        should_stop = kwargs["should_stop"]
        while not should_stop():  # simule une recherche très longue mais annulable
            time.sleep(0.005)
        return _fake_report(tournament, SolveStatus.CANCELLED)

    monkeypatch.setattr(jobs_module, "plan", endless_plan)
    job_id = client.post("/api/schedules", json={"tournament": _dataset("small")}).json()["job_id"]
    assert started.wait(5)
    assert client.get(f"/api/schedules/{job_id}").json()["status"] == "running"  # pas bloqué

    assert client.delete(f"/api/schedules/{job_id}").status_code == 200
    assert _wait(client, job_id)["status"] == "cancelled"


def test_pending_job_is_cancelled_immediately(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def blocking_plan(tournament: Tournament, **kwargs: Any) -> PlanningReport:
        release.wait(5)
        return _fake_report(tournament, SolveStatus.TIMEOUT)

    monkeypatch.setattr(jobs_module, "plan", blocking_plan)
    first = client.post("/api/schedules", json={"tournament": _dataset("small")}).json()
    second = client.post("/api/schedules", json={"tournament": _dataset("small")}).json()
    # Un seul worker : le second attend dans la file.
    assert client.get(f"/api/schedules/{second['job_id']}").json()["status"] == "pending"
    assert client.delete(f"/api/schedules/{second['job_id']}").json()["status"] == "cancelled"

    release.set()
    assert _wait(client, first["job_id"])["status"] == "timeout"
    assert _wait(client, second["job_id"])["status"] == "cancelled"


# --- OpenAPI -----------------------------------------------------------------------------


def test_openapi_documents_the_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert set(paths) >= {
        "/api/tournaments/validate",
        "/api/schedules",
        "/api/schedules/{job_id}",
    }
    assert {"get", "delete"} <= set(paths["/api/schedules/{job_id}"])
    assert "404" in paths["/api/schedules/{job_id}"]["get"]["responses"]
    statuses = spec["components"]["schemas"]["JobStatus"]["enum"]
    assert set(statuses) == {"pending", "running", *FINAL}
