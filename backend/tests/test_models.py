import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from planning.constraints.catalog import SoftConstraintId
from planning.domain import Tournament, generate_matches, load_tournament
from planning.domain.io import dump_schema

DATASETS = Path(__file__).resolve().parents[2] / "datasets"


def _base() -> dict[str, Any]:
    return {
        "name": "Test",
        "teams": [
            {"id": "A", "name": "Équipe A"},
            {"id": "B", "name": "Équipe B"},
            {"id": "C", "name": "Équipe C"},
        ],
        "fields": [{"id": "F1", "name": "Terrain 1"}],
        "slots": [
            {"id": "S1", "day": "2026-12-05", "start": "09:00", "duration_minutes": 60},
            {"id": "S2", "day": "2026-12-05", "start": "10:00", "duration_minutes": 60},
        ],
    }


def test_minimal_tournament_is_valid() -> None:
    t = Tournament.model_validate(_base())
    assert t.rules.min_rest_minutes == 0
    assert t.slot("S2").ends_at.hour == 11


def _invalid(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Tournament.model_validate(data)


def test_duplicate_ids_are_rejected() -> None:
    data = _base()
    data["teams"][1]["id"] = "A"
    _invalid(data, "équipe en double : A")


def test_unknown_slot_references_are_rejected() -> None:
    data = _base()
    data["teams"][0]["unavailable_slots"] = ["S9"]
    data["fields"][0]["unavailable_slots"] = ["S8"]
    _invalid(data, "créneaux inconnus : S9")
    _invalid(data, "créneaux inconnus : S8")


def test_overlapping_slots_are_rejected() -> None:
    data = _base()
    data["slots"][1]["start"] = "09:30"
    _invalid(data, "se chevauchent")


def test_back_to_back_slots_do_not_overlap() -> None:
    Tournament.model_validate(_base())  # S1 finit à 10:00, S2 commence à 10:00


def test_invalid_incompatibilities_are_rejected() -> None:
    data = _base()
    data["incompatibilities"] = [{"teams": ["A", "A"]}, {"teams": ["A", "Z"]}]
    _invalid(data, "avec elle-même")
    _invalid(data, "équipe inconnue 'Z'")


def test_pools_must_be_all_or_nothing_and_have_two_teams() -> None:
    data = _base()
    data["teams"][0]["pool"] = "P1"
    _invalid(data, "certaines équipes ont une poule")
    for team, pool in zip(data["teams"], ["P1", "P1", "P2"], strict=True):
        team["pool"] = pool
    _invalid(data, "moins de 2 équipes : P2")


def test_slot_quotas_must_be_consistent() -> None:
    data = _base()
    data["slots"][0] |= {"min_matches": 3, "max_matches": 1}
    _invalid(data, "min_matches")


def test_unknown_keys_are_rejected() -> None:
    data = _base() | {"unknown": 1}
    _invalid(data, "Extra inputs are not permitted")


@pytest.mark.parametrize(
    ("name", "teams", "matches"),
    [("small", 6, 15), ("medium", 16, 56), ("unsolvable", 6, 15)],
)
def test_example_datasets_load(name: str, teams: int, matches: int) -> None:
    t = load_tournament(DATASETS / f"{name}.json")
    assert len(t.teams) == teams
    assert len(generate_matches(t)) == matches


def test_unsolvable_dataset_lacks_capacity() -> None:
    t = load_tournament(DATASETS / "unsolvable.json")
    assert len(generate_matches(t)) > len(t.slots) * len(t.fields)


def test_committed_json_schema_is_up_to_date() -> None:
    committed = json.loads((DATASETS / "tournament.schema.json").read_text(encoding="utf-8"))
    fix = "uv run python -m planning.export_schema ../datasets/tournament.schema.json"
    assert committed == json.loads(dump_schema()), f"Schéma obsolète, relancer : {fix}"


def test_weights_override_defaults_partially() -> None:
    t = Tournament.model_validate(_base() | {"weights": {"S1": 0, "S3": 5}})
    weights = t.effective_weights
    assert weights[SoftConstraintId.PREFERRED_SLOTS] == 0
    assert weights[SoftConstraintId.AVOID_LATE_SLOTS] == 5
    assert weights[SoftConstraintId.FIELD_BALANCE] == 1  # défaut du catalogue
    _invalid(_base() | {"weights": {"S9": 1}}, "S1")
    _invalid(_base() | {"weights": {"S1": -1}}, "greater than or equal to 0")
