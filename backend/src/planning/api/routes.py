"""Routes HTTP de l'API (préfixe `/api`)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import ValidationError

from planning import __version__
from planning.api.jobs import Job, JobManager
from planning.api.schemas import (
    EXAMPLE_TOURNAMENT,
    InputError,
    JobCreated,
    JobView,
    ScheduleRequest,
    SearchStats,
    TournamentSummary,
    ValidationReport,
)
from planning.checker import validate
from planning.diagnosis import precheck
from planning.domain.fixtures import generate_matches
from planning.domain.models import Tournament
from planning.solver.tournament import to_schedule

router = APIRouter(prefix="/api")


def get_jobs(request: Request) -> JobManager:
    jobs: JobManager = request.app.state.jobs
    return jobs


Jobs = Annotated[JobManager, Depends(get_jobs)]

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"description": "Aucun job avec cet identifiant (ou job expiré)."}
}


@router.get("/health", tags=["système"], summary="État du service")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


# --- Tournois ----------------------------------------------------------------------------


# Messages Pydantic les plus fréquents, traduits pour l'utilisateur final.
_MESSAGES_FR: dict[str, str] = {
    "missing": "champ obligatoire manquant",
    "extra_forbidden": "champ inconnu",
    "string_too_short": "ne doit pas être vide",
    "string_type": "doit être une chaîne de caractères",
    "string_pattern_mismatch": "caractères autorisés : lettres, chiffres, '-' et '_'",
    "int_parsing": "doit être un nombre entier",
    "int_type": "doit être un nombre entier",
    "greater_than": "doit être supérieur à {gt}",
    "greater_than_equal": "doit être supérieur ou égal à {ge}",
    "less_than_equal": "doit être inférieur ou égal à {le}",
    "too_short": "au moins {min_length} élément(s) attendu(s)",
    "date_from_datetime_parsing": "date invalide (format AAAA-MM-JJ)",
    "time_parsing": "heure invalide (format HH:MM)",
    "enum": "valeur non autorisée",
}


def _input_errors(exc: ValidationError) -> list[InputError]:
    errors: list[InputError] = []
    for err in exc.errors(include_url=False):
        location = ".".join(str(part) for part in err["loc"])
        template = _MESSAGES_FR.get(err["type"])
        if template is not None:
            message = template.format(**err.get("ctx", {}))
        else:
            message = str(err["msg"]).removeprefix("Value error, ")
        # Les erreurs de cohérence globales arrivent groupées en une liste à puces.
        if message.startswith("tournoi invalide :\n- "):
            errors += [
                InputError(location=location, message=line)
                for line in message.removeprefix("tournoi invalide :\n- ").split("\n- ")
            ]
        else:
            errors.append(InputError(location=location, message=message))
    return errors


@router.post(
    "/tournaments/validate",
    tags=["tournois"],
    summary="Valider un tournoi",
    description="Vérifie le format et la cohérence d'un tournoi **sans le résoudre**. "
    "Répond toujours 200 : `valid` indique le résultat, `errors` liste les problèmes "
    "champ par champ, et `warnings` signale les tournois valides mais prouvés insolubles.",
)
def validate_tournament(
    payload: Annotated[
        dict[str, Any],
        Body(openapi_examples={"mini": {"summary": "Mini tournoi", "value": EXAMPLE_TOURNAMENT}}),
    ],
) -> ValidationReport:
    try:
        tournament = Tournament.model_validate(payload)
    except ValidationError as exc:
        return ValidationReport(valid=False, errors=_input_errors(exc))
    matches = generate_matches(tournament)
    return ValidationReport(
        valid=True,
        summary=TournamentSummary(
            teams=len(tournament.teams),
            fields=len(tournament.fields),
            slots=len(tournament.slots),
            matches=len(matches),
            places=len(tournament.slots) * len(tournament.fields),
        ),
        warnings=precheck(tournament, matches),
    )


# --- Plannings ---------------------------------------------------------------------------


def _view(job: Job) -> JobView:
    report = job.report
    view = JobView(
        job_id=job.id,
        status=job.status,
        tournament_name=job.tournament.name,
        timeout_seconds=job.timeout_seconds,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        matches=report.matches if report else generate_matches(job.tournament),
        error=job.error,
    )
    if report is None:
        return view
    view.diagnosis = report.diagnosis
    if report.result is not None:
        s = report.result.stats
        view.stats = SearchStats(
            nodes=s.nodes,
            backtracks=s.backtracks,
            max_depth=s.max_depth,
            elapsed_ms=round(s.elapsed_seconds * 1000, 3),
        )
        if report.result.assignment is not None:
            view.schedule = to_schedule(report.result.assignment)
            view.violations = validate(job.tournament, view.schedule, report.matches)
    return view


@router.post(
    "/schedules",
    tags=["plannings"],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lancer la génération d'un planning",
    description="Démarre la résolution en tâche de fond et renvoie immédiatement un "
    "`job_id`. Suivre l'avancement avec `GET /api/schedules/{job_id}`.",
)
def create_schedule(request: ScheduleRequest, jobs: Jobs) -> JobCreated:
    job = jobs.submit(request.tournament, request.timeout_seconds)
    return JobCreated(job_id=job.id, status=job.status)


@router.get(
    "/schedules/{job_id}",
    tags=["plannings"],
    summary="Statut et résultat d'une génération",
    description="`pending`/`running` : à réinterroger. `solved` : `schedule` est rempli. "
    "`infeasible` : impossibilité prouvée, voir `diagnosis.conflicts`. `timeout` : rien "
    "trouvé à temps, ce qui ne prouve pas l'impossibilité.",
    responses=_NOT_FOUND,
)
def get_schedule(job_id: str, jobs: Jobs) -> JobView:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job inconnu")
    return _view(job)


@router.delete(
    "/schedules/{job_id}",
    tags=["plannings"],
    summary="Annuler une génération",
    description="Demande l'arrêt du job. Sans effet sur un job déjà terminé. La recherche "
    "s'arrête en quelques millisecondes ; le statut passe alors à `cancelled`.",
    responses=_NOT_FOUND,
)
def cancel_schedule(job_id: str, jobs: Jobs) -> JobView:
    job = jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job inconnu")
    return _view(job)
