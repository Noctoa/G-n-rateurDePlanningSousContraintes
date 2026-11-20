"""Régression du tournoi à 56 matchs / 60 places et contrôle indépendant des coupes."""

import random
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planning.checker import validate
from planning.domain import Tournament, generate_matches, load_tournament
from planning.main import create_app
from planning.planner import plan
from planning.solver import SolveStatus, build_problem, solve, to_schedule
from planning.solver.guided import solve_guided

DATASETS = Path(__file__).resolve().parents[2] / "datasets"


def tight_tournament(
    hours: tuple[str, ...] = ("09:00", "10:00", "11:00", "13:00", "14:00"),
) -> Tournament:
    data = load_tournament(DATASETS / "medium.json").model_dump(mode="json", by_alias=True)
    # Même édition que dans l'UI : garder 09:00, 10:00, 11:00, 13:00 et 14:00 sur 3 jours.
    previous = {slot["id"]: slot for slot in data["slots"]}
    days = sorted({slot["day"] for slot in data["slots"]})
    data["slots"] = [
        previous.get(
            f"J{day_index}-{hour[:2]}h",
            {
                "id": f"J{day_index}-{hour[:2]}h",
                "day": day,
                "start": hour,
                "duration_minutes": 60,
            },
        )
        for day_index, day in enumerate(days, 1)
        for hour in hours
    ]
    ids = {slot["id"] for slot in data["slots"]}
    for team in data["teams"]:
        for key in ("unavailable_slots", "preferred_slots"):
            team[key] = [slot for slot in team[key] if slot in ids]
    return Tournament.model_validate(data)


@pytest.mark.parametrize(
    "hours",
    [
        ("09:00", "10:00", "11:00", "13:00", "14:00"),
        ("08:00", "09:00", "10:00", "11:00", "13:00"),
    ],
)
def test_tight_tournament_is_solved_without_relaxing_any_constraint(hours: tuple[str, ...]) -> None:
    tournament = tight_tournament(hours)
    assert len(tournament.slots) * len(tournament.fields) == 60
    report = plan(tournament, timeout_seconds=2)
    assert len(report.matches) == 56
    assert report.result is not None
    assert report.result.status is SolveStatus.SOLVED
    assert report.result.assignment is not None
    assert validate(tournament, to_schedule(report.result.assignment), report.matches) == []


@pytest.mark.parametrize(
    "hours",
    [
        ("09:00", "10:00", "11:00", "13:00", "14:00"),
        ("08:00", "09:00", "10:00", "11:00", "13:00"),
    ],
)
def test_api_solves_the_edited_medium_tournament(hours: tuple[str, ...]) -> None:
    tournament = tight_tournament(hours)
    with TestClient(create_app(database_path=":memory:")) as client:
        data = tournament.model_dump(mode="json", by_alias=True)
        # La validation de la saisie n'est pas une résolution : les deux routes sont vérifiées.
        assert client.post("/api/tournaments/validate", json=data).json()["valid"] is True
        created = client.post("/api/schedules", json={"tournament": data, "timeout_seconds": 2})
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = client.get(f"/api/schedules/{job_id}").json()
            if result["status"] not in {"pending", "running"}:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("Le tournoi modifié n'a pas été résolu à temps.")
        assert result["status"] == "solved"
        assert len(result["schedule"]["assignments"]) == 56
        assert result["violations"] == []


def test_guided_search_agrees_with_exhaustive_search_on_small_tournaments() -> None:
    rng = random.Random(52)
    for _ in range(80):
        slots = [
            {
                "id": f"D{day}S{i}",
                "day": f"2026-12-0{day}",
                "start": f"{9 + i:02d}:00",
                "duration_minutes": rng.choice([30, 45, 60]),
                "min_matches": rng.choice([0, 0, 1]),
                "max_matches": rng.choice([None, None, 1]),
            }
            for day in range(1, rng.randint(1, 2) + 1)
            for i in range(rng.randint(2, 4))
        ]
        ids = [slot["id"] for slot in slots]
        teams = [
            {"id": team, "name": team, "unavailable_slots": rng.sample(ids, rng.randint(0, 1))}
            for team in "ABCD"[: rng.randint(2, 4)]
        ]
        tournament = Tournament.model_validate(
            {
                "name": "contrôle",
                "teams": teams,
                "fields": [
                    {
                        "id": f"F{i}",
                        "name": f"F{i}",
                        "unavailable_slots": rng.sample(ids, rng.randint(0, 1)),
                    }
                    for i in range(rng.randint(1, 2))
                ],
                "slots": slots,
                "rules": {
                    "min_rest_minutes": rng.choice([0, 20, 60]),
                    "max_matches_per_team_per_day": rng.choice([None, 1, 2]),
                },
                "incompatibilities": [{"teams": ["A", "B"]}] if rng.random() < 0.3 else [],
            }
        )
        matches = generate_matches(tournament)
        reference = solve(build_problem(tournament, matches), timeout_seconds=0.5)
        guided = solve_guided(tournament, matches, timeout_seconds=1)
        if reference.status is not SolveStatus.TIMEOUT:
            assert guided.status is reference.status
        if guided.status is SolveStatus.SOLVED:
            assert guided.assignment is not None
            assert validate(tournament, to_schedule(guided.assignment), matches) == []


def test_guided_search_honours_cancellation_and_timeout() -> None:
    tournament = tight_tournament()
    matches = generate_matches(tournament)
    assert solve_guided(tournament, matches, timeout_seconds=0).status is SolveStatus.TIMEOUT
    assert (
        solve_guided(tournament, matches, should_stop=lambda: True).status is SolveStatus.CANCELLED
    )
    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 5

    result = solve_guided(tournament, matches, should_stop=cancel)
    assert result.status is SolveStatus.CANCELLED
    assert result.assignment is None
