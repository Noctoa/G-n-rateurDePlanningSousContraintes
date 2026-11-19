# Générateur de planning sous contraintes

Génère automatiquement le planning d'un **tournoi sportif** (qui joue contre qui, sur quel terrain, à quel créneau) en respectant des règles fixées :

- **contraintes dures** (obligatoires) : disponibilités des équipes, pas deux matchs en même temps pour une équipe ou un terrain, temps de repos minimum, quotas min/max de matchs par créneau…
- **contraintes souples** (préférences) : équilibrer les horaires, éviter les matchs tardifs pour certaines équipes, etc.

Quand aucune solution ne respecte toutes les contraintes dures, l'outil le **détecte et explique pourquoi**.

Le cœur du projet est le solveur : un CSP par backtracking (MRV, forward checking, AC-3) pour les contraintes dures, puis un recuit simulé pour optimiser les contraintes souples.

> Sujet : Epitech – *Générateur de planning sous contraintes* (brief projet v1, Simulated).
> Roadmap : [GitHub Project](https://github.com/users/Noctoa/projects/3)

## Stack

| Partie | Techno |
|---|---|
| Backend | Python 3.12, FastAPI, SQLite + SQLAlchemy, `uv`, `ruff`, `mypy --strict`, `pytest` |
| Frontend | React 19 + TypeScript, Vite, `oxlint`, Prettier |
| CI | GitHub Actions : lint → tests backend → build frontend |

## Lancement local

Prérequis : [`uv`](https://docs.astral.sh/uv/) et Node.js ≥ 20.

```bash
# Backend → http://localhost:8000 (docs : /docs)
cd backend && uv run uvicorn planning.main:app --reload

# Frontend → http://localhost:5173 (proxy /api vers le backend)
cd frontend && npm install && npm run dev
```

### Résoudre un tournoi en ligne de commande

```bash
cd backend && uv run python -m planning.solve ../datasets/small.json --timeout 10
```

### Sauvegarde et historique

Dans **Mes tournois**, enregistrez le formulaire ou ouvrez un tournoi existant. Générer un
planning enregistre aussi automatiquement le tournoi. L'**historique des générations**
permet de rouvrir chaque résultat avec ses statistiques, son diagnostic et les paramètres
du solveur. Chaque génération conserve son propre instantané du tournoi : modifier les
équipes ou les terrains ne change pas les anciens plannings.

La base SQLite est créée automatiquement dans `backend/planning.sqlite3` avec le lancement
ci-dessus. Pour choisir un autre fichier, définissez `PLANNING_DB_PATH`. Les résultats
restent disponibles après rechargement de la page et redémarrage du serveur. Une recherche
interrompue par un redémarrage est marquée comme annulée. La suppression d'un tournoi
supprime aussi son historique ; elle est refusée pendant une génération active.

L'API expose `GET/POST /api/tournaments`, `GET/PUT/DELETE /api/tournaments/{id}` et
`GET /api/tournaments/{id}/schedules`. `POST /api/schedules` accepte un `tournament_id`
pour ajouter une génération à un tournoi existant, et renvoie cet identifiant.
Le champ `score` de l'historique reste `null` jusqu'à l'implémentation du score souple (#12).

## Qualité

```bash
# Backend
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest

# Frontend
cd frontend
npm run lint && npm run format:check && npm run build
```

## Structure

```
backend/    API FastAPI + solveur (src/planning, tests)
frontend/   Interface React (saisie du tournoi, visualisation du planning)
docs/       Documents de conception
datasets/   Tournois d'exemple au format JSON
```
