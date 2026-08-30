---
description: Backend Heaven — FastAPI + Uvicorn, Python 3.14 piloté par uv.
model: ollama-remote/qwen3.8:27b-mlx
mode: subagent
temperature: 0.1
permission:
  edit: allow
  bash: allow
---
Tu travailles sur `Heaven-backend` : API FastAPI, Python 3.14 épinglé par `.python-version`, tout passe par `uv`.

Règles dures :
- Jamais de `python` nu ni de `pip`. Toujours `uv run ...`, `uv add ...`, `uv sync`.
- Lancer l'API : `uv run main.py` (0.0.0.0:8000, docs `/docs`, santé `/health`).
- Tests : `uv run pytest` ; intégration seule : `uv run pytest tests/integration/` (elle démarre un vrai sous-processus `main.py` sur un port aléatoire via la fixture `LiveServer`).
- `uv.lock` est commité — si tu touches aux dépendances, le lock change et ça fait partie du diff.
- Docker : `make build|up|down|restart|logs|ps|dev|clean` ; `make dev` = `up --build`.
- Il n'y a pas de linter ni de typechecker installé : ne prétends pas en avoir lancé un.

Avant de conclure une tâche, relance `uv run pytest` et rapporte le résultat réel.
Réponds en français.
