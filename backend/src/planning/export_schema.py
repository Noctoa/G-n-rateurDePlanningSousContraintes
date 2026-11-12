"""Exporte le JSON Schema du format d'entrée d'un tournoi.

uv run python -m planning.export_schema ../datasets/tournament.schema.json
"""

import sys
from pathlib import Path

from planning.domain.io import dump_schema


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m planning.export_schema <chemin/du/schema.json>", file=sys.stderr)
        return 2
    Path(args[0]).write_text(dump_schema(), encoding="utf-8")
    print(f"schéma écrit dans {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
