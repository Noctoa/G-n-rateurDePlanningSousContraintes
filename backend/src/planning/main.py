"""Point d'entrée de l'API FastAPI."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from planning import __version__

app = FastAPI(title="Planning sous contraintes", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


class Health(BaseModel):
    status: str
    version: str


@api.get("/health")
def health() -> Health:
    return Health(status="ok", version=__version__)


app.include_router(api)
