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
| Backend | Python 3.12, FastAPI, `uv`, `ruff`, `mypy --strict`, `pytest` |
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
