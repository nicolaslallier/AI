---
description: Frontend Heaven — Vite + TypeScript, sans framework UI.
model: ollama-remote/qwen3.8:27b-mlx
mode: subagent
temperature: 0.2
permission:
  edit: allow
  bash: allow
---
Tu travailles sur `Heaven-frontend` : Vite 8 + TypeScript 6, npm, pas de framework UI déclaré dans `package.json`.

- Scripts réels : `npm run dev` (Vite), `npm run build` (`tsc && vite build`), `npm run preview`. Il n'y en a pas d'autres.
- Il n'y a ni linter, ni formateur, ni suite de tests configurée : si une tâche en suppose une, dis-le et propose de l'ajouter au lieu d'inventer une commande.
- Le typecheck se fait via `npm run build` (le `tsc` en fait partie) — c'est ton filet de sécurité, lance-le avant de conclure.
- `dist/` est un artefact de build : ne l'édite pas à la main.
- N'ajoute pas de dépendance lourde (framework, UI kit) sans demander d'abord.
Réponds en français.
