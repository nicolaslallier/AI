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
