import random
from pathlib import Path
from typing import Any

import pytest

from planning.constraints.catalog import HardConstraintId as H
from planning.diagnosis import Feasibility, find_conflict, precheck
from planning.domain import Tournament, generate_matches, load_tournament
from planning.planner import plan
from planning.solver import Problem, SolveStatus, build_problem, solve

DATASETS = Path(__file__).resolve().parents[2] / "datasets"


def _tournament(
    teams: str | list[dict[str, Any]] = "ABCD",
    fields: int | list[dict[str, Any]] = 2,
    slots: int = 4,
    days: int = 1,
    **extra: Any,
) -> Tournament:
    """`teams` : lettres des équipes ou liste complète ; `fields` : nombre ou liste complète."""
    return Tournament.model_validate(
        {
            "name": "test",
            "teams": (
                [{"id": t, "name": f"Équipe {t}"} for t in teams]
                if isinstance(teams, str)
                else teams
            ),
            "fields": (
                [{"id": f"F{i}", "name": f"Terrain {i}"} for i in range(1, fields + 1)]
                if isinstance(fields, int)
                else fields
            ),
            "slots": [
                {
                    "id": f"D{d}S{i}",
                    "day": f"2026-12-0{d}",
                    "start": f"{9 + i:02d}:00",
                    "duration_minutes": 60,
                }
                for d in range(1, days + 1)
                for i in range(slots)
            ],
            **extra,
        }
    )


def _ids(conflicts: list[Any]) -> set[H]:
    return {ref.id for c in conflicts for ref in c.constraints}


# --- Bout en bout ------------------------------------------------------------------------


def test_unsolvable_dataset_is_diagnosed_before_search() -> None:
    report = plan(load_tournament(DATASETS / "unsolvable.json"), timeout_seconds=5)
    d = report.diagnosis
    assert d.feasibility is Feasibility.INFEASIBLE
    assert report.result is None  # la recherche n'a même pas été lancée
    assert _ids(d.conflicts) == {H.FIELD_CAPACITY}
    [conflict] = d.conflicts
    assert "15 matchs à placer mais seulement 12 places" in conflict.explanation
    assert any("terrain" in s for s in conflict.suggestions)
    assert any("créneaux" in s for s in conflict.suggestions)


@pytest.mark.parametrize("name", ["small", "medium"])
def test_solvable_datasets_are_feasible(name: str) -> None:
    report = plan(load_tournament(DATASETS / f"{name}.json"))
    assert report.diagnosis.feasibility is Feasibility.FEASIBLE
    assert report.diagnosis.conflicts == []


def test_timeout_is_unknown_not_infeasible() -> None:
    report = plan(load_tournament(DATASETS / "medium.json"), timeout_seconds=0)
    assert report.result is not None
    assert report.result.status is SolveStatus.TIMEOUT
    assert report.diagnosis.feasibility is Feasibility.UNKNOWN
    assert report.diagnosis.conflicts == []
    assert "ne prouve pas" in report.diagnosis.summary


# --- Filtre par suppression --------------------------------------------------------------


def _triangle() -> Tournament:
    """3 équipes, 3 créneaux consécutifs, 1 h de repos : chaque paire de matchs partage
    une équipe, donc il faudrait 3 créneaux espacés d'1 h, il n'y en a que 2 (S0 et S2)."""
    return _tournament(teams="ABC", fields=1, slots=3, rules={"min_rest_minutes": 60})


def test_triangle_passes_prechecks_but_search_finds_minimal_conflict() -> None:
    t = _triangle()
    assert precheck(t, generate_matches(t)) == []
    report = plan(t, timeout_seconds=5)
    d = report.diagnosis
    assert d.feasibility is Feasibility.INFEASIBLE
    assert report.result is not None
    assert report.result.status is SolveStatus.INFEASIBLE
    assert d.minimal is True
    [conflict] = d.conflicts
    assert conflict.source == "search"
    assert _ids(d.conflicts) == {H.MIN_REST}
    assert "réduire le temps de repos minimum" in conflict.suggestions


def test_conflict_is_infeasible_and_minimal() -> None:
    t = _triangle()
    problem = build_problem(t, generate_matches(t))
    core, minimal = find_conflict(problem)
    assert minimal

    def status(constraints: list[Any]) -> SolveStatus:
        return solve(Problem(problem.variables, problem.domains, constraints), 5).status

    assert status(core) is SolveStatus.INFEASIBLE
    for c in core:
        assert status([x for x in core if x is not c]) is SolveStatus.SOLVED


# --- Pré-vérifications, une par une ------------------------------------------------------


