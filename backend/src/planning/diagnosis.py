"""Détection et explication des tournois insolubles.

Deux niveaux, du moins cher au plus cher :

1. **Pré-vérifications** (`precheck`) : des conditions *nécessaires* simples (capacité,
   créneaux disponibles par équipe…). Si l'une échoue, le tournoi est prouvé insoluble sans
   lancer la recherche, et on sait exactement pourquoi.
2. **Filtre par suppression** (`find_conflict`) : quand la recherche prouve l'impossibilité
   sans qu'une pré-vérification l'ait vue, on retire les contraintes une par une et on
   relance. Celles dont le retrait rend le problème soluble sont indispensables au conflit :
   on obtient un sous-ensemble minimal de contraintes incompatibles entre elles.

On distingue toujours « prouvé impossible » (`INFEASIBLE`) de « pas trouvé à temps »
(`UNKNOWN`), qui ne prouve rien.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum
from math import ceil
from time import perf_counter
from typing import Literal

from pydantic import BaseModel

from planning.constraints.catalog import HardConstraintId as H
from planning.domain.models import Match, Slot, Team, Tournament
from planning.solver.backtracking import SolveStatus, StopCallback, solve
from planning.solver.csp import Constraint, Problem


class Feasibility(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    """Impossibilité **prouvée** (pré-vérification ou recherche exhaustive)."""
    UNKNOWN = "unknown"
    """Ni solution trouvée ni impossibilité prouvée dans le temps imparti."""


class ConstraintRef(BaseModel):
    id: H
    label: str


class Conflict(BaseModel):
    source: Literal["precheck", "search"]
    constraints: list[ConstraintRef]
    explanation: str
    suggestions: list[str]


class Diagnosis(BaseModel):
    feasibility: Feasibility
    summary: str
    conflicts: list[Conflict] = []
    minimal: bool | None = None
    """Pour un conflit trouvé par la recherche : `True` si chaque contrainte listée est
    indispensable (aucun timeout pendant le filtre). `None` si non applicable."""


# --- Suggestions génériques par type de contrainte ---------------------------------------

SUGGESTIONS: dict[H, str] = {
    H.FIELD_CAPACITY: "ajouter un terrain ou des créneaux",
    H.TEAM_ONE_MATCH_PER_SLOT: "ajouter des créneaux",
    H.TEAM_UNAVAILABLE: "lever certaines indisponibilités des équipes concernées",
    H.FIELD_UNAVAILABLE: "lever certaines indisponibilités des terrains",
    H.MIN_REST: "réduire le temps de repos minimum",
    H.MAX_MATCHES_PER_DAY: "autoriser plus de matchs par équipe et par jour",
    H.INCOMPATIBLE_TEAMS: "retirer ou revoir l'incompatibilité entre les équipes concernées",
    H.SLOT_QUOTA_MAX: "augmenter le nombre maximum de matchs des créneaux concernés",
    H.SLOT_QUOTA_MIN: "baisser le nombre minimum de matchs des créneaux concernés",
}


def _suggestions(ids: Iterable[H]) -> list[str]:
    seen: list[str] = []
    for i in ids:
        if SUGGESTIONS[i] not in seen:
            seen.append(SUGGESTIONS[i])
    return seen


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n <= 1 else plural or word + 's'}"


# --- 1. Pré-vérifications ----------------------------------------------------------------


def _places(tournament: Tournament) -> dict[str, int]:
    """Nombre de matchs qu'un créneau peut accueillir (terrains dispo, plafonné par H8)."""
    result: dict[str, int] = {}
    for slot in tournament.slots:
        free_fields = sum(1 for f in tournament.fields if slot.id not in f.unavailable_slots)
        cap = free_fields if slot.max_matches is None else min(free_fields, slot.max_matches)
        result[slot.id] = cap
    return result


