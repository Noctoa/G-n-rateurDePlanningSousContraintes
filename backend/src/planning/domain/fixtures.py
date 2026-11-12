"""Génération des rencontres à planifier (méthode du cercle).

Méthode du cercle (round-robin de Berger) : pour n équipes (n pair, sinon on ajoute une
équipe fictive « exempt »), on fixe la première équipe et on fait tourner les autres d'un
cran à chaque journée. On obtient n-1 journées où chaque équipe joue au plus une fois, et
chaque paire se rencontre exactement une fois. Le choix de qui reçoit est fait ensuite,
globalement, pour équilibrer domicile et extérieur.
"""

from __future__ import annotations

from collections.abc import Sequence

from planning.domain.models import Match, Tournament, TournamentFormat

_BYE = None


def round_robin_pairings(team_ids: Sequence[str]) -> list[list[tuple[str, str]]]:
    """Journées d'un round-robin simple, chaque rencontre orientée (domicile, extérieur).

    Les équipes exemptes (nombre impair) n'apparaissent simplement pas dans la journée.
    L'écart domicile/extérieur de chaque équipe est d'au plus 1 (voir `_balanced_home`).
    """
    if len(set(team_ids)) != len(team_ids):
        raise ValueError("identifiants d'équipes en double")
    if len(team_ids) < 2:
        return []

    circle: list[str | None] = list(team_ids)
    if len(circle) % 2:
        circle.append(_BYE)
    n = len(circle)

    rounds: list[list[tuple[str, str]]] = []
    for _ in range(n - 1):
        pairs: list[tuple[str, str]] = []
        for i in range(n // 2):
            a, b = circle[i], circle[n - 1 - i]
            if a is not _BYE and b is not _BYE:
                pairs.append((a, b))
        rounds.append(pairs)
        # Rotation : on garde circle[0] fixe et on décale le reste d'un cran.
        circle = [circle[0], circle[-1], *circle[1:-1]]

    oriented = _balanced_home([p for day in rounds for p in day], rounds[0])
    return [[p if p in oriented else (p[1], p[0]) for p in day] for day in rounds]


def _balanced_home(
    pairs: list[tuple[str, str]], matching: list[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Choisit qui reçoit pour chaque rencontre, avec |domicile - extérieur| <= 1 pour tous.

    Graphe complet K_n : si n est impair, tous les degrés sont pairs ; si n est pair, on
    retire un couplage parfait (la 1re journée) et les degrés restants deviennent pairs.
    Un graphe de degrés pairs admet un circuit eulérien par composante ; orienter chaque
    arête dans le sens du parcours donne exactement autant d'entrées que de sorties en
    chaque sommet. Les arêtes du couplage retiré ajoutent au plus ±1.
    """
    matched = {frozenset(p) for p in matching} if len(matching) * 2 == _team_count(pairs) else set()
    adjacency: dict[str, list[str]] = {}
    for a, b in pairs:
        if frozenset((a, b)) in matched:
            continue
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    used: set[frozenset[str]] = set()
    oriented: set[tuple[str, str]] = {p for p in pairs if frozenset(p) in matched}
    for start in adjacency:
        # Hierholzer itératif : on suit les arêtes non utilisées et on oriente au passage.
        stack = [start]
        while stack:
            node = stack[-1]
            neighbours = adjacency[node]
            while neighbours and frozenset((node, neighbours[-1])) in used:
                neighbours.pop()
            if neighbours:
                nxt = neighbours.pop()
                used.add(frozenset((node, nxt)))
                oriented.add((node, nxt))
                stack.append(nxt)
            else:
                stack.pop()
    return oriented


def _team_count(pairs: list[tuple[str, str]]) -> int:
    return len({t for p in pairs for t in p})


def generate_matches(tournament: Tournament) -> list[Match]:
    """Liste ordonnée des matchs à placer pour le tournoi (toutes poules confondues).

    Identifiants stables : `M001`, `M002`… dans l'ordre (poule, aller/retour, journée).
    """
    matches: list[Match] = []
    double = tournament.format is TournamentFormat.DOUBLE_ROUND_ROBIN

    for pool, teams in tournament.pools.items():
        rounds = round_robin_pairings([t.id for t in teams])
        legs = [(1, rounds)]
        if double:
            # Retour : mêmes journées, domicile/extérieur inversés, numérotées à la suite.
            legs.append((2, [[(away, home) for home, away in day] for day in rounds]))
        for leg, leg_rounds in legs:
            offset = (leg - 1) * len(rounds)
            for r, day in enumerate(leg_rounds, start=1):
                for home, away in day:
                    matches.append(
                        Match(
                            id=f"M{len(matches) + 1:03d}",
                            home=home,
                            away=away,
                            round=offset + r,
                            leg=leg,
                            pool=pool,
                        )
                    )
    return matches
