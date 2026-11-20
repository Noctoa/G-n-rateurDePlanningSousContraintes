"""Backtracking de tournoi : MRV, LCV et propagation des domaines par masques de bits.

Le moteur chronologique reste disponible pour comparer les recherches. Ici, les matchs
les plus contraints passent d'abord et chaque placement retire immédiatement les valeurs
interdites des autres domaines. Aucune règle ni indisponibilité n'est assouplie.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from time import perf_counter

from planning.domain.models import Match, Tournament
from planning.solver.backtracking import SolveResult, SolveStats, SolveStatus, StopCallback
from planning.solver.csp import Value
from planning.solver.round_seed import seed_rounds
from planning.solver.tournament import build_problem


def _bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask -= bit


@dataclass
class _Frame:
    variable: int
    values: Iterator[int]
    domains: dict[int, int]


class _StoppedError(Exception):
    def __init__(self, status: SolveStatus) -> None:
        self.status = status


class _Search:
    def __init__(
        self,
        tournament: Tournament,
        matches: list[Match],
        stats: SolveStats,
        deadline: float | None,
        should_stop: StopCallback | None,
    ) -> None:
        self.tournament = tournament
        self.matches = matches
        self.stats = stats
        self.deadline = deadline
        self.should_stop = should_stop
        self.problem = build_problem(tournament, matches)
        self.slots = sorted(tournament.slots, key=lambda s: s.starts_at)
        self.width = len(tournament.fields)
        self.values = [(s.id, f.id) for s in self.slots for f in tournament.fields]
        value_index = {value: i for i, value in enumerate(self.values)}
        self.slot_masks = [
            ((1 << self.width) - 1) << (i * self.width) for i in range(len(self.slots))
        ]
        days = sorted({s.day for s in self.slots})
        self.day_of = [days.index(s.day) for s in self.slots]
        self.day_masks = [
            sum(self.slot_masks[i] for i, s in enumerate(self.slots) if s.day == day)
            for day in days
        ]
        self.rest_masks: list[int] = []
        for a in self.slots:
            self.check_stop()
            mask = 0
            for j, b in enumerate(self.slots):
                first, second = (a, b) if a.starts_at <= b.starts_at else (b, a)
                gap = (second.starts_at - first.ends_at).total_seconds()
                if gap < tournament.rules.min_rest_minutes * 60:
                    mask |= self.slot_masks[j]
            self.rest_masks.append(mask)
        self.teams = [frozenset(match.teams) for match in matches]
        incompatible = {frozenset(inc.teams) for inc in tournament.incompatibilities}
        self.shared = [[bool(a & b) for b in self.teams] for a in self.teams]
        self.incompatible = [
            [any(frozenset((x, y)) in incompatible for x in a for y in b) for b in self.teams]
            for a in self.teams
        ]
        self.team_scope = {
            team.id: [i for i, match in enumerate(matches) if team.id in match.teams]
            for team in tournament.teams
        }
        domains = self.problem.node_consistent_domains()
        self.initial = {
            i: sum(1 << value_index[value] for value in domains[match.id])
            for i, match in enumerate(matches)
        }
        self.assignment: dict[int, int] = {}
        self.named_assignment: dict[str, Value] = {}
        self.team_day: Counter[tuple[str, int]] = Counter()
        self.slot_load: Counter[int] = Counter()

    def check_stop(self) -> None:
        if self.should_stop is not None and self.should_stop():
            raise _StoppedError(SolveStatus.CANCELLED)
        if self.deadline is not None and perf_counter() >= self.deadline:
            raise _StoppedError(SolveStatus.TIMEOUT)

    def frame(self, domains: dict[int, int]) -> _Frame:
        self.check_stop()
        # MRV ; les liens d'équipe/incompatibilité départagent les tailles égales.
        var = min(
            domains,
            key=lambda v: (
                domains[v].bit_count(),
                -sum(self.shared[v][other] or self.incompatible[v][other] for other in domains),
                v,
            ),
        )

        def impact(index: int) -> int:
            slot = index // self.width
            return sum(
                (
                    mask
                    & (
                        (1 << index)
                        | (self.rest_masks[slot] if self.shared[var][other] else 0)
                        | (self.slot_masks[slot] if self.incompatible[var][other] else 0)
                    )
                ).bit_count()
                for other, mask in domains.items()
                if other != var
            )

        # LCV : essayer d'abord les valeurs retirant le moins de choix aux autres matchs.
        values = sorted(_bits(domains[var]), key=impact)
        return _Frame(var, iter(values), domains)

    def place(self, var: int, index: int) -> None:
        self.assignment[var] = index
        self.named_assignment[self.matches[var].id] = self.values[index]
        slot = index // self.width
        for team in self.teams[var]:
            self.team_day[team, self.day_of[slot]] += 1
        self.slot_load[slot] += 1
        self.stats.max_depth = max(self.stats.max_depth, len(self.assignment))

    def unplace(self, var: int) -> None:
        index = self.assignment.pop(var)
        del self.named_assignment[self.matches[var].id]
        slot = index // self.width
        for team in self.teams[var]:
            self.team_day[team, self.day_of[slot]] -= 1
        self.slot_load[slot] -= 1

    def propagate(self, var: int, index: int, domains: dict[int, int]) -> dict[int, int] | None:
        slot = index // self.width
        day = self.day_of[slot]
        limit = self.tournament.rules.max_matches_per_team_per_day
        quota = self.slots[slot].max_matches
        result: dict[int, int] = {}
        for other, mask in domains.items():
            if other == var:
                continue
            mask &= ~(1 << index)  # terrain occupé
            if self.shared[var][other]:
                mask &= ~self.rest_masks[slot]
            if self.incompatible[var][other]:
                mask &= ~self.slot_masks[slot]
            if limit is not None and any(
                self.team_day[team, day] >= limit for team in self.teams[other]
            ):
                mask &= ~self.day_masks[day]
            if quota is not None and self.slot_load[slot] >= quota:
                mask &= ~self.slot_masks[slot]
            if not mask:
                return None
            result[other] = mask
        # Coupe sûre : même l'union des horaires encore possibles doit permettre de
        # placer tous les matchs restants d'une équipe en respectant repos et limites.
        for team, scope in self.team_scope.items():
            own = [v for v in scope if v in result]
            if not own:
                continue
            possible = 0
            for v in own:
                possible |= result[v]
            capacity = 0
            for day_index in range(len(self.day_masks)):
                selected = 0
                last_end = None
                for j, s in enumerate(self.slots):
                    if self.day_of[j] != day_index or not possible & self.slot_masks[j]:
                        continue
                    if last_end is None or (s.starts_at - last_end).total_seconds() >= (
                        self.tournament.rules.min_rest_minutes * 60
                    ):
                        selected += 1
                        last_end = s.ends_at
                if limit is not None:
                    selected = min(selected, limit - self.team_day[team, day_index])
                capacity += selected
            if capacity < len(own):
                return None
        for j, s in enumerate(self.slots):
            needed = s.min_matches - self.slot_load[j]
            if needed <= 0:
                continue
            candidates = [v for v, mask in result.items() if mask & self.slot_masks[j]]
            if len(candidates) < needed:
                return None
            if len(candidates) == needed:
                for v in candidates:
                    result[v] &= self.slot_masks[j]
                    if not result[v]:
                        return None
        return result

    def run(self) -> SolveStatus:
        self.check_stop()
        if not self.initial:
            return (
                SolveStatus.SOLVED
                if all(c.is_satisfied({}) for c in self.problem.constraints)
                else SolveStatus.INFEASIBLE
            )
        if any(not mask for mask in self.initial.values()):
            return SolveStatus.INFEASIBLE
        stack = [self.frame(self.initial)]
        while stack:
            self.check_stop()
            current = stack[-1]
            for index in current.values:
                self.check_stop()
                self.stats.nodes += 1
                var = current.variable
                if not self.problem.is_consistent(
                    self.matches[var].id, self.values[index], self.named_assignment
                ):
                    continue
                self.place(var, index)
                reduced = self.propagate(var, index, current.domains)
                if reduced is None:
                    self.unplace(var)
                    continue
                if not reduced:
                    return SolveStatus.SOLVED
                stack.append(self.frame(reduced))
                break
            else:
                stack.pop()
                self.stats.backtracks += 1
                if stack:
                    self.unplace(stack[-1].variable)
        return SolveStatus.INFEASIBLE


def solve_guided(
    tournament: Tournament,
    matches: list[Match],
    timeout_seconds: float | None = 10.0,
    should_stop: StopCallback | None = None,
) -> SolveResult:
    started = perf_counter()
    stats = SolveStats()
    deadline = None if timeout_seconds is None else started + timeout_seconds
    search = None
    try:
        if should_stop is not None and should_stop():
            raise _StoppedError(SolveStatus.CANCELLED)
        if deadline is not None and perf_counter() >= deadline:
            raise _StoppedError(SolveStatus.TIMEOUT)
        seed_budget = 0.1 if timeout_seconds is None else min(0.1, timeout_seconds * 0.2)
        seeded = seed_rounds(tournament, matches, seed_budget, should_stop)
        if seeded is not None:
            seeded.stats.elapsed_seconds = perf_counter() - started
            return seeded
        search = _Search(tournament, matches, stats, deadline, should_stop)
        status = search.run()
    except _StoppedError as stopped:
        status = stopped.status
    stats.elapsed_seconds = perf_counter() - started
    return SolveResult(
        status,
        dict(search.named_assignment) if status is SolveStatus.SOLVED and search else None,
        stats,
    )
