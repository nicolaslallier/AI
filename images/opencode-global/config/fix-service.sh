#!/usr/bin/env bash
# Charge (ou recharge) le serveur opencode. Essaie launchd, puis retombe sur un
# démarrage direct si launchd refuse. Affiche la vraie raison de l'échec.
set -uo pipefail

LABEL="net.famillelallier.opencode"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_="$(id -u)"
TGT="gui/$UID_/$LABEL"
SRV="http://127.0.0.1:4096"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m /!\\\033[0m %s\n' "$*"; }

up() { curl -fsS --max-time 2 "$SRV/doc" >/dev/null 2>&1; }

wait_up() { for _ in $(seq 1 25); do up && return 0; sleep 1; done; return 1; }

if up; then say "le serveur répond déjà sur $SRV"; fi

# --- nettoyage complet -----------------------------------------------------
say "arrêt de tout service/processus existant"
launchctl bootout "$TGT"            2>/dev/null
launchctl bootout "gui/$UID_" "$PLIST" 2>/dev/null
launchctl unload  "$PLIST"          2>/dev/null
pkill -f 'opencode serve'           2>/dev/null
sleep 1

# --- contrôles préalables --------------------------------------------------
[ -f "$PLIST" ] || { warn "plist absent : $PLIST — relance ./install.sh"; exit 1; }
chmod 644 "$PLIST"
plutil -lint "$PLIST" || { warn "plist mal formé"; exit 1; }
BIN="$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$PLIST" 2>/dev/null)"
say "binaire visé : $BIN"
[ -x "$BIN" ] || { warn "$BIN n'est pas exécutable"; exit 1; }
mkdir -p "$HOME/Library/Logs"

# --- tentative 1 : bootstrap moderne --------------------------------------
say "launchctl enable + bootstrap"
launchctl enable "$TGT" 2>/dev/null
if launchctl bootstrap "gui/$UID_" "$PLIST" 2>&1; then
  launchctl kickstart -k "$TGT" 2>/dev/null
  if wait_up; then say "OK via launchd (bootstrap). Serveur UP -> $SRV"; exit 0; fi
  warn "service chargé mais le serveur ne répond pas — voir les logs plus bas"
else
  warn "bootstrap refusé (code $?)"
fi

# --- tentative 2 : load -w (ancienne API, tolère des cas que bootstrap refuse)
say "repli : launchctl load -w"
if launchctl load -w "$PLIST" 2>&1; then
  if wait_up; then say "OK via launchd (load -w). Serveur UP -> $SRV"; exit 0; fi
fi
warn "launchd n'y arrive pas."

# --- diagnostic launchd ----------------------------------------------------
say "état launchd du service"
launchctl print "$TGT" 2>&1 | sed -n '1,25p'

# --- tentative 3 : démarrage direct ---------------------------------------
say "repli : démarrage direct (ne survivra pas au redémarrage du Mac)"
nohup "$BIN" serve --hostname 127.0.0.1 --port 4096 \
  >>"$HOME/Library/Logs/opencode-serve.log" \
  2>>"$HOME/Library/Logs/opencode-serve.err.log" &
disown
if wait_up; then
  say "Serveur UP -> $SRV (lancé à la main)"
  warn "à relancer après chaque redémarrage : ./fix-service.sh"
  exit 0
fi

warn "le serveur ne démarre pas du tout. Dernières erreurs :"
tail -n 40 "$HOME/Library/Logs/opencode-serve.err.log" 2>&1
warn "essaie en avant-plan pour voir l'erreur brute :  $BIN serve --port 4096"
exit 1
