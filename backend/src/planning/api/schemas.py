"""Schémas d'entrée/sortie de l'API. Ils forment le contrat OpenAPI utilisé par le front."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from planning.checker import Violation
from planning.diagnosis import Conflict, Diagnosis
from planning.domain.models import Match, Schedule, Tournament

MAX_TIMEOUT_SECONDS = 60.0
"""Plafond côté serveur : aucun job ne peut monopoliser un worker plus longtemps."""

EXAMPLE_TOURNAMENT: dict[str, Any] = {
    "name": "Mini tournoi",
    "format": "round_robin",
    "teams": [
        {"id": "LIO", "name": "Lions", "unavailable_slots": ["J1-09h"]},
        {"id": "AIG", "name": "Aigles"},
        {"id": "REQ", "name": "Requins"},
        {"id": "LOU", "name": "Loups", "preferred_slots": ["J1-11h"]},
    ],
    "fields": [{"id": "T1", "name": "Terrain 1"}, {"id": "T2", "name": "Terrain 2"}],
    "slots": [
        {"id": "J1-09h", "day": "2026-12-05", "start": "09:00", "duration_minutes": 60},
        {"id": "J1-10h", "day": "2026-12-05", "start": "10:00", "duration_minutes": 60},
        {"id": "J1-11h", "day": "2026-12-05", "start": "11:00", "duration_minutes": 60},
        {"id": "J1-14h", "day": "2026-12-05", "start": "14:00", "duration_minutes": 60},
        {"id": "J1-15h", "day": "2026-12-05", "start": "15:00", "duration_minutes": 60},
        {"id": "J1-16h", "day": "2026-12-05", "start": "16:00", "duration_minutes": 60},
    ],
    "incompatibilities": [{"teams": ["LIO", "AIG"], "reason": "même entraîneur"}],
    "rules": {"min_rest_minutes": 0, "max_matches_per_team_per_day": 3},
}


# --- POST /tournaments/validate --------------------------------------------------------


class InputError(BaseModel):
    location: str = Field(description="Chemin du champ fautif, ex. `teams.2.id` (vide = global).")
    message: str


class TournamentSummary(BaseModel):
    teams: int
    fields: int
    slots: int
    matches: int
    places: int = Field(description="Couples (créneau, terrain) : capacité brute.")


class ValidationReport(BaseModel):
    valid: bool = Field(description="Le JSON respecte le format et est cohérent.")
    errors: list[InputError] = []
    summary: TournamentSummary | None = None
    warnings: list[Conflict] = Field(
        default=[],
        description="Pré-vérifications en échec : le tournoi est valide mais **prouvé "
        "insoluble**, inutile de lancer la résolution sans le modifier.",
    )


# --- /schedules --------------------------------------------------------------------------


class ScheduleRequest(BaseModel):
    tournament: Tournament
    timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=MAX_TIMEOUT_SECONDS,
        description=f"Temps maximum de recherche (plafonné à {MAX_TIMEOUT_SECONDS:.0f} s).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"tournament": EXAMPLE_TOURNAMENT, "timeout_seconds": 10}]
        }
    }


class JobStatus(StrEnum):
    PENDING = "pending"
    """En file d'attente."""
    RUNNING = "running"
    SOLVED = "solved"
    """Planning trouvé, toutes les contraintes dures respectées."""
    INFEASIBLE = "infeasible"
    """Impossibilité **prouvée** ; voir `diagnosis.conflicts`."""
    TIMEOUT = "timeout"
    """Rien trouvé dans le temps imparti ; ne prouve pas l'impossibilité."""
    CANCELLED = "cancelled"
    ERROR = "error"
    """Erreur interne inattendue ; voir `error`."""

    @property
    def finished(self) -> bool:
        return self not in (JobStatus.PENDING, JobStatus.RUNNING)


class SearchStats(BaseModel):
    nodes: int = Field(description="Couples (match, placement) essayés.")
    backtracks: int = Field(description="Retours arrière.")
    max_depth: int = Field(description="Plus grand nombre de matchs placés simultanément.")
    elapsed_ms: float


class JobView(BaseModel):
    job_id: str
    status: JobStatus
    tournament_name: str
    timeout_seconds: float
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    matches: list[Match] = Field(description="Matchs à placer (générés depuis le tournoi).")
    schedule: Schedule | None = Field(default=None, description="Présent si `solved`.")
    stats: SearchStats | None = Field(
        default=None, description="Absent si une pré-vérification a conclu sans recherche."
    )
    diagnosis: Diagnosis | None = None
    violations: list[Violation] = Field(
        default=[],
        description="Résultat du vérificateur indépendant sur le planning (vide = valide).",
    )
    error: str | None = None


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus
