# Datasets

Tournois d'exemple au format JSON, validés par [`tournament.schema.json`](tournament.schema.json)
(généré depuis le modèle Pydantic : `cd backend && uv run python -m planning.export_schema ../datasets/tournament.schema.json`).

| Fichier | Équipes | Matchs | Places (créneaux × terrains) | Rôle |
|---|---|---|---|---|
| `small.json` | 6 | 15 | 12 × 2 = 24 | Cas simple, avec indisponibilités, préférences et une incompatibilité |
| `medium.json` | 16 (2 poules de 8) | 56 | 24 × 4 = 96 | Volume moyen, quotas min/max sur certains créneaux |
| `unsolvable.json` | 6 | 15 | 6 × 2 = 12 | **Volontairement insoluble** : pas assez de places |

## Format (résumé)

```jsonc
{
  "$schema": "./tournament.schema.json",
  "name": "…",
  "format": "round_robin",            // ou "double_round_robin" (aller-retour)
  "teams":  [{ "id": "LIO", "name": "Lions", "pool": "A",
               "unavailable_slots": ["J1-09h"],   // dur
               "preferred_slots": ["J2-14h"] }],  // souple
  "fields": [{ "id": "T1", "name": "Terrain 1", "unavailable_slots": [] }],
  "slots":  [{ "id": "J1-09h", "day": "2026-12-05", "start": "09:00",
               "duration_minutes": 60, "min_matches": 0, "max_matches": 2 }],
  "incompatibilities": [{ "teams": ["LIO", "AIG"], "reason": "même entraîneur" }],
  "rules": { "min_rest_minutes": 60, "max_matches_per_team_per_day": 3 }
}
```

Les matchs ne sont pas saisis : ils sont générés à partir des équipes (méthode du cercle, par poule).