def _max_games_per_day(day_slots: list[Slot], rest_minutes: int) -> int:
    """Nombre max de créneaux choisissables dans la journée en respectant le repos.

    Glouton « fin au plus tôt » : optimal pour sélectionner des intervalles disjoints
    (ici chaque créneau prolongé de la durée de repos).
    """
    count = 0
    last_end = None
    for slot in sorted(day_slots, key=lambda s: s.ends_at):
        if last_end is None or (slot.starts_at - last_end).total_seconds() >= rest_minutes * 60:
            count += 1
            last_end = slot.ends_at
    return count


def _check_capacity(t: Tournament, matches: list[Match], places: dict[str, int]) -> list[Conflict]:
    total = sum(places.values())
    if len(matches) <= total:
        return []
    deficit = len(matches) - total
    raw = len(t.slots) * len(t.fields)
    refs = [ConstraintRef(id=H.FIELD_CAPACITY, label="un match par terrain et créneau")]
    detail = f"{len(t.slots)} créneaux × {len(t.fields)} terrains"
    if total < raw:
        detail += f", dont {raw - total} indisponibles ou au-delà des quotas"
        if any(f.unavailable_slots for f in t.fields):
            refs.append(ConstraintRef(id=H.FIELD_UNAVAILABLE, label="terrains indisponibles"))
        if any(s.max_matches is not None and s.max_matches < len(t.fields) for s in t.slots):
            refs.append(ConstraintRef(id=H.SLOT_QUOTA_MAX, label="quotas maximum des créneaux"))
    suggestions = [
        f"ajouter au moins {_plural(ceil(deficit / len(t.fields)), 'créneau', 'créneaux')} "
        f"(avec {_plural(len(t.fields), 'terrain')})",
        f"ou ajouter au moins {_plural(ceil(deficit / len(t.slots)), 'terrain')}",
        "ou réduire le nombre de matchs (poules plus petites, aller simple)",
    ]
    return [
        Conflict(
            source="precheck",
            constraints=refs,
            explanation=f"Il y a {len(matches)} matchs à placer mais seulement {total} places "
            f"disponibles ({detail}) : il manque {_plural(deficit, 'place')}.",
            suggestions=suggestions,
        )
    ]


def _team_matches(matches: list[Match]) -> dict[str, list[Match]]:
    by_team: dict[str, list[Match]] = defaultdict(list)
    for m in matches:
        for team_id in m.teams:
            by_team[team_id].append(m)
    return by_team


def _usable_slots(team: Team, t: Tournament, places: dict[str, int]) -> list[Slot]:
    return [s for s in t.slots if s.id not in team.unavailable_slots and places[s.id] > 0]


def _check_match_domains(
    t: Tournament, matches: list[Match], places: dict[str, int]
) -> list[Conflict]:
    conflicts = []
    for m in matches:
        home, away = t.team(m.home), t.team(m.away)
        common = set(s.id for s in _usable_slots(home, t, places)) & set(
            s.id for s in _usable_slots(away, t, places)
        )
        if common:
            continue
        refs = [
            ConstraintRef(id=H.TEAM_UNAVAILABLE, label=f"indisponibilités de {home.name}"),
            ConstraintRef(id=H.TEAM_UNAVAILABLE, label=f"indisponibilités de {away.name}"),
        ]
        if any(p == 0 for p in places.values()):
            refs.append(ConstraintRef(id=H.FIELD_UNAVAILABLE, label="terrains indisponibles"))
        conflicts.append(
            Conflict(
                source="precheck",
                constraints=refs,
                explanation=f"Le match {m.id} ({home.name} – {away.name}) ne peut se jouer sur "
                "aucun créneau : il n'existe aucun créneau où les deux équipes sont disponibles "
                "et un terrain est libre.",
                suggestions=[
                    f"trouver un créneau commun à {home.name} et {away.name}",
                    *_suggestions([H.FIELD_UNAVAILABLE] if len(refs) > 2 else []),
                ],
            )
        )
    return conflicts


