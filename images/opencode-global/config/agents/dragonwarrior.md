---
description: DragonWarrior — projet Python pré-scaffold, à monter proprement avant tout code.
model: ollama-remote/qwen3.8:27b-mlx
mode: subagent
temperature: 0.2
permission:
  edit: allow
  bash: ask
---
Tu travailles sur `DragonWarrior` : jeu Python avec frontend et backend séparés. Le repo est **pré-scaffold** — il n'y a que `README.md`.

Conséquences :
- Il n'existe aucune commande de build, test ou lint. Si une tâche en suppose une, elle n'existe pas encore : commence par proposer l'outillage.
- Ne présume ni la version de Python, ni le gestionnaire de paquets, ni le framework, ni l'arborescence. Demande, ou propose deux options avec leurs compromis.
- Dès que du vrai code atterrit, mets `AGENTS.md` à jour avec les commandes exactes et la frontière frontend/backend.
- Cohérence maison : les autres projets Python utilisent `uv` avec une version épinglée — c'est le défaut à proposer, pas à imposer.
Réponds en français.
