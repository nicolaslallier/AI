#!/usr/bin/env bash
# Force UN modèle partout : config globale + chaque agent, et purge le "dernier
# modèle utilisé" qu'opencode garde en mémoire pour les sessions déjà créées.
#
#   ./pin-model.sh                       # réapplique le modèle de la config
#   ./pin-model.sh qwen3.8:27b-mlx       # impose ce tag
#   ./pin-model.sh --agents-only ...     # n'épingle que les agents
set -euo pipefail

CFG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
STATE="$HOME/.local/share/opencode"
PROVIDER="ollama-remote"
LABEL="net.famillelallier.opencode"
say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m /!\\\033[0m %s\n' "$*"; }

TAG="${1:-}"
if [ -z "$TAG" ] || [ "$TAG" = "--agents-only" ]; then
  TAG="$(python3 -c "import json;print(json.load(open('$CFG/opencode.json'))['model'].split('/',1)[1])")"
fi
FULL="$PROVIDER/$TAG"
say "modèle imposé : $FULL"

# 1. config globale
python3 - "$CFG/opencode.json" "$FULL" <<'PY'
import json, sys
p, full = sys.argv[1], sys.argv[2]
c = json.load(open(p))
c["model"] = full
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False)
open(p, "a").write("\n")
print(f"  config : model = {full}")
PY

# 2. chaque agent (le front-matter d'un agent bat la config globale)
for f in "$CFG"/agents/*.md; do
  python3 - "$f" "$FULL" <<'PY'
import re, sys, pathlib
p, full = pathlib.Path(sys.argv[1]), sys.argv[2]
t = p.read_text()
m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
if not m:
    print(f"  !! {p.name} : pas de front-matter, ignoré"); raise SystemExit
fm, rest = m.group(1), t[m.end():]
if re.search(r"^model:", fm, re.M):
    fm = re.sub(r"^model:.*$", f"model: {full}", fm, flags=re.M)
else:
    fm = re.sub(r"^(description:.*)$", r"\1\n" + f"model: {full}", fm, count=1, flags=re.M)
p.write_text(f"---\n{fm}\n---\n{rest}")
print(f"  agent  : {p.name}")
PY
done

# 2b. miroir vers la source, pour qu'un futur ./install.sh ne défasse pas l'épinglage
SRCDIR="$HOME/OpenCode/opencode-global"
if [ -d "$SRCDIR" ] && [ "$SRCDIR" != "$CFG" ]; then
  cp "$CFG"/agents/*.md "$SRCDIR/agents/" 2>/dev/null || true
  python3 - "$SRCDIR/opencode.json" "$FULL" <<'PY2' 2>/dev/null || true
import json, sys
p, full = sys.argv[1], sys.argv[2]
c = json.load(open(p)); c["model"] = full
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False); open(p, "a").write("\n")
PY2
  say "source mise à jour : $SRCDIR (l'épinglage survivra à ./install.sh)"
fi

# 3. le "dernier modèle utilisé" : il bat la config pour une session DÉJÀ créée
if [ -d "$STATE" ]; then
  HITS="$(grep -rlE '"(model|modelID)" *: *"' "$STATE" 2>/dev/null | wc -l | tr -d ' ')"
  say "état persistant : $HITS fichier(s) mentionnent un modèle"
  warn "Les sessions déjà ouvertes gardent LEUR modèle : la config ne s'applique"
  warn "qu'aux sessions neuves. Ouvre une session neuve (\`oc\`, pas \`occ\`),"
  warn "ou change le modèle dans la TUI avec /models."
fi

# 4. redémarrage du serveur pour qu'il relise tout
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null \
  || { pkill -f 'opencode serve' 2>/dev/null || true; "$CFG/fix-service.sh" >/dev/null 2>&1 || true; }
say "serveur redémarré — vérifie avec :  opencode models | head"
