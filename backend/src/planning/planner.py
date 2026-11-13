"""Point d'entrée « métier » : planifier un tournoi et, en cas d'échec, expliquer pourquoi.

pré-vérifications ──échec──▶ INFEASIBLE (prouvé, sans recherche)
      │ ok
      ▼
backtracking ──solution──▶ FEASIBLE
      │      ──timeout───▶ UNKNOWN (rien n'est prouvé)
      │ épuisé
      ▼
filtre par suppression ──▶ INFEASIBLE + sous-ensemble de contraintes en conflit
"""

from __future__ import annotations

from dataclasses import dataclass

from planning.diagnosis import (
    Diagnosis,
    Feasibility,
    explain_conflict,
    find_conflict,
    precheck,
)
from planning.domain.fixtures import generate_matches
from planning.domain.models import Match, Tournament
from planning.solver.backtracking import SolveResult, SolveStatus, StopCallback, solve
from planning.solver.tournament import build_problem


@dataclass
class PlanningReport:
    matches: list[Match]
    result: SolveResult | None
    """`None` si une pré-vérification a conclu sans lancer la recherche."""
    diagnosis: Diagnosis


def plan(
    tournament: Tournament,
    timeout_seconds: float | None = 10.0,
    conflict_budget_seconds: float = 20.0,
    should_stop: StopCallback | None = None,
) -> PlanningReport:
    """`should_stop` permet d'annuler depuis un autre thread (cf. l'API et ses jobs)."""
    matches = generate_matches(tournament)

    conflicts = precheck(tournament, matches)
    if conflicts:
        return PlanningReport(
            matches,
            None,
            Diagnosis(
                feasibility=Feasibility.INFEASIBLE,
                summary="Aucun planning ne peut respecter toutes les règles obligatoires "
                "(détecté avant la recherche).",
                conflicts=conflicts,
            ),
        )

    problem = build_problem(tournament, matches)
    result = solve(problem, timeout_seconds, should_stop)

    if result.status is SolveStatus.SOLVED:
        diagnosis = Diagnosis(
            feasibility=Feasibility.FEASIBLE,
            summary="Planning trouvé : toutes les règles obligatoires sont respectées.",
        )
    elif result.status is SolveStatus.CANCELLED:
        diagnosis = Diagnosis(
            feasibility=Feasibility.UNKNOWN,
            summary="Recherche annulée avant d'avoir trouvé un planning.",
        )
    elif result.status is SolveStatus.TIMEOUT:
        diagnosis = Diagnosis(
            feasibility=Feasibility.UNKNOWN,
            summary=f"Aucun planning trouvé en {timeout_seconds} s. Cela ne prouve pas qu'il "
            "n'en existe pas : la recherche n'a pas eu le temps d'explorer toutes les "
            "possibilités. Essayez un délai plus long ou assouplissez certaines règles.",
        )
    else:
        core, minimal = find_conflict(
            problem, budget_seconds=conflict_budget_seconds, should_stop=should_stop
        )
        diagnosis = Diagnosis(
            feasibility=Feasibility.INFEASIBLE,
            summary="Aucun planning ne peut respecter toutes les règles obligatoires "
            "(prouvé par une recherche exhaustive).",
            conflicts=[explain_conflict(core, minimal)],
            minimal=minimal,
        )
    return PlanningReport(matches, result, diagnosis)
