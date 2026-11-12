from collections import Counter
from itertools import combinations

import pytest

from planning.domain import (
    Slot,
    Team,
    Tournament,
    TournamentFormat,
    Venue,
    generate_matches,
    round_robin_pairings,
)


def _ids(n: int) -> list[str]:
    return [f"T{i}" for i in range(n)]


@pytest.mark.parametrize("n", range(2, 15))
def test_round_robin_every_pair_meets_exactly_once(n: int) -> None:
    rounds = round_robin_pairings(_ids(n))
    played = Counter(frozenset(p) for day in rounds for p in day)
    expected = {frozenset(p) for p in combinations(_ids(n), 2)}
    assert set(played) == expected
    assert all(count == 1 for count in played.values())


@pytest.mark.parametrize("n", range(2, 15))
def test_round_robin_round_count_and_one_match_per_team_per_round(n: int) -> None:
    rounds = round_robin_pairings(_ids(n))
    assert len(rounds) == (n - 1 if n % 2 == 0 else n)
    for day in rounds:
        teams = [t for pair in day for t in pair]
        assert len(teams) == len(set(teams))


@pytest.mark.parametrize("n", range(2, 15))
def test_round_robin_home_away_is_balanced(n: int) -> None:
    rounds = round_robin_pairings(_ids(n))
    home = Counter(h for day in rounds for h, _ in day)
    away = Counter(a for day in rounds for _, a in day)
    for team in _ids(n):
        assert abs(home[team] - away[team]) <= 1


def test_round_robin_rejects_duplicates_and_handles_trivial_cases() -> None:
    with pytest.raises(ValueError):
        round_robin_pairings(["A", "A"])
    assert round_robin_pairings(["A"]) == []


def _tournament(
    teams: list[Team], fmt: TournamentFormat = TournamentFormat.ROUND_ROBIN
) -> Tournament:
    return Tournament(
        name="test",
        format=fmt,
        teams=teams,
        fields=[Venue(id="F1", name="Terrain")],
        slots=[Slot(id="S1", day="2026-12-05", start="09:00", duration_minutes=60)],  # type: ignore[arg-type]
    )


def test_generate_matches_ids_are_unique_and_sequential() -> None:
    matches = generate_matches(_tournament([Team(id=t, name=t) for t in _ids(6)]))
    assert [m.id for m in matches] == [f"M{i:03d}" for i in range(1, 16)]


def test_double_round_robin_plays_each_fixture_home_and_away() -> None:
    teams = [Team(id=t, name=t) for t in _ids(5)]
    matches = generate_matches(_tournament(teams, TournamentFormat.DOUBLE_ROUND_ROBIN))
    assert len(matches) == 2 * 10
    fixtures = Counter((m.home, m.away) for m in matches)
    assert all(count == 1 for count in fixtures.values())
    for home, away in fixtures:
        assert (away, home) in fixtures
    first_leg_last_round = max(m.round for m in matches if m.leg == 1)
    assert min(m.round for m in matches if m.leg == 2) == first_leg_last_round + 1


def test_pools_only_generate_matches_inside_each_pool() -> None:
    teams = [Team(id=f"A{i}", name=f"A{i}", pool="A") for i in range(4)] + [
        Team(id=f"B{i}", name=f"B{i}", pool="B") for i in range(3)
    ]
    matches = generate_matches(_tournament(teams))
    assert len(matches) == 6 + 3
    for m in matches:
        assert m.pool is not None
        assert m.home.startswith(m.pool)
        assert m.away.startswith(m.pool)
