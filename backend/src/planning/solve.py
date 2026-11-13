"""Résout un tournoi depuis la ligne de commande et affiche le planning.

uv run python -m planning.solve ../datasets/small.json [--timeout 10]
"""

from __future__ import annotations

import argparse
from itertools import groupby

from planning.checker import validate
from planning.domain import Match, Tournament, load_tournament
from planning.solver import SolveResult, SolveStatus, solve_tournament, to_schedule

_DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def render(tournament: Tournament, matches: list[Match], result: SolveResult) -> str:
    s = result.stats
    lines = [
        f"{tournament.name} — {len(matches)} matchs, "
        f"{len(tournament.slots)} créneaux × {len(tournament.fields)} terrains",
        f"statut : {result.status}  |  nœuds : {s.nodes}  |  retours arrière : {s.backtracks}"
        f"  |  profondeur max : {s.max_depth}/{len(matches)}  |  {s.elapsed_seconds * 1000:.1f} ms",
    ]
    if result.status is SolveStatus.TIMEOUT:
        lines.append("→ pas de solution trouvée dans le temps imparti (ce n'est pas une preuve).")
    if result.status is SolveStatus.INFEASIBLE:
        lines.append("→ aucune solution n'existe (recherche exhaustive).")
        if result.empty_domains:
            lines.append(f"  matchs impossibles à placer : {', '.join(result.empty_domains)}")
    if result.assignment is None:
        return "\n".join(lines)

    violations = validate(tournament, to_schedule(result.assignment), matches)
    lines.append(f"vérification indépendante : {len(violations)} violation(s)")
    lines += [f"  ✗ {v.constraint or 'planning'} — {v.message}" for v in violations]

    by_id = {m.id: m for m in matches}
    fields = [f.id for f in tournament.fields]
    grid = {(slot, fld): by_id[m] for m, (slot, fld) in result.assignment.items()}
    width = 13
    slots = sorted(tournament.slots, key=lambda x: x.starts_at)
    for day, day_slots in groupby(slots, key=lambda x: x.day):
        lines += ["", f"{_DAYS[day.weekday()]} {day:%d/%m}"]
        lines.append("        " + "".join(f.ljust(width) for f in fields))
        for slot in day_slots:
            cells = []
            for f in fields:
                m = grid.get((slot.id, f))
                cells.append((f"{m.home}–{m.away}" if m else "·").ljust(width))
            lines.append(f"{slot.start:%H:%M}   " + "".join(cells))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tournament", help="fichier JSON du tournoi")
    parser.add_argument("--timeout", type=float, default=10.0, help="en secondes (défaut : 10)")
    args = parser.parse_args(argv)

    tournament = load_tournament(args.tournament)
    matches, result = solve_tournament(tournament, args.timeout)
    print(render(tournament, matches, result))
    return 0 if result.status is SolveStatus.SOLVED else 1


if __name__ == "__main__":
    raise SystemExit(main())
