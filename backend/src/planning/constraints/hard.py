"""Contraintes dures H1 à H9 (définitions : docs/constraints.md).

Chaque classe implémente :
- `is_satisfied(assignment)` : vérification complète sur la portée (affectation partielle
  acceptée, cf. `Constraint`) ;
- `is_consistent(var, value, assignment)` : vérification incrémentale, appelée par le
  solveur à chaque nœud, qui ne compare la nouvelle valeur qu'aux variables déjà placées.

Une valeur est un couple `(slot_id, field_id)`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from itertools import pairwise

from planning.constraints.catalog import HardConstraintId as H
from planning.domain.models import Slot
from planning.solver.csp import Assignment, Constraint, UnaryConstraint, Value, Variable


def _assigned(
    variables: Iterable[Variable], assignment: Assignment
) -> list[tuple[Variable, Value]]:
    return [(v, assignment[v]) for v in variables if v in assignment]


class FieldCapacity(Constraint):
    """H1 : deux matchs ne partagent jamais le même couple (créneau, terrain)."""

    id = H.FIELD_CAPACITY

    def is_satisfied(self, assignment: Assignment) -> bool:
        values = [val for _, val in _assigned(self.variables, assignment)]
        return len(values) == len(set(values))

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        return all(assignment[v] != value for v in self.variables if v != var and v in assignment)


class TeamOneMatchPerSlot(Constraint):
    """H2 : les matchs d'une même équipe sont sur des créneaux distincts."""

    id = H.TEAM_ONE_MATCH_PER_SLOT

    def is_satisfied(self, assignment: Assignment) -> bool:
        slots = [val[0] for _, val in _assigned(self.variables, assignment)]
        return len(slots) == len(set(slots))

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        return all(
            assignment[v][0] != value[0] for v in self.variables if v != var and v in assignment
        )


class SlotsUnavailable(UnaryConstraint):
    """H3 / H4 : certaines valeurs sont interdites (indisponibilité d'une équipe ou d'un terrain).

    `forbidden` est l'ensemble des couples (créneau, terrain) interdits pour les variables
    de la portée ; on le construit à partir des créneaux indisponibles.
    """

    def __init__(
        self,
        constraint_id: H,
        variables: Iterable[Variable],
        forbidden_slots: Iterable[str],
        label: str,
        field_id: str | None = None,
    ) -> None:
        super().__init__(variables, label)
        self.id = constraint_id
        self.forbidden_slots = frozenset(forbidden_slots)
        self.field_id = field_id
        """Si renseigné, l'interdiction ne vaut que sur ce terrain (H4)."""

    def allows(self, var: Variable, value: Value) -> bool:
        slot_id, field_id = value
        if self.field_id is not None and field_id != self.field_id:
            return True
        return slot_id not in self.forbidden_slots


class MinRest(Constraint):
    """H5 : au moins `rest_minutes` entre la fin d'un match d'une équipe et le début du suivant."""

    id = H.MIN_REST

    def __init__(
        self,
        variables: Iterable[Variable],
        slots: Mapping[str, Slot],
        rest_minutes: int,
        label: str,
    ) -> None:
        super().__init__(variables, label)
        self.slots = slots
        self.rest_seconds = rest_minutes * 60

    def _compatible(self, a: str, b: str) -> bool:
        first, second = sorted((self.slots[a], self.slots[b]), key=lambda s: s.starts_at)
        return (second.starts_at - first.ends_at).total_seconds() >= self.rest_seconds

    def is_satisfied(self, assignment: Assignment) -> bool:
        slots = sorted(
            (self.slots[val[0]] for _, val in _assigned(self.variables, assignment)),
            key=lambda s: s.starts_at,
        )
        return all(
            (b.starts_at - a.ends_at).total_seconds() >= self.rest_seconds
            for a, b in pairwise(slots)
        )

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        return all(
            self._compatible(value[0], assignment[v][0])
            for v in self.variables
            if v != var and v in assignment
        )


