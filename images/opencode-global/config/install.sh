#!/usr/bin/env bash
# Installe la config opencode globale : provider central + agents partagés + serveur launchd.
# Idempotent. Sauvegarde ce qui existe déjà.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
OLLAMA_URL="${OLLAMA_URL:-http://192.168.2.40:11434}"
STAMP="$(date +%Y%m%d-%H%M%S)"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m /!\\\033[0m %s\n' "$*"; }

# --- 0. opencode présent ? -------------------------------------------------
if ! command -v opencode >/dev/null 2>&1; then
  warn "opencode n'est pas dans le PATH. Installe-le puis relance :"
  echo "    brew install sst/tap/opencode      # ou : curl -fsSL https://opencode.ai/install | bash"
  exit 1
fi
OPENCODE_BIN="$(command -v opencode)"
say "opencode trouvé : $OPENCODE_BIN ($(opencode --version 2>/dev/null || echo 'version inconnue'))"

# --- 1. config globale -----------------------------------------------------
mkdir -p "$DEST"
if [ -f "$DEST/opencode.json" ]; then
  cp "$DEST/opencode.json" "$DEST/opencode.json.bak-$STAMP"
  say "ancien opencode.json sauvegardé -> opencode.json.bak-$STAMP"
fi
cp "$SRC/opencode.json" "$DEST/opencode.json"
say "config écrite : $DEST/opencode.json"

# --- 2. agents partagés ----------------------------------------------------
mkdir -p "$DEST/agents"
for f in "$SRC"/agents/*.md; do
  b="$(basename "$f")"
  [ -f "$DEST/agents/$b" ] && cp "$DEST/agents/$b" "$DEST/agents/$b.bak-$STAMP"
  cp "$f" "$DEST/agents/$b"
done
# Selon la version, opencode lit `agent/` ou `agents/` : on couvre les deux.
if [ ! -e "$DEST/agent" ]; then
  ln -s agents "$DEST/agent"
elif [ ! -L "$DEST/agent" ]; then
  warn "$DEST/agent existe et n'est pas un lien — laissé tel quel, vérifie-le à la main."
fi
say "agents installés : $(ls -1 "$DEST"/agents/*.md | wc -l | tr -d ' ') fichiers dans $DEST/agents"

cp "$SRC/shell-aliases.sh" "$DEST/shell-aliases.sh"
cp "$SRC/refresh-models.py" "$DEST/refresh-models.py"
cp "$SRC/fix-service.sh" "$DEST/fix-service.sh" 2>/dev/null || true
cp "$SRC/diag.sh" "$DEST/diag.sh" 2>/dev/null || true
cp "$SRC/pin-model.sh" "$DEST/pin-model.sh" 2>/dev/null || true
chmod +x "$DEST"/*.sh "$DEST/refresh-models.py" 2>/dev/null || true
say "raccourcis shell : $DEST/shell-aliases.sh"

# --- 3. modèles réels depuis Ollama ---------------------------------------
say "interrogation d'Ollama sur $OLLAMA_URL ..."
set +e
python3 "$SRC/refresh-models.py" "$DEST/opencode.json" --url "$OLLAMA_URL"
RC=$?
set -e
case "$RC" in
  0) ;;
  2) warn "Liste des modèles écrite, mais un modèle épinglé n'est pas servi (voir ci-dessus)." ;;
  *) warn "Ollama injoignable. La config garde des placeholders — relance plus tard :"
     echo "    python3 $DEST/refresh-models.py --url $OLLAMA_URL" ;;
esac

# --- 4. serveur au démarrage (launchd) ------------------------------------
PLIST="$HOME/Library/LaunchAgents/net.famillelallier.opencode.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__OPENCODE_BIN__|$OPENCODE_BIN|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__PATH__|$(dirname "$OPENCODE_BIN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin|g" \
    "$SRC/net.famillelallier.opencode.plist" > "$PLIST"
chmod 644 "$PLIST"
say "plist écrit : $PLIST"

# --- 5. chargement + vérification -----------------------------------------
# fix-service.sh gère bootstrap / load -w / démarrage direct et dit ce qui a marché.
exec "$SRC/fix-service.sh"
