"""Un cas valide et un cas invalide par contrainte dure, construits à la main.

Chaque cas est passé à la fois :
- au vérificateur indépendant (`planning.checker.validate`) ;
- aux classes de contraintes du solveur (`planning.constraints.hard`, via `build_problem`).
Les deux doivent rendre le même verdict.

Tournoi de base : 4 équipes A, B, C, D ; 2 terrains F1, F2 ; créneaux d'1 h
S1 09:00, S2 10:00, S3 11:00 le samedi et S4 09:00 le dimanche.
"""

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from planning.checker import validate
from planning.constraints.catalog import HardConstraintId as H
from planning.domain import Assignment, Match, Schedule, Tournament, generate_matches
from planning.domain import load_tournament as load
from planning.solver import build_problem
from planning.solver.csp import Value

DATASETS = Path(__file__).resolve().parents[2] / "datasets"

Placement = dict[tuple[str, str], tuple[str, str]]
"""(équipe, équipe) → (créneau, terrain)"""


def _tournament(**overrides: Any) -> Tournament:
    data: dict[str, Any] = {
        "name": "cas de test",
        "teams": [{"id": t, "name": f"Équipe {t}"} for t in "ABCD"],
        "fields": [{"id": "F1", "name": "Terrain 1"}, {"id": "F2", "name": "Terrain 2"}],
        "slots": [
            {"id": "S1", "day": "2026-12-05", "start": "09:00", "duration_minutes": 60},
            {"id": "S2", "day": "2026-12-05", "start": "10:00", "duration_minutes": 60},
            {"id": "S3", "day": "2026-12-05", "start": "11:00", "duration_minutes": 60},
            {"id": "S4", "day": "2026-12-06", "start": "09:00", "duration_minutes": 60},
        ],
    }
    for key, value in overrides.items():
        if key == "team_A":
            data["teams"][0] |= value
        elif key == "field_F2":
            data["fields"][1] |= value
        elif key == "slot_S1":
            data["slots"][0] |= value
        else:
            data[key] = value
    return Tournament.model_validate(data)


def _match(matches: list[Match], a: str, b: str) -> Match:
    return next(m for m in matches if set(m.teams) == {a, b})


@dataclass
class Case:
    constraint: H
    tournament: Tournament
    valid: Placement
    invalid: Placement
    expected_in_message: str
    notes: dict[str, str] = field(default_factory=dict)


CASES = [
    Case(
        H.FIELD_CAPACITY,
        _tournament(),
        valid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S1", "F2")},
        invalid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S1", "F1")},
        expected_in_message="2 matchs sur le terrain F1 au créneau S1",
    ),
    Case(
        H.TEAM_ONE_MATCH_PER_SLOT,
        _tournament(),
        valid={("A", "B"): ("S1", "F1"), ("A", "C"): ("S2", "F1")},
        invalid={("A", "B"): ("S1", "F1"), ("A", "C"): ("S1", "F2")},
        expected_in_message="Équipe A joue 2 matchs en même temps au créneau S1",
    ),
    Case(
        H.TEAM_UNAVAILABLE,
        _tournament(team_A={"unavailable_slots": ["S1"]}),
        valid={("A", "B"): ("S2", "F1")},
        invalid={("A", "B"): ("S1", "F1")},
        expected_in_message="Équipe A est indisponible au créneau S1",
    ),
    Case(
        H.FIELD_UNAVAILABLE,
        _tournament(field_F2={"unavailable_slots": ["S1"]}),
        valid={("A", "B"): ("S1", "F1")},
        invalid={("A", "B"): ("S1", "F2")},
        expected_in_message="le terrain Terrain 2 est indisponible au créneau S1",
    ),
    Case(
        H.MIN_REST,
        _tournament(rules={"min_rest_minutes": 60}),
        valid={("A", "B"): ("S1", "F1"), ("A", "C"): ("S3", "F1")},
        invalid={("A", "B"): ("S1", "F1"), ("A", "C"): ("S2", "F1")},
        expected_in_message="Équipe A n'a que 0 min de repos",
    ),
    Case(
        H.MAX_MATCHES_PER_DAY,
        _tournament(rules={"max_matches_per_team_per_day": 1}),
        valid={("A", "B"): ("S1", "F1"), ("A", "C"): ("S4", "F1")},
        invalid={("A", "B"): ("S1", "F1"), ("A", "C"): ("S3", "F1")},
        expected_in_message="Équipe A joue 2 matchs le samedi 05/12 (maximum 1)",
    ),
    Case(
        H.INCOMPATIBLE_TEAMS,
        _tournament(incompatibilities=[{"teams": ["A", "D"], "reason": "même coach"}]),
        # A–D ensemble est permis : c'est un seul match.
        valid={("A", "D"): ("S1", "F1"), ("B", "C"): ("S1", "F2")},
        invalid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S1", "F2")},
        expected_in_message="ne doivent pas jouer en même temps (même coach)",
    ),
    Case(
        H.SLOT_QUOTA_MAX,
        _tournament(slot_S1={"max_matches": 1}),
        valid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S2", "F1")},
        invalid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S1", "F2")},
        expected_in_message="2 matchs au créneau S1, maximum 1",
    ),
    Case(
        H.SLOT_QUOTA_MIN,
        _tournament(slot_S1={"min_matches": 2}),
        valid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S1", "F2")},
        invalid={("A", "B"): ("S1", "F1"), ("C", "D"): ("S2", "F1")},
        expected_in_message="1 match(s) au créneau S1, minimum 2",
    ),
]


