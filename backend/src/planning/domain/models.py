"""Modèle métier d'un tournoi : ce qu'on planifie et dans quel cadre.

On planifie des **matchs** (qui joue contre qui) sur des couples **(créneau, terrain)**.
Ce module ne contient que des données et leur validation *structurelle* (références
existantes, identifiants uniques, valeurs cohérentes). Savoir si un planning respectant
toutes les règles existe est le travail du solveur, pas de la validation.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Identifiant unique (lettres, chiffres, '-' et '_').",
    ),
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Team(_Model):
    """Une équipe participante."""

    id: Identifier
    name: str = Field(min_length=1)
    pool: str | None = Field(
        default=None,
        description="Poule de l'équipe. Si une équipe a une poule, toutes doivent en avoir une.",
    )
    unavailable_slots: list[str] = Field(
        default_factory=list, description="Créneaux où l'équipe ne peut pas jouer (dur)."
    )
    preferred_slots: list[str] = Field(
        default_factory=list, description="Créneaux où l'équipe préfère jouer (souple)."
    )


class Venue(_Model):
    """Un terrain. Nommé `Venue` côté Python pour ne pas masquer `pydantic.Field`."""

    id: Identifier
    name: str = Field(min_length=1)
    unavailable_slots: list[str] = Field(
        default_factory=list, description="Créneaux où le terrain est indisponible (dur)."
    )


class Slot(_Model):
    """Un créneau horaire : un jour, une heure de début, une durée.

    `min_matches` / `max_matches` sont les quotas du créneau (tous terrains confondus).
    """

    id: Identifier
    day: date
    start: time
    duration_minutes: int = Field(gt=0, le=24 * 60)
    min_matches: int = Field(default=0, ge=0)
    max_matches: int | None = Field(default=None, ge=0)

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.day, self.start)

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    def overlaps(self, other: Slot) -> bool:
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at

    @model_validator(mode="after")
    def _check_quotas(self) -> Self:
        if self.max_matches is not None and self.min_matches > self.max_matches:
            raise ValueError(
                f"créneau {self.id!r} : min_matches ({self.min_matches}) "
                f"> max_matches ({self.max_matches})"
            )
        return self


class Incompatibility(_Model):
    """Deux équipes qui ne doivent jamais jouer en même temps (staff ou joueurs partagés…)."""

    teams: tuple[str, str]
    reason: str | None = None


class TournamentFormat(StrEnum):
    ROUND_ROBIN = "round_robin"
    """Chaque équipe rencontre une fois chaque autre équipe (de sa poule)."""
    DOUBLE_ROUND_ROBIN = "double_round_robin"
    """Aller-retour : chaque rencontre est jouée deux fois, domicile/extérieur inversés."""


class Rules(_Model):
    """Paramètres des contraintes dures globales."""

    min_rest_minutes: int = Field(
        default=0,
        ge=0,
        description="Repos minimum d'une équipe entre la fin d'un match et le début du suivant.",
    )
    max_matches_per_team_per_day: int | None = Field(default=None, ge=1)


class Tournament(_Model):
    """Données d'entrée complètes d'un tournoi à planifier."""

    json_schema: str | None = Field(
        default=None,
        alias="$schema",
        description="Chemin du JSON Schema (autocomplétion dans l'éditeur), ignoré sinon.",
    )
    name: str = Field(min_length=1)
    description: str | None = None
    format: TournamentFormat = TournamentFormat.ROUND_ROBIN
    teams: list[Team] = Field(min_length=2)
    fields: list[Venue] = Field(min_length=1, description="Terrains disponibles.")
    slots: list[Slot] = Field(min_length=1)
    incompatibilities: list[Incompatibility] = Field(default_factory=list)
    rules: Rules = Field(default_factory=Rules)

    # --- accès pratiques -------------------------------------------------------------

    @property
    def pools(self) -> dict[str | None, list[Team]]:
        """Équipes regroupées par poule (clé `None` si pas de poules), dans l'ordre d'entrée."""
        result: dict[str | None, list[Team]] = {}
        for team in self.teams:
            result.setdefault(team.pool, []).append(team)
        return result

    def team(self, team_id: str) -> Team:
        return next(t for t in self.teams if t.id == team_id)

    def slot(self, slot_id: str) -> Slot:
        return next(s for s in self.slots if s.id == slot_id)

    # --- validation structurelle -----------------------------------------------------

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        errors: list[str] = []

        for label, ids in (
            ("d'équipe", [t.id for t in self.teams]),
            ("de terrain", [f.id for f in self.fields]),
            ("de créneau", [s.id for s in self.slots]),
        ):
            duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
            if duplicates:
                errors.append(f"identifiant(s) {label} en double : {', '.join(duplicates)}")

        slot_ids = {s.id for s in self.slots}
        team_ids = {t.id for t in self.teams}

        for team in self.teams:
            for attr in ("unavailable_slots", "preferred_slots"):
                unknown = sorted(set(getattr(team, attr)) - slot_ids)
                if unknown:
                    errors.append(
                        f"équipe {team.id!r} : {attr} référence des créneaux inconnus : "
                        f"{', '.join(unknown)}"
                    )
        for venue in self.fields:
            unknown = sorted(set(venue.unavailable_slots) - slot_ids)
            if unknown:
                errors.append(
                    f"terrain {venue.id!r} : unavailable_slots référence des créneaux inconnus : "
                    f"{', '.join(unknown)}"
                )

        for inc in self.incompatibilities:
            a, b = inc.teams
            if a == b:
                errors.append(f"incompatibilité d'une équipe avec elle-même : {a!r}")
            for t in (a, b):
                if t not in team_ids:
                    errors.append(f"incompatibilité : équipe inconnue {t!r}")

        pools = [t.pool for t in self.teams]
        if any(p is not None for p in pools):
            if any(p is None for p in pools):
                errors.append("poules : certaines équipes ont une poule et d'autres non")
            else:
                small = sorted(p for p, n in Counter(pools).items() if p is not None and n < 2)
                if small:
                    errors.append(f"poule(s) avec moins de 2 équipes : {', '.join(small)}")

        ordered = sorted(self.slots, key=lambda s: s.starts_at)
        for prev, nxt in pairwise(ordered):
            if prev.overlaps(nxt):
                errors.append(f"les créneaux {prev.id!r} et {nxt.id!r} se chevauchent")

        if errors:
            raise ValueError("tournoi invalide :\n- " + "\n- ".join(errors))
        return self


class Match(_Model):
    """Une rencontre à placer. C'est une *variable* du CSP."""

    id: Identifier
    home: str
    away: str
    round: int = Field(ge=1, description="Journée théorique issue de la méthode du cercle.")
    leg: int = Field(default=1, ge=1, le=2, description="1 = aller, 2 = retour.")
    pool: str | None = None

    @property
    def teams(self) -> tuple[str, str]:
        return (self.home, self.away)


class Assignment(_Model):
    """Placement d'un match : la *valeur* affectée à une variable du CSP."""

    match_id: str
    slot_id: str
    field_id: str


class Schedule(_Model):
    """Un planning (complet ou partiel) : la liste des placements."""

    assignments: list[Assignment] = Field(default_factory=list)
