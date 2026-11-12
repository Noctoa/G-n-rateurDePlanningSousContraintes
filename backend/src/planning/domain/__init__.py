"""Modèle métier du tournoi."""

from planning.domain.fixtures import generate_matches, round_robin_pairings
from planning.domain.io import load_tournament, tournament_json_schema
from planning.domain.models import (
    Assignment,
    Incompatibility,
    Match,
    Rules,
    Schedule,
    Slot,
    Team,
    Tournament,
    TournamentFormat,
    Venue,
)

__all__ = [
    "Assignment",
    "Incompatibility",
    "Match",
    "Rules",
    "Schedule",
    "Slot",
    "Team",
    "Tournament",
    "TournamentFormat",
    "Venue",
    "generate_matches",
    "load_tournament",
    "round_robin_pairings",
    "tournament_json_schema",
]
