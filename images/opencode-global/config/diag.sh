#!/usr/bin/env bash
# Diagnostic : pourquoi opencode ne prend pas le provider Ollama distant.
OLLAMA_URL="${OLLAMA_URL:-http://192.168.2.40:11434}"
SRV="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
h() { printf '\n\033[1;36m===== %s =====\033[0m\n' "$*"; }

h "1. opencode"
command -v opencode || echo "ABSENT DU PATH"
opencode --version 2>&1 | head -1

h "2. Ollama joignable depuis ce Mac ? (API native)"
curl -s --max-time 6 "$OLLAMA_URL/api/tags" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(" -",m["name"]) for m in d.get("models",[])]' \
  2>&1 || echo "ECHEC /api/tags"

h "3. Ollama en mode OpenAI-compatible ? (c'est CE endpoint qu'opencode utilise)"
curl -s --max-time 6 "$OLLAMA_URL/v1/models" | head -c 800; echo

h "4. Un vrai appel de complétion sur le modèle configuré"
MODEL="$(python3 -c "import json;print(json.load(open('$CFG/opencode.json'))['model'].split('/',1)[1])" 2>/dev/null)"
echo "modèle configuré : ${MODEL:-INCONNU}"
curl -s --max-time 30 "$OLLAMA_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"dis OK\"}],\"max_tokens\":5}" \
  | head -c 600; echo

h "5. Config sur le disque"
cat "$CFG/opencode.json" 2>&1

h "6. Fichiers de config concurrents (ils écrasent la globale !)"
ls -la "$CFG" 2>&1 | sed -n '1,20p'
echo "-- OPENCODE_CONFIG=${OPENCODE_CONFIG:-<non défini>}"
echo "-- OPENCODE_CONFIG_CONTENT=${OPENCODE_CONFIG_CONTENT:+<DÉFINI, il gagne sur tout>}"
echo "-- opencode.json dans le dossier courant : $([ -f ./opencode.json ] && echo OUI || echo non)"
echo "-- .opencode/ dans le dossier courant   : $([ -d ./.opencode ] && echo OUI || echo non)"

h "7. Ce que le SERVEUR a réellement chargé"
curl -s --max-time 5 "$SRV/config" | head -c 1200; echo

h "8. Modèles vus par opencode"
opencode models 2>&1 | head -30

h "9. Agents"
ls -la "$CFG/agents" 2>&1 | head -15
echo "-- lien agent : $(ls -ld "$CFG/agent" 2>&1)"

h "10. Modèle réellement choisi : d'où vient-il ?"
STATE="$HOME/.local/share/opencode"
echo "-- config  model = $(python3 -c "import json;print(json.load(open('$CFG/opencode.json')).get('model'))" 2>/dev/null)"
echo "-- config  small = $(python3 -c "import json;print(json.load(open('$CFG/opencode.json')).get('small_model'))" 2>/dev/null)"
echo "-- état persistant : $STATE"
ls -la "$STATE" 2>&1 | sed -n '1,12p'
echo "-- traces de modèle dans l'état (le \"last used\" bat la config pour une session déjà créée) :"
grep -rhoE '"(model|modelID|providerID)" *: *"[^"]+"' "$STATE" 2>/dev/null | sort | uniq -c | sort -rn | head -15
echo "-- modèle par agent (front-matter) :"
grep -l '^model:' "$CFG"/agents/*.md 2>/dev/null || echo "   aucun agent n'épingle de modèle (ils suivent la config globale)"

h "11. Logs du serveur (30 dernières lignes d'erreur)"
tail -n 30 ~/Library/Logs/opencode-serve.err.log 2>&1