def _ids(cases: list[Case]) -> list[str]:
    return [f"{c.constraint.value}-{c.constraint.name}" for c in cases]


def _schedule(t: Tournament, placement: Placement) -> tuple[list[Match], Schedule]:
    """Matchs concernés par le placement, et le planning correspondant."""
    all_matches = generate_matches(t)
    matches = [_match(all_matches, a, b) for a, b in placement]
    schedule = Schedule(
        assignments=[
            Assignment(match_id=m.id, slot_id=s, field_id=f)
            for m, (s, f) in zip(matches, placement.values(), strict=True)
        ]
    )
    return matches, schedule


def _solver_verdict(t: Tournament, placement: Placement, constraint: H) -> bool:
    """`True` si toutes les contraintes `constraint` du solveur sont satisfaites."""
    matches, schedule = _schedule(t, placement)
    problem = build_problem(t, matches)
    assignment = {a.match_id: (a.slot_id, a.field_id) for a in schedule.assignments}
    concerned = [c for c in problem.constraints if c.id is constraint]
    assert concerned, f"le solveur n'a créé aucune contrainte {constraint}"
    return all(c.is_satisfied(assignment) for c in concerned)


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_valid_case_has_no_violation(case: Case) -> None:
    matches, schedule = _schedule(case.tournament, case.valid)
    assert validate(case.tournament, schedule, matches) == []
    assert _solver_verdict(case.tournament, case.valid, case.constraint)


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_invalid_case_is_detected_with_readable_message(case: Case) -> None:
    matches, schedule = _schedule(case.tournament, case.invalid)
    violations = validate(case.tournament, schedule, matches)
    # Un cas invalide peut en violer d'autres par ricochet (ex. H2 implique H5),
    # mais il doit au moins violer la contrainte visée.
    assert case.constraint in {v.constraint for v in violations}
    messages = [v.message for v in violations if v.constraint is case.constraint]
    assert any(case.expected_in_message in m for m in messages), messages
    assert not _solver_verdict(case.tournament, case.invalid, case.constraint)


def test_every_hard_constraint_has_a_case() -> None:
    assert {c.constraint for c in CASES} == set(H)


# --- Structure du planning ------------------------------------------------------------


def test_missing_unknown_and_duplicate_matches_are_reported() -> None:
    t = _tournament()
    matches = generate_matches(t)
    first, second = matches[0], matches[1]
    schedule = Schedule(
        assignments=[
            Assignment(match_id=first.id, slot_id="S1", field_id="F1"),
            Assignment(match_id=first.id, slot_id="S2", field_id="F1"),
            Assignment(match_id="M999", slot_id="S1", field_id="F1"),
            Assignment(match_id=second.id, slot_id="S9", field_id="F1"),
        ]
    )
    messages = [v.message for v in validate(t, schedule) if v.constraint is None]
    assert any("est placé 2 fois" in m for m in messages)
    assert any("match inconnu : M999" in m for m in messages)
    assert any("inconnu (S9)" in m for m in messages)
    assert any(f"{len(matches) - 2} match(s) non placé(s)" in m for m in messages)


def test_partial_schedule_can_be_checked_without_completeness() -> None:
    t = _tournament()
    _, schedule = _schedule(t, {("A", "B"): ("S1", "F1")})
    assert validate(t, schedule, require_complete=False) == []
    assert [v.constraint for v in validate(t, schedule)] == [None]


def test_hand_built_schedule_with_many_violations_reports_them_all() -> None:
    t = _tournament(
        team_A={"unavailable_slots": ["S1"]},
        field_F2={"unavailable_slots": ["S2"]},
        rules={"min_rest_minutes": 60, "max_matches_per_team_per_day": 2},
        incompatibilities=[{"teams": ["B", "C"]}],
        slot_S1={"max_matches": 1},
    )
    placement: Placement = {
        ("A", "B"): ("S1", "F1"),  # H3 (A indispo S1)
        ("C", "D"): ("S1", "F1"),  # H1 (même case), H7 (B et C en même temps), H8 (S1 max 1)
        ("A", "C"): ("S2", "F2"),  # H4 (F2 indispo S2), H5 (A et C sans repos)
        ("A", "D"): ("S3", "F1"),  # H5, H6 (A joue 3 fois le samedi)
        ("B", "D"): ("S3", "F2"),  # H2 (D joue deux fois à S3)
        ("B", "C"): ("S4", "F1"),
    }
    matches, schedule = _schedule(t, placement)
    found = {v.constraint for v in validate(t, schedule, matches)}
    assert found == set(H) - {H.SLOT_QUOTA_MIN}


# --- Le vérificateur et le solveur sont d'accord ----------------------------------------


@pytest.mark.parametrize("name", ["small", "medium"])
def test_checker_and_solver_constraints_agree_on_random_schedules(name: str) -> None:
    t = load(DATASETS / f"{name}.json")
    matches = generate_matches(t)
    problem = build_problem(t, matches)
    values: list[Value] = [(s.id, f.id) for s in t.slots for f in t.fields]
    rng = random.Random(name)
    for _ in range(200):
        assignment = {m.id: rng.choice(values) for m in matches}
        schedule = Schedule(
            assignments=[
                Assignment(match_id=m, slot_id=s, field_id=f) for m, (s, f) in assignment.items()
            ]
        )
        from_checker = {v.constraint for v in validate(t, schedule, matches)}
        from_solver = {c.id for c in problem.constraints if not c.is_satisfied(assignment)}
        assert from_checker == from_solver
