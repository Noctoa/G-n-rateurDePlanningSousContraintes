"""Exécution des résolutions en tâche de fond.

Chaque demande de planning devient un *job* exécuté dans un pool de threads : la requête
HTTP répond tout de suite avec un `job_id`, et le front interroge ensuite son statut.
L'annulation est coopérative : le solveur consulte régulièrement l'`Event` du job.

Les états sont enregistrés dans SQLite à chaque transition. Le cache mémoire est borné ;
les résultats restent consultables dans la base après éviction ou redémarrage.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from planning.api.schemas import JobStatus, JobView, SearchStats
from planning.checker import validate
from planning.diagnosis import Feasibility
from planning.domain.fixtures import generate_matches
from planning.domain.models import Tournament
from planning.persistence import Store
from planning.planner import PlanningReport, plan
from planning.solver.backtracking import SolveStatus
from planning.solver.tournament import to_schedule

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Job:
    id: str
    tournament: Tournament
    tournament_id: str
    timeout_seconds: float
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: PlanningReport | None = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future[None] | None = None


def _status_of(report: PlanningReport) -> JobStatus:
    if report.result is not None and report.result.status is SolveStatus.CANCELLED:
        return JobStatus.CANCELLED
    return {
        Feasibility.FEASIBLE: JobStatus.SOLVED,
        Feasibility.INFEASIBLE: JobStatus.INFEASIBLE,
        Feasibility.UNKNOWN: JobStatus.TIMEOUT,
    }[report.diagnosis.feasibility]


def job_view(job: Job) -> JobView:
    report = job.report
    view = JobView(
        job_id=job.id,
        tournament_id=job.tournament_id,
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


class JobManager:
    def __init__(self, store: Store, max_workers: int = 2, max_jobs: int = 200) -> None:
        self._store = store
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="solver")
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def submit(
        self, tournament: Tournament, timeout_seconds: float, tournament_id: str | None = None
    ) -> Job:
        saved = self._store.save_tournament(tournament, tournament_id)
        job = Job(
            id=uuid.uuid4().hex,
            tournament=tournament,
            tournament_id=saved.id,
            timeout_seconds=timeout_seconds,
        )
        with self._lock:
            self._store.add_schedule(job_view(job), tournament)
            self._jobs[job.id] = job
            self._forget_old_jobs()
        job.future = self._executor.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def view(self, job_id: str) -> JobView | None:
        # Lire l'état persisté garantit que « terminé » implique « sauvegardé ».
        return self._store.get_schedule(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel_event.set()
        with self._lock:
            # Pas encore démarré : on le retire de la file et on conclut tout de suite.
            if job.status is JobStatus.PENDING and job.future is not None and job.future.cancel():
                job.status = JobStatus.CANCELLED
                job.finished_at = _now()
                self._store.update_schedule(job_view(job))
        return job

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            self.cancel(job.id)
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _forget_old_jobs(self) -> None:
        finished = [j.id for j in self._jobs.values() if j.status.finished]
        excess = len(self._jobs) - self._max_jobs
        for job_id in finished[: max(excess, 0)]:
            del self._jobs[job_id]

    def _run(self, job: Job) -> None:
        with self._lock:
            if job.cancel_event.is_set():
                job.status = JobStatus.CANCELLED
                job.finished_at = _now()
                self._store.update_schedule(job_view(job))
                return
            job.status = JobStatus.RUNNING
            job.started_at = _now()
            self._store.update_schedule(job_view(job))
        try:
            report = plan(
                job.tournament,
                timeout_seconds=job.timeout_seconds,
                conflict_budget_seconds=job.timeout_seconds,
                should_stop=job.cancel_event.is_set,
            )
        except Exception as exc:  # pragma: no cover - filet de sécurité
            logger.exception("job %s en erreur", job.id)
            with self._lock:
                job.status = JobStatus.ERROR
                job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = _now()
                self._store.update_schedule(job_view(job))
            return
        with self._lock:
            job.report = report
            job.status = _status_of(report)
            job.finished_at = _now()
            self._store.update_schedule(job_view(job))
