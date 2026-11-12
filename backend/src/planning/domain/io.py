"""Chargement d'un tournoi depuis JSON et export du JSON Schema du format d'entrée.

Export du schéma en ligne de commande :

    uv run python -m planning.export_schema ../datasets/tournament.schema.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planning.domain.models import Tournament

SCHEMA_ID = "tournament.schema.json"


def load_tournament(path: str | Path) -> Tournament:
    """Lit et valide un tournoi. Lève `pydantic.ValidationError` si le fichier est invalide."""
    return Tournament.model_validate_json(Path(path).read_text(encoding="utf-8"))


def tournament_json_schema() -> dict[str, Any]:
    schema = Tournament.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
    }


def dump_schema() -> str:
    return json.dumps(tournament_json_schema(), indent=2, ensure_ascii=False) + "\n"