def _check_team_capacity(
    t: Tournament, matches: list[Match], places: dict[str, int]
) -> list[Conflict]:
    conflicts = []
    rest = t.rules.min_rest_minutes
    limit = t.rules.max_matches_per_team_per_day
    for team_id, own in _team_matches(matches).items():
        team = t.team(team_id)
        usable = _usable_slots(team, t, places)
        per_day: dict[object, list[Slot]] = defaultdict(list)
        for s in usable:
            per_day[s.day].append(s)

        capacity = 0
        rest_binds = limit_binds = False
        for day_slots in per_day.values():
            with_rest = _max_games_per_day(day_slots, rest)
            rest_binds |= with_rest < len(day_slots)
            day_cap = with_rest if limit is None else min(with_rest, limit)
            limit_binds |= day_cap < with_rest
            capacity += day_cap
        if len(own) <= capacity:
            continue

        refs = [
            ConstraintRef(id=H.TEAM_ONE_MATCH_PER_SLOT, label=f"{team.name} : un match à la fois")
        ]
        reasons = [
            f"{_plural(len(usable), 'créneau jouable', 'créneaux jouables')} sur {len(t.slots)}"
        ]
        if team.unavailable_slots:
            refs.append(
                ConstraintRef(id=H.TEAM_UNAVAILABLE, label=f"indisponibilités de {team.name}")
            )
            n_unavailable = len(team.unavailable_slots)
            reasons.append(f"indisponible sur {_plural(n_unavailable, 'créneau', 'créneaux')}")
        if rest_binds:
            refs.append(ConstraintRef(id=H.MIN_REST, label=f"{team.name} : repos de {rest} min"))
            reasons.append(f"{rest} min de repos entre deux matchs")
        if limit_binds:
            refs.append(
                ConstraintRef(
                    id=H.MAX_MATCHES_PER_DAY, label=f"{team.name} : {limit} matchs/jour max"
                )
            )
            reasons.append(f"{_plural(limit or 0, 'match')} par jour au maximum")
        conflicts.append(
            Conflict(
                source="precheck",
                constraints=refs,
                explanation=f"{team.name} doit jouer {len(own)} matchs mais ne peut en jouer "
                f"que {capacity} au plus ({', '.join(reasons)}).",
                suggestions=_suggestions(r.id for r in refs[1:]) or _suggestions([refs[0].id]),
            )
        )
    return conflicts


def _check_incompatibilities(
    t: Tournament, matches: list[Match], places: dict[str, int]
) -> list[Conflict]:
    conflicts = []
    by_team = _team_matches(matches)
    usable = sum(1 for p in places.values() if p > 0)
    for inc in t.incompatibilities:
        a, b = inc.teams
        involved = {m.id for m in by_team[a]} | {m.id for m in by_team[b]}
        if len(involved) <= usable:
            continue
        name_a, name_b = t.team(a).name, t.team(b).name
        conflicts.append(
            Conflict(
                source="precheck",
                constraints=[
                    ConstraintRef(
                        id=H.INCOMPATIBLE_TEAMS, label=f"{name_a} et {name_b} jamais en même temps"
                    ),
                    ConstraintRef(id=H.TEAM_ONE_MATCH_PER_SLOT, label="un match à la fois"),
                ],
                explanation=f"{name_a} et {name_b} ne doivent jamais jouer en même temps : leurs "
                f"{len(involved)} matchs demandent {len(involved)} créneaux différents, "
                f"or seuls {usable} créneaux sont utilisables.",
                suggestions=_suggestions([H.INCOMPATIBLE_TEAMS, H.TEAM_ONE_MATCH_PER_SLOT]),
            )
        )
    return conflicts


