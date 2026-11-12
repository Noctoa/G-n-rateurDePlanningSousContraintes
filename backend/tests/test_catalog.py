import re
from pathlib import Path

from planning.constraints import DEFAULT_WEIGHTS, HardConstraintId, SoftConstraintId

DOC = (Path(__file__).resolve().parents[2] / "docs" / "constraints.md").read_text(encoding="utf-8")


def _doc_headings() -> dict[str, str]:
    """`### H1 — FIELD_CAPACITY : …` → {"H1": "FIELD_CAPACITY"}."""
    return dict(re.findall(r"^### ([HS]\d+) — ([A-Z_]+)", DOC, flags=re.MULTILINE))


def test_every_constraint_is_documented_with_the_same_name() -> None:
    expected = {c.value: c.name for c in [*HardConstraintId, *SoftConstraintId]}
    assert _doc_headings() == expected


def test_default_weights_match_the_doc_table() -> None:
    rows = dict(re.findall(r"^\| (S\d+) \| [A-Z_]+ \| (\d+) \|$", DOC, flags=re.MULTILINE))
    assert {c.value: str(w) for c, w in DEFAULT_WEIGHTS.items()} == rows
    assert set(DEFAULT_WEIGHTS) == set(SoftConstraintId)