def test_capacity_counts_unavailable_fields_and_slot_quotas() -> None:
    t = _tournament(
        slots=4,  # 8 places brutes pour 6 matchs…
        fields=[
            {"id": "F1", "name": "Terrain 1"},
            {"id": "F2", "name": "Terrain 2", "unavailable_slots": ["D1S0", "D1S1"]},
        ],
    )
    t = t.model_copy(
        update={"slots": [t.slots[0].model_copy(update={"max_matches": 0}), *t.slots[1:]]}
    )  # … moins 2 (terrain indispo) moins 1 (quota) = 5 places
    conflicts = precheck(t, generate_matches(t))
    assert {H.FIELD_CAPACITY, H.FIELD_UNAVAILABLE, H.SLOT_QUOTA_MAX} <= _ids(conflicts)
    assert any("6 matchs à placer mais seulement 5 places" in c.explanation for c in conflicts)


def test_match_without_any_common_slot() -> None:
    t = _tournament(
        teams=[
            {"id": "A", "name": "Équipe A", "unavailable_slots": ["D1S0"]},
            {"id": "B", "name": "Équipe B", "unavailable_slots": ["D1S1"]},
        ],
        slots=2,
    )
    conflicts = precheck(t, generate_matches(t))
    assert any("ne peut se jouer sur aucun créneau" in c.explanation for c in conflicts)
    assert H.TEAM_UNAVAILABLE in _ids(conflicts)


def test_team_with_too_few_playable_slots() -> None:
    t = _tournament(
        teams="ABCD",
        fields=2,
        slots=4,
        days=2,
        rules={"min_rest_minutes": 60, "max_matches_per_team_per_day": 1},
    )
    # Chaque équipe joue 3 matchs, mais au plus 1 par jour sur 2 jours.
    conflicts = precheck(t, generate_matches(t))
    assert H.MAX_MATCHES_PER_DAY in _ids(conflicts)
    assert any(
        "doit jouer 3 matchs mais ne peut en jouer que 2" in c.explanation for c in conflicts
    )


def test_rest_reduces_team_capacity() -> None:
    t = _tournament(teams="ABCD", fields=2, slots=4, rules={"min_rest_minutes": 120})
    # 4 créneaux consécutifs d'1 h + 2 h de repos → 2 matchs max dans la journée, il en faut 3.
    conflicts = precheck(t, generate_matches(t))
    assert H.MIN_REST in _ids(conflicts)


def test_incompatible_teams_need_more_slots_than_available() -> None:
    t = _tournament(teams="ABCD", fields=2, slots=4, incompatibilities=[{"teams": ["A", "B"]}])
    # Matchs de A ∪ B = 3 + 3 - 1 = 5, tous sur des créneaux distincts, or 4 créneaux.
    conflicts = precheck(t, generate_matches(t))
    assert _ids(conflicts) == {H.INCOMPATIBLE_TEAMS, H.TEAM_ONE_MATCH_PER_SLOT}
    assert "5 matchs demandent 5 créneaux différents" in conflicts[0].explanation


def test_slot_minimum_above_slot_capacity() -> None:
    t = _tournament(teams="ABCD", fields=1, slots=6)
    t = t.model_copy(
        update={"slots": [t.slots[0].model_copy(update={"min_matches": 2}), *t.slots[1:]]}
    )
    conflicts = precheck(t, generate_matches(t))
    assert {H.SLOT_QUOTA_MIN, H.FIELD_CAPACITY} <= _ids(conflicts)


def test_sum_of_slot_minimums_above_match_count() -> None:
    t = _tournament(teams="ABC", fields=2, slots=2)
    t = t.model_copy(update={"slots": [s.model_copy(update={"min_matches": 2}) for s in t.slots]})
    conflicts = precheck(t, generate_matches(t))
    assert any("dépasse le nombre total de matchs (3)" in c.explanation for c in conflicts)


# --- Les pré-vérifications ne se trompent jamais ----------------------------------------


def test_prechecks_never_reject_a_solvable_tournament() -> None:
    """Une pré-vérification est une condition *nécessaire* : si le solveur trouve un
    planning, aucune pré-vérification ne doit avoir crié à l'impossible."""
    rng = random.Random(6)
    checked = 0
    for _ in range(300):
        n_slots, days = rng.randint(2, 4), rng.randint(1, 2)
        slot_ids = [f"D{d}S{i}" for d in range(1, days + 1) for i in range(n_slots)]
        teams = [
            {
                "id": t,
                "name": t,
                "unavailable_slots": rng.sample(slot_ids, rng.randint(0, 2)),
            }
            for t in "ABCD"[: rng.randint(3, 4)]
        ]
        t = _tournament(
            fields=rng.randint(1, 2),
            slots=n_slots,
            days=days,
            teams=teams,
            rules={
                "min_rest_minutes": rng.choice([0, 0, 60]),
                "max_matches_per_team_per_day": rng.choice([None, 1, 2]),
            },
            incompatibilities=[{"teams": ["A", "B"]}] if rng.random() < 0.3 else [],
        )
        matches = generate_matches(t)
        result = solve(build_problem(t, matches), timeout_seconds=2)
        if result.status is SolveStatus.SOLVED:
            checked += 1
            assert precheck(t, matches) == [], t
    assert checked > 20  # le générateur produit bien des cas solubles
