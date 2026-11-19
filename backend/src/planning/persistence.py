"""Bibliothèque SQLite, avec instantané immuable du tournoi pour chaque génération."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, create_engine, event, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from planning.api.schemas import JobStatus, JobView, SavedSchedule, SavedTournament
from planning.domain.models import Tournament


class _Base(DeclarativeBase):
    pass


class _Tournament(_Base):
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str]
    updated_at: Mapped[str]


class _Schedule(_Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(primary_key=True)
    tournament_id: Mapped[str] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    tournament: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    score: Mapped[float | None]
    solver_parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, index=True)


class TournamentBusyError(Exception):
    """Un tournoi avec une génération active ne peut pas être supprimé."""


class Store:
    def __init__(self, database_path: str | Path) -> None:
        path = str(database_path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            **({"poolclass": StaticPool} if path == ":memory:" else {}),
        )

        @event.listens_for(self._engine, "connect")
        def enable_foreign_keys(connection: Any, _record: Any) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

        self._lock = threading.RLock()
        _Base.metadata.create_all(self._engine)
        self._recover_interrupted()

    def close(self) -> None:
        self._engine.dispose()

    @staticmethod
    def _saved(row: _Tournament, count: int) -> SavedTournament:
        return SavedTournament(
            id=row.id,
            tournament=Tournament.model_validate(row.data),
            created_at=datetime.fromisoformat(row.created_at),
            updated_at=datetime.fromisoformat(row.updated_at),
            schedules_count=count,
        )

    def list_tournaments(self) -> list[SavedTournament]:
        with self._lock, Session(self._engine) as session:
            rows = session.execute(
                select(_Tournament, func.count(_Schedule.id))
                .outerjoin(_Schedule)
                .group_by(_Tournament.id)
                .order_by(_Tournament.updated_at.desc(), _Tournament.id)
            )
            return [self._saved(row, count) for row, count in rows]

    def get_tournament(self, tournament_id: str) -> SavedTournament | None:
        with self._lock, Session(self._engine) as session:
            row = session.get(_Tournament, tournament_id)
            if row is None:
                return None
            count = session.scalar(
                select(func.count())
                .select_from(_Schedule)
                .where(_Schedule.tournament_id == tournament_id)
            )
            return self._saved(row, count or 0)

    def save_tournament(
        self, tournament: Tournament, tournament_id: str | None = None
    ) -> SavedTournament:
        with self._lock, Session(self._engine) as session, session.begin():
            now = datetime.now(UTC).isoformat()
            if tournament_id is None:
                row = _Tournament(id=uuid.uuid4().hex, data={}, created_at=now, updated_at=now)
                session.add(row)
            else:
                existing = session.get(_Tournament, tournament_id)
                if existing is None:
                    raise KeyError(tournament_id)
                row = existing
            row.data = tournament.model_dump(mode="json", by_alias=True)
            row.updated_at = now
            session.flush()
            count = session.scalar(
                select(func.count()).select_from(_Schedule).where(_Schedule.tournament_id == row.id)
            )
            return self._saved(row, count or 0)

    def delete_tournament(self, tournament_id: str) -> bool:
        with self._lock, Session(self._engine) as session, session.begin():
            row = session.get(_Tournament, tournament_id)
            if row is None:
                return False
            for schedule in session.scalars(
                select(_Schedule).where(_Schedule.tournament_id == tournament_id)
            ):
                if not JobStatus(schedule.result["status"]).finished:
                    raise TournamentBusyError(tournament_id)
            session.delete(row)
            return True

    def add_schedule(self, view: JobView, tournament: Tournament) -> None:
        with self._lock, Session(self._engine) as session, session.begin():
            if session.get(_Tournament, view.tournament_id) is None:
                raise KeyError(view.tournament_id)
            session.add(
                _Schedule(
                    id=view.job_id,
                    tournament_id=view.tournament_id,
                    tournament=tournament.model_dump(mode="json", by_alias=True),
                    result=view.model_dump(mode="json"),
                    solver_parameters={
                        "algorithm": "backtracking",
                        "timeout_seconds": view.timeout_seconds,
                    },
                    created_at=view.created_at.isoformat(),
                )
            )

    def update_schedule(self, view: JobView) -> None:
        with self._lock, Session(self._engine) as session, session.begin():
            row = session.get(_Schedule, view.job_id)
            if row is not None:
                row.result = view.model_dump(mode="json")

    @staticmethod
    def _schedule(row: _Schedule) -> SavedSchedule:
        return SavedSchedule(
            **row.result,
            tournament=Tournament.model_validate(row.tournament),
            score=row.score,
            solver_parameters=row.solver_parameters,
        )

    def list_schedules(self, tournament_id: str) -> list[SavedSchedule]:
        with self._lock, Session(self._engine) as session:
            return [
                self._schedule(row)
                for row in session.scalars(
                    select(_Schedule)
                    .where(_Schedule.tournament_id == tournament_id)
                    .order_by(_Schedule.created_at.desc(), _Schedule.id)
                )
            ]

    def get_schedule(self, job_id: str) -> SavedSchedule | None:
        with self._lock, Session(self._engine) as session:
            row = session.get(_Schedule, job_id)
            return self._schedule(row) if row else None

    def _recover_interrupted(self) -> None:
        # Après un arrêt brutal, aucun ancien job ne doit rester « en cours » à jamais.
        with self._lock, Session(self._engine) as session, session.begin():
            for row in session.scalars(select(_Schedule)):
                if not JobStatus(row.result["status"]).finished:
                    row.result = {
                        **row.result,
                        "status": JobStatus.CANCELLED.value,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "error": "Génération interrompue par le redémarrage du serveur.",
                    }