def _check_quotas_min(
    t: Tournament, matches: list[Match], places: dict[str, int]
) -> list[Conflict]:
    conflicts = []
    total_min = sum(s.min_matches for s in t.slots)
    if total_min > len(matches):
        conflicts.append(
            Conflict(
                source="precheck",
                constraints=[ConstraintRef(id=H.SLOT_QUOTA_MIN, label="quotas minimum")],
                explanation=f"La somme des minimums par créneau ({total_min}) dépasse le nombre "
                f"total de matchs ({len(matches)}).",
                suggestions=_suggestions([H.SLOT_QUOTA_MIN]),
            )
        )
    for s in t.slots:
        free_teams = sum(1 for team in t.teams if s.id not in team.unavailable_slots)
        ceiling = min(places[s.id], free_teams // 2)
        if s.min_matches <= ceiling:
            continue
        refs = [ConstraintRef(id=H.SLOT_QUOTA_MIN, label=f"{s.id} : {s.min_matches} min")]
        why: list[str] = []
        if places[s.id] < s.min_matches:
            refs.append(ConstraintRef(id=H.FIELD_CAPACITY, label="un match par terrain"))
            why.append(_plural(places[s.id], "terrain utilisable", "terrains utilisables"))
        if free_teams // 2 < s.min_matches:
            refs.append(ConstraintRef(id=H.TEAM_ONE_MATCH_PER_SLOT, label="un match à la fois"))
            why.append(f"{free_teams} équipes disponibles, donc {free_teams // 2} matchs au plus")
        conflicts.append(
            Conflict(
                source="precheck",
                constraints=refs,
                explanation=f"Le créneau {s.id} exige au moins {s.min_matches} matchs, mais ne "
                f"peut en accueillir que {ceiling} ({', '.join(why)}).",
                suggestions=_suggestions(r.id for r in refs),
            )
        )
    return conflicts


def precheck(tournament: Tournament, matches: list[Match]) -> list[Conflict]:
    """Conditions nécessaires d'existence d'une solution. Liste vide = rien d'évident."""
    places = _places(tournament)
    return [
        *_check_capacity(tournament, matches, places),
        *_check_match_domains(tournament, matches, places),
        *_check_team_capacity(tournament, matches, places),
        *_check_incompatibilities(tournament, matches, places),
        *_check_quotas_min(tournament, matches, places),
    ]


# --- 2. Filtre par suppression -----------------------------------------------------------


def find_conflict(
    problem: Problem,
    timeout_per_solve: float = 1.0,
    budget_seconds: float = 20.0,
    should_stop: StopCallback | None = None,
) -> tuple[list[Constraint], bool]:
    """Sous-ensemble de contraintes qui, ensemble, rendent le problème insoluble.

    Suppose que `problem` est prouvé insoluble. Pour chaque contrainte : on la retire et on
    relance. Si c'est toujours insoluble, elle ne participe pas au conflit et on la laisse
    de côté ; sinon on la garde. Renvoie `(conflit, minimal)` : `minimal` est faux si un
    timeout ou l'épuisement du budget a empêché de trancher pour au moins une contrainte.
    """
    deadline = perf_counter() + budget_seconds
    core = list(problem.constraints)
    minimal = True
    for candidate in list(core):
        if perf_counter() > deadline or (should_stop is not None and should_stop()):
            return core, False
        trial = [c for c in core if c is not candidate]
        result = solve(
            Problem(problem.variables, problem.domains, trial), timeout_per_solve, should_stop
        )
        if result.status is SolveStatus.INFEASIBLE:
            core = trial
        elif result.status is not SolveStatus.SOLVED:
            minimal = False
    return core, minimal


def explain_conflict(core: list[Constraint], minimal: bool) -> Conflict:
    refs = [ConstraintRef(id=c.id, label=c.label) for c in core]
    names = [f"« {c.label} » ({c.id})" for c in core]
    if len(names) == 1:
        explanation = f"La règle {names[0]} ne peut pas être respectée."
    elif len(names) == 2:
        explanation = (
            f"Les règles {names[0]} et {names[1]} sont incompatibles : "
            "aucun planning ne peut respecter les deux à la fois."
        )
    else:
        explanation = (
            f"Ces {len(names)} règles ne peuvent pas être respectées toutes ensemble : "
            + ", ".join(names)
            + "."
        )
    if minimal:
        explanation += " Assouplir n'importe laquelle d'entre elles suffit à lever ce conflit."
    else:
        explanation += (
            " (Analyse incomplète faute de temps : la liste peut contenir des règles en trop.)"
        )
    return Conflict(
        source="search",
        constraints=refs,
        explanation=explanation,
        suggestions=_suggestions(c.id for c in core),
    )
