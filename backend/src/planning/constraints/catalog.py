"""Identifiants des contraintes, partagés entre le doc, le solveur, l'API et l'UI.

La source de vérité de la *définition* de chaque contrainte est `docs/constraints.md`.
Un test vérifie que ce fichier et ce catalogue restent synchronisés.
"""

from enum import StrEnum


class HardConstraintId(StrEnum):
    """Contraintes dures : un planning qui en viole une est invalide."""

    FIELD_CAPACITY = "H1"
    TEAM_ONE_MATCH_PER_SLOT = "H2"
    TEAM_UNAVAILABLE = "H3"
    FIELD_UNAVAILABLE = "H4"
    MIN_REST = "H5"
    MAX_MATCHES_PER_DAY = "H6"
    INCOMPATIBLE_TEAMS = "H7"
    SLOT_QUOTA_MAX = "H8"
    SLOT_QUOTA_MIN = "H9"


class SoftConstraintId(StrEnum):
    """Contraintes souples : chaque violation coûte une pénalité pondérée."""

    PREFERRED_SLOTS = "S1"
    FIELD_BALANCE = "S2"
    AVOID_LATE_SLOTS = "S3"
    SPREAD_OVER_DAYS = "S4"
    LONG_WAIT = "S5"


DEFAULT_WEIGHTS: dict[SoftConstraintId, int] = {
    SoftConstraintId.PREFERRED_SLOTS: 3,
    SoftConstraintId.FIELD_BALANCE: 1,
    SoftConstraintId.AVOID_LATE_SLOTS: 2,
    SoftConstraintId.SPREAD_OVER_DAYS: 2,
    SoftConstraintId.LONG_WAIT: 1,
}
