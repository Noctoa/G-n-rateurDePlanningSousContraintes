"""Point d'entrée de l'API FastAPI.

uv run uvicorn planning.main:app --reload     # doc interactive : /docs
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from planning import __version__
from planning.api.jobs import JobManager
from planning.api.routes import router

DESCRIPTION = """
Génère le planning d'un tournoi (qui joue contre qui, sur quel terrain, à quel créneau)
en respectant des contraintes dures, et explique pourquoi quand c'est impossible.

Flux typique côté front :

1. `POST /api/tournaments/validate` pour afficher les erreurs de saisie ;
2. `POST /api/schedules` → `job_id` ;
3. `GET /api/schedules/{job_id}` toutes les ~300 ms jusqu'à un statut final ;
4. `DELETE /api/schedules/{job_id}` si l'utilisateur annule.

Identifiants des contraintes (`H1`…`H9`, `S1`…`S5`) : voir `docs/constraints.md`.
"""


def create_app(max_workers: int = 2) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.jobs = JobManager(max_workers=max_workers)
        yield
        app.state.jobs.shutdown()

    app = FastAPI(
        title="Planning sous contraintes",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "tournois", "description": "Saisie et validation des tournois."},
            {"name": "plannings", "description": "Génération asynchrone des plannings."},
            {"name": "système"},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
