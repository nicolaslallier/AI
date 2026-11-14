# Agents

Définitions d'agents et de sous-agents Claude Code, un fichier `.md` par agent :

```markdown
---
name: mon-agent
description: Quand l'utiliser, en une phrase.
tools: Read, Grep, Glob
---

Instructions de l'agent.
```

Pour les utiliser dans un projet, copier ou lier le fichier dans `.claude/agents/`
(ou `~/.claude/agents/` pour tous les projets).

Un agent qui tourne seul, hors de Claude Code, a en plus son dossier `agents/<nom>/` :
un programme Python (Claude Agent SDK) avec son `pyproject.toml`, ses tests et son
README. Il relit les mêmes `.md`, pour qu'une définition serve aux deux usages.

| Agent | Rôle |
|---|---|
| [`orchestrateur`](orchestrateur.md) | Découpe une demande et la fait réaliser par les quatre suivants ; programme dans [`orchestrateur/`](orchestrateur/) |
| [`explorateur`](explorateur.md) | Comprend le code avant qu'on le change, en lecture seule |
| [`codeur`](codeur.md) | Réalise une tâche bornée, avec ses tests, et la committe |
| [`testeur`](testeur.md) | Lance les tests et rend un verdict |
| [`relecteur`](relecteur.md) | Relit le diff d'une branche et rend un verdict |
