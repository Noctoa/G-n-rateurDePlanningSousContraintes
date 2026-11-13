"""Planifie un tournoi depuis la ligne de commande : planning ou diagnostic d'échec.

uv run python -m planning.solve ../datasets/small.json [--timeout 10]
"""

from __future__ import annotations

import argparse
from itertools import groupby

from planning.checker import validate
from planning.diagnosis import Feasibility
from planning.domain import Tournament, load_tournament
from planning.planner import PlanningReport, plan
from planning.solver import to_schedule

_DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def render(tournament: Tournament, report: PlanningReport) -> str:
    matches, result, diagnosis = report.matches, report.result, report.diagnosis
    lines = [
        f"{tournament.name} — {len(matches)} matchs, "
        f"{len(tournament.slots)} créneaux × {len(tournament.fields)} terrains",
    ]
    if result is not None:
        s = result.stats
        lines.append(
            f"recherche : {result.status}  |  nœuds : {s.nodes}  |  retours arrière : "
            f"{s.backtracks}  |  profondeur max : {s.max_depth}/{len(matches)}  |  "
            f"{s.elapsed_seconds * 1000:.1f} ms"
        )
    lines += ["", f"[{diagnosis.feasibility}] {diagnosis.summary}"]
    for conflict in diagnosis.conflicts:
        ids = ", ".join(sorted({c.id.value for c in conflict.constraints}))
        lines += ["", f"✗ Conflit ({ids}) : {conflict.explanation}"]
        lines += [f"  → {s}" for s in conflict.suggestions]

    if diagnosis.feasibility is not Feasibility.FEASIBLE or result is None:
        return "\n".join(lines)
    assert result.assignment is not None

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
    report = plan(tournament, args.timeout)
    print(render(tournament, report))
    return 0 if report.diagnosis.feasibility is Feasibility.FEASIBLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