class MaxMatchesPerDay(Constraint):
    """H6 : une équipe joue au plus `limit` matchs par jour."""

    id = H.MAX_MATCHES_PER_DAY

    def __init__(
        self, variables: Iterable[Variable], slots: Mapping[str, Slot], limit: int, label: str
    ) -> None:
        super().__init__(variables, label)
        self.day_of: dict[str, date] = {sid: s.day for sid, s in slots.items()}
        self.limit = limit

    def is_satisfied(self, assignment: Assignment) -> bool:
        per_day = Counter(self.day_of[val[0]] for _, val in _assigned(self.variables, assignment))
        return all(n <= self.limit for n in per_day.values())

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        day = self.day_of[value[0]]
        same_day = sum(
            1
            for v in self.variables
            if v != var and v in assignment and self.day_of[assignment[v][0]] == day
        )
        return same_day + 1 <= self.limit


class IncompatibleTeams(Constraint):
    """H7 : aucun match de l'équipe A en même temps qu'un *autre* match de l'équipe B.

    La portée est l'union des matchs de A et de B. Le match A contre B lui-même (s'il existe)
    appartient aux deux ensembles et n'entre pas en conflit avec lui-même.
    """

    id = H.INCOMPATIBLE_TEAMS

    def __init__(
        self, matches_a: Iterable[Variable], matches_b: Iterable[Variable], label: str
    ) -> None:
        self.side_a = frozenset(matches_a)
        self.side_b = frozenset(matches_b)
        super().__init__(sorted(self.side_a | self.side_b), label)

    def _conflict(self, m1: Variable, s1: str, m2: Variable, s2: str) -> bool:
        if m1 == m2 or s1 != s2:
            return False
        return (m1 in self.side_a and m2 in self.side_b) or (
            m1 in self.side_b and m2 in self.side_a
        )

    def is_satisfied(self, assignment: Assignment) -> bool:
        placed = _assigned(self.variables, assignment)
        return not any(
            self._conflict(m1, v1[0], m2, v2[0])
            for i, (m1, v1) in enumerate(placed)
            for m2, v2 in placed[i + 1 :]
        )

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        return not any(
            self._conflict(var, value[0], v, assignment[v][0])
            for v in self.variables
            if v in assignment
        )


class SlotQuotaMax(Constraint):
    """H8 : au plus `limit` matchs sur le créneau `slot_id`."""

    id = H.SLOT_QUOTA_MAX

    def __init__(self, variables: Iterable[Variable], slot_id: str, limit: int, label: str) -> None:
        super().__init__(variables, label)
        self.slot_id = slot_id
        self.limit = limit

    def _count(self, assignment: Assignment, exclude: Variable | None = None) -> int:
        return sum(
            1
            for v in self.variables
            if v != exclude and v in assignment and assignment[v][0] == self.slot_id
        )

    def is_satisfied(self, assignment: Assignment) -> bool:
        return self._count(assignment) <= self.limit

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        if value[0] != self.slot_id:
            return True
        return self._count(assignment, exclude=var) + 1 <= self.limit


class SlotQuotaMin(Constraint):
    """H9 : au moins `minimum` matchs sur le créneau `slot_id`.

    Sur une affectation partielle, elle n'est violée que si, même en mettant sur ce créneau
    tous les matchs pas encore placés, on ne peut plus atteindre le minimum.
    """

    id = H.SLOT_QUOTA_MIN

    def __init__(
        self, variables: Iterable[Variable], slot_id: str, minimum: int, label: str
    ) -> None:
        super().__init__(variables, label)
        self.slot_id = slot_id
        self.minimum = minimum

    def is_satisfied(self, assignment: Assignment) -> bool:
        placed = 0
        unassigned = 0
        for v in self.variables:
            if v not in assignment:
                unassigned += 1
            elif assignment[v][0] == self.slot_id:
                placed += 1
        return placed + unassigned >= self.minimum
