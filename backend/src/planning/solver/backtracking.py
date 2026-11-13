"""Recherche par backtracking chronologique.

Version de base, volontairement sans heuristique : les variables sont prises dans l'ordre
donné, les valeurs dans l'ordre de leur domaine. Les heuristiques (MRV, LCV) et la
propagation (forward checking, AC-3) viendront s'y brancher (#11) et seront comparées à
cette version grâce aux statistiques.

La recherche est itérative (pile d'itérateurs de domaines) plutôt que récursive, pour ne
pas dépendre de la limite de récursion de Python sur les gros tournois.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter

from planning.solver.csp import Problem, Value, Variable


class SolveStatus(StrEnum):
    SOLVED = "solved"
    """Une affectation complète respectant toutes les contraintes dures a été trouvée."""
    INFEASIBLE = "infeasible"
    """Toute la recherche a été parcourue : il est **prouvé** qu'aucune solution n'existe."""
    TIMEOUT = "timeout"
    """Pas de solution trouvée dans le temps imparti. Cela ne prouve **pas** l'impossibilité."""
    CANCELLED = "cancelled"
    """Recherche interrompue à la demande de l'appelant (`should_stop`)."""


@dataclass
class SolveStats:
    nodes: int = 0
    """Nombre de couples (variable, valeur) essayés."""
    backtracks: int = 0
    """Nombre de retours arrière (une variable n'a plus aucune valeur possible)."""
    max_depth: int = 0
    """Plus grand nombre de variables affectées simultanément."""
    elapsed_seconds: float = 0.0


@dataclass
class SolveResult:
    status: SolveStatus
    assignment: dict[Variable, Value] | None
    stats: SolveStats = field(default_factory=SolveStats)
    empty_domains: list[Variable] = field(default_factory=list)
    """Variables dont le domaine est vide dès le départ (insolubilité immédiate)."""


_TIME_CHECK_EVERY = 256

StopCallback = Callable[[], bool]
"""Fonction consultée régulièrement pendant la recherche ; `True` = s'arrêter (annulation)."""


def solve(
    problem: Problem,
    timeout_seconds: float | None = 10.0,
    should_stop: StopCallback | None = None,
) -> SolveResult:
    started = perf_counter()
    deadline = None if timeout_seconds is None else started + timeout_seconds
    stats = SolveStats()

    def finish(status: SolveStatus, assignment: dict[Variable, Value] | None = None) -> SolveResult:
        stats.elapsed_seconds = perf_counter() - started
        return SolveResult(status, assignment, stats)

    domains = problem.node_consistent_domains()
    empty = [v for v in problem.variables if not domains[v]]
    if empty:
        result = finish(SolveStatus.INFEASIBLE)
        result.empty_domains = empty
        return result

    order = problem.variables
    if not order:
        return finish(SolveStatus.SOLVED, {})

    assignment: dict[Variable, Value] = {}
    # stack[i] = itérateur sur les valeurs restant à essayer pour order[i].
    stack: list[Iterator[Value]] = [iter(domains[order[0]])]

    while stack:
        depth = len(stack) - 1
        var = order[depth]

        for value in stack[-1]:
            stats.nodes += 1
            if stats.nodes % _TIME_CHECK_EVERY == 0:
                if should_stop is not None and should_stop():
                    return finish(SolveStatus.CANCELLED)
                if deadline is not None and perf_counter() > deadline:
                    return finish(SolveStatus.TIMEOUT)
            if problem.is_consistent(var, value, assignment):
                assignment[var] = value
                break
        else:
            # Plus aucune valeur pour `var` : on revient sur la variable précédente.
            stack.pop()
            stats.backtracks += 1
            if stack:
                del assignment[order[len(stack) - 1]]
            continue

        stats.max_depth = max(stats.max_depth, len(assignment))
        if len(assignment) == len(order):
            return finish(SolveStatus.SOLVED, dict(assignment))
        stack.append(iter(domains[order[depth + 1]]))

    return finish(SolveStatus.INFEASIBLE)
