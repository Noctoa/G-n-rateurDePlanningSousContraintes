"""Vérificateur indépendant d'un planning : l'« oracle » des contraintes dures.

Ce module ne réutilise **rien** du solveur (ni `Problem`, ni les classes de
`constraints/hard.py`) : il relit directement le tournoi et le planning et applique les
définitions de `docs/constraints.md`. Si le solveur avait un bug, ce vérificateur doit le
voir. Il sert aussi à valider un planning saisi ou modifié à la main.

Il produit des messages lisibles, destinés à l'utilisateur final.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from planning.constraints.catalog import HardConstraintId as H
from planning.domain.fixtures import generate_matches
from planning.domain.models import Match, Schedule, Slot, Tournament

_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class Violation(BaseModel):
    """Une règle non respectée par le planning."""

    model_config = ConfigDict(frozen=True)

    constraint: H | None
    """Contrainte dure violée, ou `None` pour un planning mal formé (match inconnu, oublié…)."""
    message: str
    matches: list[str] = []
    slots: list[str] = []


def _day(slot: Slot) -> str:
    return f"{_DAYS[slot.day.weekday()]} {slot.day:%d/%m}"


def _match_label(m: Match) -> str:
    return f"{m.id} ({m.home}–{m.away})"


def validate(
    tournament: Tournament,
    schedule: Schedule,
    matches: list[Match] | None = None,
    *,
    require_complete: bool = True,
) -> list[Violation]:
    """Liste toutes les violations du planning (liste vide = planning valide).

    `matches` : matchs attendus (par défaut, ceux générés pour le tournoi).
    `require_complete` : signaler les matchs non placés. À `False`, on vérifie un planning
    partiel tel quel (H9 compte alors uniquement les matchs présents).
    """
    expected = generate_matches(tournament) if matches is None else matches
    by_id = {m.id: m for m in expected}
    slots = {s.id: s for s in tournament.slots}
    teams = {t.id: t for t in tournament.teams}
    fields = {f.id: f for f in tournament.fields}
    out: list[Violation] = []

    # --- Structure : chaque match attendu est placé une fois, sur un créneau et un terrain connus.
    # Un match placé plusieurs fois est signalé puis exclu des vérifications suivantes.
    seen = Counter(a.match_id for a in schedule.assignments)
    for match_id, n in seen.items():
        if match_id in by_id and n > 1:
            out.append(
                Violation(
                    constraint=None,
                    message=f"{_match_label(by_id[match_id])} est placé {n} fois",
                    matches=[match_id],
                )
            )

    placed: dict[str, tuple[Slot, str]] = {}
    for a in schedule.assignments:
        if a.match_id not in by_id:
            out.append(Violation(constraint=None, message=f"match inconnu : {a.match_id}"))
            continue
        if seen[a.match_id] > 1:
            continue
        if a.slot_id not in slots or a.field_id not in fields:
            unknown = a.slot_id if a.slot_id not in slots else a.field_id
            out.append(
                Violation(
                    constraint=None,
                    message=f"{_match_label(by_id[a.match_id])} : créneau ou terrain "
                    f"inconnu ({unknown})",
                    matches=[a.match_id],
                )
            )
            continue
        placed[a.match_id] = (slots[a.slot_id], a.field_id)

    if require_complete:
        missing = [m for m in by_id if m not in seen]
        if missing:
            out.append(
                Violation(
                    constraint=None,
                    message=f"{len(missing)} match(s) non placé(s) : {', '.join(missing)}",
                    matches=missing,
                )
            )

    # --- H1 : un seul match par (créneau, terrain).
    occupants: dict[tuple[str, str], list[str]] = defaultdict(list)
    for m, (slot, field_id) in placed.items():
        occupants[(slot.id, field_id)].append(m)
    for (slot_id, field_id), ms in occupants.items():
        if len(ms) > 1:
            out.append(
                Violation(
                    constraint=H.FIELD_CAPACITY,
                    message=f"{len(ms)} matchs sur le terrain {field_id} au créneau {slot_id} : "
                    + ", ".join(_match_label(by_id[m]) for m in ms),
                    matches=ms,
                    slots=[slot_id],
                )
            )

    # --- H3 / H4 : indisponibilités.
    for m, (slot, field_id) in placed.items():
        for team_id in by_id[m].teams:
            if slot.id in teams[team_id].unavailable_slots:
                out.append(
                    Violation(
                        constraint=H.TEAM_UNAVAILABLE,
                        message=f"{teams[team_id].name} est indisponible au créneau {slot.id}, "
                        f"mais joue {_match_label(by_id[m])}",
                        matches=[m],
                        slots=[slot.id],
                    )
                )
        if slot.id in fields[field_id].unavailable_slots:
            out.append(
                Violation(
                    constraint=H.FIELD_UNAVAILABLE,
                    message=f"le terrain {fields[field_id].name} est indisponible au créneau "
                    f"{slot.id}, mais accueille {_match_label(by_id[m])}",
                    matches=[m],
                    slots=[slot.id],
                )
            )

    # --- Par équipe : H2, H5, H6.
    games: dict[str, list[tuple[str, Slot]]] = defaultdict(list)
    for m, (slot, _) in placed.items():
        for team_id in by_id[m].teams:
            games[team_id].append((m, slot))
    rest = tournament.rules.min_rest_minutes
    limit = tournament.rules.max_matches_per_team_per_day

    for team_id, team_games in games.items():
        name = teams[team_id].name
        per_slot: dict[str, list[str]] = defaultdict(list)
        for m, slot in team_games:
            per_slot[slot.id].append(m)
        for slot_id, ms in per_slot.items():
            if len(ms) > 1:
                out.append(
                    Violation(
                        constraint=H.TEAM_ONE_MATCH_PER_SLOT,
                        message=f"{name} joue {len(ms)} matchs en même temps au créneau "
                        f"{slot_id} : " + ", ".join(_match_label(by_id[m]) for m in ms),
                        matches=ms,
                        slots=[slot_id],
                    )
                )

        ordered = sorted(team_games, key=lambda g: g[1].starts_at)
        if rest > 0:
            for (m1, s1), (m2, s2) in pairwise(ordered):
                gap = int((s2.starts_at - s1.ends_at).total_seconds() // 60)
                if gap < rest:
                    out.append(
                        Violation(
                            constraint=H.MIN_REST,
                            message=f"{name} n'a que {max(gap, 0)} min de repos entre "
                            f"{_match_label(by_id[m1])} ({s1.id}) et "
                            f"{_match_label(by_id[m2])} ({s2.id}), minimum {rest} min",
                            matches=[m1, m2],
                            slots=[s1.id, s2.id],
                        )
                    )

        if limit is not None:
            per_day: dict[str, list[tuple[str, Slot]]] = defaultdict(list)
            for m, slot in ordered:
                per_day[_day(slot)].append((m, slot))
            for day, day_games in per_day.items():
                if len(day_games) > limit:
                    out.append(
                        Violation(
                            constraint=H.MAX_MATCHES_PER_DAY,
                            message=f"{name} joue {len(day_games)} matchs le {day} "
                            f"(maximum {limit})",
                            matches=[m for m, _ in day_games],
                            slots=[s.id for _, s in day_games],
                        )
                    )

    # --- H7 : équipes incompatibles.
    for inc in tournament.incompatibilities:
        team_a, team_b = inc.teams
        reason = f" ({inc.reason})" if inc.reason else ""
        for m1, s1 in games.get(team_a, []):
            for m2, s2 in games.get(team_b, []):
                if m1 != m2 and s1.id == s2.id:
                    out.append(
                        Violation(
                            constraint=H.INCOMPATIBLE_TEAMS,
                            message=f"{teams[team_a].name} et {teams[team_b].name} ne doivent "
                            f"pas jouer en même temps{reason}, or {_match_label(by_id[m1])} et "
                            f"{_match_label(by_id[m2])} sont tous deux au créneau {s1.id}",
                            matches=[m1, m2],
                            slots=[s1.id],
                        )
                    )

    # --- H8 / H9 : quotas par créneau.
    per_slot_count = Counter(slot.id for slot, _ in placed.values())
    for slot in tournament.slots:
        n = per_slot_count[slot.id]
        if slot.max_matches is not None and n > slot.max_matches:
            out.append(
                Violation(
                    constraint=H.SLOT_QUOTA_MAX,
                    message=f"{n} matchs au créneau {slot.id}, maximum {slot.max_matches}",
                    matches=[m for m, (s, _) in placed.items() if s.id == slot.id],
                    slots=[slot.id],
                )
            )
        if n < slot.min_matches:
            out.append(
                Violation(
                    constraint=H.SLOT_QUOTA_MIN,
                    message=f"{n} match(s) au créneau {slot.id}, minimum {slot.min_matches}",
                    slots=[slot.id],
                )
            )

    return out
