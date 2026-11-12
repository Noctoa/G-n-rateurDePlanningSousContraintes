"""Traduction d'un tournoi en CSP, et d'une solution du CSP en planning."""

from __future__ import annotations

from planning.constraints.catalog import HardConstraintId as H
from planning.constraints.hard import (
    FieldCapacity,
    IncompatibleTeams,
    MaxMatchesPerDay,
    MinRest,
    SlotQuotaMax,
    SlotQuotaMin,
    SlotsUnavailable,
    TeamOneMatchPerSlot,
)
from planning.domain.fixtures import generate_matches
from planning.domain.models import Assignment, Match, Schedule, Tournament
from planning.solver.backtracking import SolveResult, solve
from planning.solver.csp import Constraint, Problem, Value, Variable


def build_problem(tournament: Tournament, matches: list[Match]) -> Problem:
    """Variables = matchs, domaine = tous les (créneau, terrain), contraintes = H1…H9."""
    slots = {s.id: s for s in tournament.slots}
    chronological = sorted(tournament.slots, key=lambda s: s.starts_at)
    all_values: list[Value] = [(s.id, f.id) for s in chronological for f in tournament.fields]

    variables: list[Variable] = [m.id for m in matches]
    by_team: dict[str, list[Variable]] = {t.id: [] for t in tournament.teams}
    for m in matches:
        for team_id in m.teams:
            by_team[team_id].append(m.id)

    constraints: list[Constraint] = [FieldCapacity(variables, "un match par terrain et créneau")]

    for team in tournament.teams:
        own = by_team[team.id]
        if len(own) > 1:
            constraints.append(TeamOneMatchPerSlot(own, f"équipe {team.id} : un match à la fois"))
        if team.unavailable_slots and own:
            constraints.append(
                SlotsUnavailable(
                    H.TEAM_UNAVAILABLE,
                    own,
                    team.unavailable_slots,
                    f"équipe {team.id} indisponible",
                )
            )
        if tournament.rules.min_rest_minutes > 0 and len(own) > 1:
            constraints.append(
                MinRest(
                    own,
                    slots,
                    tournament.rules.min_rest_minutes,
                    f"équipe {team.id} : repos de {tournament.rules.min_rest_minutes} min",
                )
            )
        limit = tournament.rules.max_matches_per_team_per_day
        if limit is not None and len(own) > limit:
            constraints.append(
                MaxMatchesPerDay(own, slots, limit, f"équipe {team.id} : {limit} matchs/jour max")
            )

    for venue in tournament.fields:
        if venue.unavailable_slots:
            constraints.append(
                SlotsUnavailable(
                    H.FIELD_UNAVAILABLE,
                    variables,
                    venue.unavailable_slots,
                    f"terrain {venue.id} indisponible",
                    field_id=venue.id,
                )
            )

    for inc in tournament.incompatibilities:
        a, b = inc.teams
        if by_team[a] and by_team[b]:
            constraints.append(
                IncompatibleTeams(by_team[a], by_team[b], f"{a} et {b} jamais en même temps")
            )

    for slot in tournament.slots:
        if slot.max_matches is not None and slot.max_matches < len(tournament.fields):
            constraints.append(
                SlotQuotaMax(
                    variables, slot.id, slot.max_matches, f"{slot.id} : {slot.max_matches} max"
                )
            )
        if slot.min_matches > 0:
            constraints.append(
                SlotQuotaMin(
                    variables, slot.id, slot.min_matches, f"{slot.id} : {slot.min_matches} min"
                )
            )

    return Problem(
        variables=variables,
        domains={v: list(all_values) for v in variables},
        constraints=constraints,
    )


def to_schedule(assignment: dict[Variable, Value]) -> Schedule:
    return Schedule(
        assignments=[
            Assignment(match_id=m, slot_id=s, field_id=f)
            for m, (s, f) in sorted(assignment.items())
        ]
    )


def solve_tournament(
    tournament: Tournament, timeout_seconds: float | None = 10.0
) -> tuple[list[Match], SolveResult]:
    matches = generate_matches(tournament)
    return matches, solve(build_problem(tournament, matches), timeout_seconds)
