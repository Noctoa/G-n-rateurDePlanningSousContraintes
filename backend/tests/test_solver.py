"""Tests du moteur de backtracking.

Les plannings trouvés sont vérifiés par `_hard_violations`, écrit ici directement à partir
des données du tournoi, sans réutiliser les classes de contraintes du solveur.
"""

import random
from collections import Counter
from itertools import combinations
from pathlib import Path

import pytest

from planning.domain import Match, Slot, Team, Tournament, Venue, load_tournament
from planning.solver import Problem, SolveStatus, build_problem, solve, solve_tournament
from planning.solver.csp import Assignment, Constraint, Value

DATASETS = Path(__file__).resolve().parents[2] / "datasets"


def _hard_violations(t: Tournament, matches: list[Match], plan: dict[str, Value]) -> list[str]:
    slots = {s.id: s for s in t.slots}
    teams = {x.id: x for x in t.teams}
    fields = {f.id: f for f in t.fields}
    errors: list[str] = []

    if set(plan) != {m.id for m in matches}:
        errors.append("tous les matchs ne sont pas placés")
    for value, n in Counter(plan.values()).items():
        if n > 1:
            errors.append(f"H1 {value}")
    by_team: dict[str, list[tuple[str, Slot]]] = {x: [] for x in teams}
    for m in matches:
        slot_id, field_id = plan[m.id]
        for team_id in m.teams:
            by_team[team_id].append((m.id, slots[slot_id]))
            if slot_id in teams[team_id].unavailable_slots:
                errors.append(f"H3 {team_id} {slot_id}")
        if slot_id in fields[field_id].unavailable_slots:
            errors.append(f"H4 {field_id} {slot_id}")
    for team, games in by_team.items():
        ordered = sorted((s for _, s in games), key=lambda s: s.starts_at)
        for first, second in combinations(ordered, 2):
            if first.id == second.id:
                errors.append(f"H2 {team} {first.id}")
            gap = (second.starts_at - first.ends_at).total_seconds() / 60
            if gap < t.rules.min_rest_minutes:
                errors.append(f"H5 {team} {first.id}->{second.id}")
        limit = t.rules.max_matches_per_team_per_day
        if limit is not None:
            for day, n in Counter(s.day for s in ordered).items():
                if n > limit:
                    errors.append(f"H6 {team} {day}")
    for inc in t.incompatibilities:
        a, b = inc.teams
        for (ma, sa), (mb, sb) in ((x, y) for x in by_team[a] for y in by_team[b]):
            if ma != mb and sa.id == sb.id:
                errors.append(f"H7 {a}/{b} {sa.id}")
    per_slot = Counter(slot_id for slot_id, _ in plan.values())
    for s in t.slots:
        if s.max_matches is not None and per_slot[s.id] > s.max_matches:
            errors.append(f"H8 {s.id}")
        if per_slot[s.id] < s.min_matches:
            errors.append(f"H9 {s.id}")
    return errors


@pytest.mark.parametrize("name", ["small", "medium"])
def test_datasets_are_solved_and_independently_valid(name: str) -> None:
    tournament = load_tournament(DATASETS / f"{name}.json")
    matches, result = solve_tournament(tournament, timeout_seconds=10)
    assert result.status is SolveStatus.SOLVED
    assert result.assignment is not None
    assert _hard_violations(tournament, matches, result.assignment) == []
    assert result.stats.nodes >= len(matches)
    assert result.stats.max_depth == len(matches)


def test_unsolvable_dataset_times_out_without_claiming_impossibility() -> None:
    tournament = load_tournament(DATASETS / "unsolvable.json")
    _, result = solve_tournament(tournament, timeout_seconds=0.3)
    assert result.status is SolveStatus.TIMEOUT
    assert result.assignment is None


def _tiny(slots: int, unavailable: list[str] | None = None) -> Tournament:
    return Tournament(
        name="mini",
        teams=[
            Team(id="A", name="A", unavailable_slots=unavailable or []),
            Team(id="B", name="B"),
            Team(id="C", name="C"),
        ],
        fields=[Venue(id="F", name="F")],
        slots=[
            Slot(id=f"S{i}", day="2026-12-05", start=f"{9 + i:02d}:00", duration_minutes=60)  # type: ignore[arg-type]
            for i in range(slots)
        ],
    )


def test_small_infeasible_tournament_is_proven_infeasible() -> None:
    _, result = solve_tournament(_tiny(slots=2), timeout_seconds=5)  # 3 matchs, 2 places
    assert result.status is SolveStatus.INFEASIBLE
    assert result.stats.backtracks > 0


def test_empty_domain_is_reported_before_search() -> None:
    # A est indisponible sur l'unique créneau : ses deux matchs n'ont aucune valeur possible.
    matches, result = solve_tournament(_tiny(slots=1, unavailable=["S0"]), timeout_seconds=5)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.stats.nodes == 0
    assert result.empty_domains == [m.id for m in matches if "A" in m.teams]


class _AllDifferent(Constraint):
    def is_satisfied(self, assignment: Assignment) -> bool:
        values = [assignment[v] for v in self.variables if v in assignment]
        return len(values) == len(set(values))


def _coloring(n: int, k: int) -> Problem:
    """n variables toutes différentes avec k valeurs : soluble ssi n <= k."""
    variables = [f"x{i}" for i in range(n)]
    domain = [(f"c{j}", "-") for j in range(k)]
    return Problem(
        variables=variables,
        domains={v: list(domain) for v in variables},
        constraints=[_AllDifferent(variables, "all different")],
    )


def test_generic_engine_solves_proves_and_times_out() -> None:
    assert solve(_coloring(4, 4)).status is SolveStatus.SOLVED
    infeasible = solve(_coloring(5, 4))
    assert infeasible.status is SolveStatus.INFEASIBLE
    assert infeasible.stats.backtracks > 0
    # 10 variables pour 9 valeurs : 9! affectations partielles à épuiser → timeout immédiat.
    assert solve(_coloring(10, 9), timeout_seconds=0.0).status is SolveStatus.TIMEOUT


def test_empty_problem_is_trivially_solved() -> None:
    result = solve(Problem(variables=[], domains={}, constraints=[]))
    assert result.status is SolveStatus.SOLVED
    assert result.assignment == {}


def test_incremental_checks_agree_with_full_checks() -> None:
    """`is_consistent` (rapide, utilisé par le solveur) == `is_satisfied` (référence)."""
    tournament = load_tournament(DATASETS / "medium.json")
    problem = build_problem(tournament, solve_tournament(tournament, 1)[0])
    values = next(iter(problem.domains.values()))
    rng = random.Random(42)
    for _ in range(300):
        placed = rng.sample(problem.variables, rng.randint(0, 20))
        assignment = {v: rng.choice(values) for v in placed}
        var = rng.choice(problem.variables)
        value = rng.choice(values)
        partial = {k: v for k, v in assignment.items() if k != var}
        for c in problem.constraints_of[var]:
            if not c.is_satisfied(partial):
                continue
            assert c.is_consistent(var, value, partial) == c.is_satisfied(
                {**partial, var: value}
            ), c
