#!/usr/bin/env python3
"""Interroge Ollama et réécrit le bloc provider.<PROVIDER>.models de opencode.json.

Usage:
  python3 refresh-models.py [chemin/opencode.json] [--url http://host:11434]

L'id de provider est `ollama-remote` et NON `ollama` : opencode découvre tout seul
un Ollama sur 127.0.0.1:11434 sous l'id `ollama`, et les configs sont fusionnées,
pas remplacées — réutiliser cet id fait entrer en collision le provider auto-détecté
(localhost) avec le nôtre (machine distante).

Un `model` / `small_model` écrit à la main n'est jamais réécrit : s'il n'est pas
servi, le script avertit et sort en code 2.
"""
import json, re, sys, urllib.request, pathlib

PROVIDER = "ollama-remote"

CONFIG = pathlib.Path(
    sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
    else pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
).expanduser()

url = "http://192.168.2.40:11434"
for i, a in enumerate(sys.argv):
    if a == "--url" and i + 1 < len(sys.argv):
        url = sys.argv[i + 1]

def size_b(name):
    """Nombre de paramètres en milliards déduit du tag, ou None."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", name.split(":")[-1], re.I)
    return float(m.group(1)) if m else None

def candidates(names):
    """Modèles utilisables comme modèle de chat par défaut."""
    out = []
    for n in names:
        low = n.lower()
        if "embed" in low or "rerank" in low:
            continue      # pas un modèle de chat
        if low.endswith("-cloud") or ":cloud" in low:
            continue      # passe par Ollama Cloud : pas un modèle local
        out.append(n)
    return out

def pick_big(names):
    c = candidates(names)
    if not c:
        return None
    coders = [n for n in c if "coder" in n.lower()]
    pool = coders or c
    sized = [n for n in pool if size_b(n) is not None]
    return max(sized, key=size_b) if sized else pool[0]

def pick_small(names):
    c = candidates(names)
    if not c:
        return None
    sized = [n for n in c if size_b(n) is not None]
    return min(sized, key=size_b) if sized else c[0]

try:
    with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=10) as r:
        tags = json.load(r)
except Exception as e:
    sys.exit(f"Impossible de joindre Ollama sur {url} : {e}\n"
             f"Vérifie que la machine est allumée et qu'Ollama écoute sur 0.0.0.0 "
             f"(OLLAMA_HOST=0.0.0.0:11434), puis relance.")

names = sorted(m["name"] for m in tags.get("models", []))
if not names:
    sys.exit(f"Ollama répond sur {url} mais ne sert aucun modèle. Fais `ollama pull <modele>` d'abord.")

cfg = json.loads(CONFIG.read_text())
prov = cfg.setdefault("provider", {}).setdefault(PROVIDER, {})
prov["models"] = {n: {"name": n, "tools": True} for n in names}
prov.setdefault("npm", "@ai-sdk/openai-compatible")
prov.setdefault("name", "Ollama")
prov.setdefault("options", {})["baseURL"] = url.rstrip("/") + "/v1"

# L'Ollama auto-détecté sur localhost ne doit pas concurrencer le nôtre.
dis = cfg.setdefault("disabled_providers", [])
if "ollama" not in dis:
    dis.append("ollama")

# Purge un ancien bloc `ollama` laissé par une version précédente de cette config.
if "ollama" in cfg.get("provider", {}):
    del cfg["provider"]["ollama"]

warnings = []

def resolve(key, picker):
    """Ne remplace jamais un modèle choisi à la main : on complète, on avertit."""
    v = cfg.get(key, "")
    tag = v.split("/", 1)[1] if "/" in v else ""
    # Réaligne le préfixe si la config vient d'une version antérieure (`ollama/...`).
    if tag and tag != "PLACEHOLDER":
        cfg[key] = f"{PROVIDER}/{tag}"
        if tag not in names:
            warnings.append(
                f"{key} = {PROVIDER}/{tag} n'est PAS servi par {url}. Valeur conservée "
                f"telle quelle (opencode échouera au premier appel). Corrige-la dans la "
                f"config, ou fais `ollama pull` du bon tag."
            )
        return
    p = picker(names)
    if p:
        cfg[key] = f"{PROVIDER}/{p}"
    else:
        warnings.append(f"{key} : aucun modèle de chat utilisable trouvé sur {url}.")

resolve("model", pick_big)
resolve("small_model", pick_small)

CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print(f"{len(names)} modèle(s) trouvé(s) sur {url} :")
for n in names:
    print("  -", n)
print(f"\nmodel       = {cfg['model']}")
print(f"small_model = {cfg['small_model']}")
print(f"écrit dans {CONFIG}")
for w in warnings:
    print("\n/!\\ " + w)
if warnings:
    sys.exit(2)
