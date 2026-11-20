"""Chercher d'abord un planning par journées de poule, puis laisser le CSP général essayer.

Regrouper les rencontres d'une même journée réduit les permutations inutiles quand les
terrains permettent de les accueillir ensemble. Cette recherche explore un sous-ensemble
des solutions : son échec ne constitue jamais une preuve d'impossibilité.
"""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter

from planning.checker import validate
from planning.constraints.hard import (
    FieldCapacity,
    IncompatibleTeams,
    MaxMatchesPerDay,
    MinRest,
    SlotQuotaMin,
    TeamOneMatchPerSlot,
)
from planning.domain.models import Match, Tournament
from planning.solver.backtracking import SolveResult, SolveStats, SolveStatus, StopCallback, solve
from planning.solver.csp import Constraint, Problem, Value
from planning.solver.tournament import to_schedule


def seed_rounds(
    tournament: Tournament,
    matches: list[Match],
    timeout_seconds: float,
    should_stop: StopCallback | None = None,
) -> SolveResult | None:
    started = perf_counter()
    batches: dict[tuple[str | None, int, int], list[Match]] = defaultdict(list)
    for match in matches:
        batches[match.pool, match.leg, match.round].append(match)
    if (
        not batches
        or len(batches) > len(tournament.slots)
        or max(map(len, batches.values())) > len(tournament.fields)
    ):
        return None
    groups = {f"round_{i}": batch for i, batch in enumerate(batches.values())}
    variables = list(groups)
    slots = {slot.id: slot for slot in tournament.slots}
    by_team = {
        team.id: [v for v, batch in groups.items() if any(team.id in m.teams for m in batch)]
        for team in tournament.teams
    }
    domains: dict[str, list[Value]] = {}
    for var, batch in groups.items():
        if should_stop is not None and should_stop():
            return SolveResult(SolveStatus.CANCELLED, None)
        if perf_counter() - started >= timeout_seconds:
            return None
        participants = {team for match in batch for team in match.teams}
        if len(participants) != 2 * len(batch):
            return None
        for inc in tournament.incompatibilities:
            a, b = inc.teams
            if (
                a in participants
                and b in participants
                and not any(a in match.teams and b in match.teams for match in batch)
            ):
                return None
        domains[var] = [
            (slot.id, "round")
            for slot in tournament.slots
            if all(slot.id not in tournament.team(team).unavailable_slots for team in participants)
            and sum(slot.id not in field.unavailable_slots for field in tournament.fields)
            >= len(batch)
            and (slot.max_matches is None or slot.max_matches >= len(batch))
            and slot.min_matches <= len(batch)
        ]
    constraints: list[Constraint] = [FieldCapacity(variables, "une journée par créneau")]
    for team, own in by_team.items():
        constraints.extend(
            [
                TeamOneMatchPerSlot(own, f"{team} : une rencontre à la fois"),
                MinRest(own, slots, tournament.rules.min_rest_minutes, f"{team} : repos"),
            ]
        )
        limit = tournament.rules.max_matches_per_team_per_day
        if limit is not None:
            constraints.append(MaxMatchesPerDay(own, slots, limit, f"{team} : limite quotidienne"))
    for inc in tournament.incompatibilities:
        a, b = inc.teams
        constraints.append(IncompatibleTeams(by_team[a], by_team[b], f"{a} et {b} incompatibles"))
    constraints.extend(
        SlotQuotaMin(variables, slot.id, 1, f"{slot.id} : créneau à remplir")
        for slot in tournament.slots
        if slot.min_matches > 0
    )
    remaining = timeout_seconds - (perf_counter() - started)
    if remaining <= 0:
        return None
    result = solve(Problem(variables, domains, constraints), remaining, should_stop)
    if should_stop is not None and should_stop():
        return SolveResult(SolveStatus.CANCELLED, None)
    if result.status is SolveStatus.CANCELLED:
        return result
    if result.assignment is None:
        return None
    assignment: dict[str, Value] = {}
    for var, (slot_id, _) in result.assignment.items():
        free_fields = [
            field.id for field in tournament.fields if slot_id not in field.unavailable_slots
        ]
        for match, field_id in zip(groups[var], free_fields, strict=False):
            assignment[match.id] = slot_id, field_id
    # Vérifier les règles originales, pas seulement le problème regroupé.
    if validate(tournament, to_schedule(assignment), matches):
        return None
    return SolveResult(
        SolveStatus.SOLVED,
        assignment,
        SolveStats(
            nodes=result.stats.nodes,
            backtracks=result.stats.backtracks,
            max_depth=len(matches),
            elapsed_seconds=perf_counter() - started,
        ),
    )
