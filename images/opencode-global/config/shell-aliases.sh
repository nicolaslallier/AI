# Raccourcis opencode : tout se rattache au serveur unique 127.0.0.1:4096.
# À sourcer depuis ~/.zshrc :   source ~/.config/opencode/shell-aliases.sh
export OPENCODE_SERVER_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"

# TUI rattachée au serveur, dans le dossier courant
oc()  { opencode attach "$OPENCODE_SERVER_URL" --dir "$PWD" "$@"; }

# Prompt one-shot sur le même serveur
ocr() { opencode run --attach "$OPENCODE_SERVER_URL" --dir "$PWD" "$@"; }

# Reprendre la dernière session du serveur
occ() { opencode attach "$OPENCODE_SERVER_URL" --dir "$PWD" --continue "$@"; }

# Lancer un agent précis : ocA infra "monte la stack"
ocA() { local a="$1"; shift; opencode run --attach "$OPENCODE_SERVER_URL" --dir "$PWD" --agent "$a" "$@"; }

# État du serveur
ocstatus() {
  if curl -fsS --max-time 2 "$OPENCODE_SERVER_URL/doc" >/dev/null 2>&1; then
    echo "opencode UP  -> $OPENCODE_SERVER_URL"
  else
    echo "opencode DOWN. launchctl kickstart -k gui/$(id -u)/net.famillelallier.opencode"
  fi
}

# Logs du serveur
oclogs() { tail -f ~/Library/Logs/opencode-serve.err.log; }
