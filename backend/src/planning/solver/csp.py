"""Représentation générique d'un CSP : variables, domaines, contraintes.

Rien ici ne connaît le tournoi : une variable est un identifiant (`str`), une valeur est un
couple `(créneau, terrain)`. La traduction tournoi → CSP est dans `solver/tournament.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import ChainMap
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from planning.constraints.catalog import HardConstraintId

Variable = str
Value = tuple[str, str]
"""(slot_id, field_id)"""

Assignment = Mapping[Variable, Value]
"""Affectation, éventuellement partielle : seules les variables déjà placées y figurent."""


class Constraint(ABC):
    """Une contrainte dure portant sur un sous-ensemble de variables (sa *portée*).

    Contrat de `is_satisfied` sur une affectation **partielle** : renvoyer `False` seulement si
    la contrainte est déjà violée de façon certaine (aucun prolongement ne peut la réparer).
    L'affectation peut contenir des variables hors de la portée : elles sont ignorées.
    """

    id: HardConstraintId

    def __init__(self, variables: Iterable[Variable], label: str) -> None:
        self.variables: tuple[Variable, ...] = tuple(variables)
        self.label = label

    @abstractmethod
    def is_satisfied(self, assignment: Assignment) -> bool: ...

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        """La contrainte reste-t-elle satisfaite si l'on ajoute `var = value` ?

        Version par défaut : on re-vérifie la portée entière sur une vue de l'affectation
        (sans la copier). Les sous-classes peuvent la spécialiser pour aller plus vite.
        """
        return self.is_satisfied(ChainMap({var: value}, dict(assignment)))

    def __repr__(self) -> str:
        return f"<{self.id} {self.label}>"


class UnaryConstraint(Constraint):
    """Contrainte qui ne regarde qu'une variable à la fois.

    Elle est appliquée une seule fois avant la recherche en retirant les valeurs interdites
    des domaines (« cohérence de nœud »), au lieu d'être re-testée à chaque nœud.
    """

    @abstractmethod
    def allows(self, var: Variable, value: Value) -> bool: ...

    def is_satisfied(self, assignment: Assignment) -> bool:
        return all(self.allows(v, assignment[v]) for v in self.variables if v in assignment)


@dataclass
class Problem:
    variables: list[Variable]
    domains: dict[Variable, list[Value]]
    constraints: list[Constraint]
    constraints_of: dict[Variable, list[Constraint]] = field(init=False)

    def __post_init__(self) -> None:
        missing = [v for v in self.variables if v not in self.domains]
        if missing:
            raise ValueError(f"variables sans domaine : {missing}")
        scope = set(self.variables)
        self.constraints_of = {v: [] for v in self.variables}
        for c in self.constraints:
            for v in c.variables:
                if v not in scope:
                    raise ValueError(f"{c!r} porte sur une variable inconnue : {v!r}")
                self.constraints_of[v].append(c)

    def node_consistent_domains(self) -> dict[Variable, list[Value]]:
        """Domaines privés des valeurs interdites par les contraintes unaires."""
        unary = [c for c in self.constraints if isinstance(c, UnaryConstraint)]
        return {
            var: [
                val for val in dom if all(c.allows(var, val) for c in unary if var in c.variables)
            ]
            for var, dom in self.domains.items()
        }

    def is_consistent(self, var: Variable, value: Value, assignment: Assignment) -> bool:
        """Teste uniquement les contraintes n-aires qui portent sur `var` (vérif. incrémentale)."""
        return all(
            c.is_consistent(var, value, assignment)
            for c in self.constraints_of[var]
            if not isinstance(c, UnaryConstraint)
        )
