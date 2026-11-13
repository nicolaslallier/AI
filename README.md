# MCP Fichiers

Serveur MCP (Python) qui implémente l'extension expérimentale `io.modelcontextprotocol/files`
sur une **copie** d'un coffre Obsidian, plus le client en ligne de commande `mcpf`.

But : vérifier qu'un client MCP (Claude Code, par exemple) peut envoyer et récupérer des fichiers
via l'extension, sans toucher au coffre réel. Le coffre réel n'est jamais écrit par ce projet.

## Spécification

- Commit de spec de référence : `8a859b8` (`specification/draft/file-uploads.md`). C'est un brouillon.
- **Digest** : sha-256 en base64url, **sans remplissage `=`** (objet `{algorithm, value}`).
- **`FileInput`** : champs requis `id` (1 à 128 caractères), `mimeType`, `size` (entier >= 0), plus
  `digest` requis dans cette implémentation. Optionnels : `name`, `data` (base64 RFC 4648 ; absent
  et `size > 0` = envoi hors bande).
- **`x-mcp-file`** (`FileInputDescriptor`) : `accept?`, `maxSize?`.

Ce que le brouillon a appris au projet :
- le digest s'écrit sans `=` de remplissage, à la différence du base64 standard ;
- `digest` est requis ici avec `id`, `mimeType` et `size` : sans lui, l'intégrité du fichier n'est pas vérifiée ;
- l'envoi hors bande passe par `upload_required` et un `requestState` scellé (voir ci-dessous).

## Dépendances et point fragile

- `mcp==2.3.0` est **épinglé**. Ne pas monter la version sans relire la suite de tests.
- `server/files_ext.py` appelle `RequestStateBoundary._seal`, méthode **privée** du SDK, pour sceller
  le `requestState` de la réponse `upload_required`. Le test `test_seal_existe_encore`
  (`tests/test_files_ext.py`) vérifie sa signature et casse si le SDK la change.

## Lancer

```
uv sync
uv run pytest -q
cp -R ~/Obsidian/Maison vault-test   # copie de travail, ignorée par git
uv run python -m server.app          # MCP sur http://127.0.0.1:8765/mcp, coffre : vault-test/
```

Client `mcpf` (il parle au serveur ci-dessus ; `--url` pour une autre adresse) :

```
uv run mcpf put <fichier> [--dossier D] [--note N]   # envoie dans <D>/Pièces jointes/ (défaut : 00 - Inbox)
uv run mcpf get <chemin> -o <sortie>                 # télécharge un fichier du coffre
```

## Outils MCP

| Outil | Rôle |
|---|---|
| `vault_search(query, limit)` | Cherche (sans casse) dans les notes `.md`, renvoie chemin et extrait |
| `vault_read_note(chemin)` | Lit une note `.md` |
| `vault_import_file(file, dossier, note_liée)` | Import via l'extension files (base64 en ligne ou hors bande) |
| `vault_import_base64(name, mimeType, data_base64, dossier, note_liée)` | Import pour les clients **sans** l'extension (limite 1 Mio) |
| `vault_export(chemin)` | Export ; lien de téléchargement si le client déclare `download`, sinon contenu en ligne (1 Mio max) |

Un PDF d'assurance importé sans `note_liée` produit une note de ressource à partir du modèle
`06 - Modèles/Modèle - Note de ressource.md` (voir ci-dessous).

## Choix de sécurité

- Écoute sur `127.0.0.1` seulement. Aucune authentification : ne pas exposer le port.
- Chemins confinés au coffre. Les dossiers et fichiers cachés (commençant par `.`) sont refusés,
  y compris via un lien symbolique.
- Pas d'écrasement : un nom déjà pris reçoit un suffixe (`-2`, `-3`…).
- Jetons de transfert à usage unique, valables **15 min** (900 s).
- `requestState` valable **1800 s**.
- Sans authentification, la protection contre le rejeu repose uniquement sur l'ensemble des jetons
  consommés (`TransferStore.consume`, synchrone) : deux relances concurrentes ne passent pas toutes les deux.
- Types de fichiers filtrés par `x-mcp-file.accept`.

## Notes d'assurance

Un PDF est considéré comme une police s'il contient au moins deux des mots « assur », « police », « prime ».
Extraction par règles simples (pas de LLM), sur le texte du PDF :
- le numéro de police apparaît **masqué** (`****` suivi des 4 derniers chiffres), y compris dans
  les autres occurrences du texte ;
- le texte extrait est assaini : pas de Markdown, ni de syntaxe Obsidian, Templater ou Dataview
  (neutralisation des injections) ;
- **compromis connu** : un PDF dont le *nom de fichier* contient le numéro de police reçoit un lien
  masqué ou cassé vers le PDF. Acceptable pour l'instant, à traiter si ça gêne ;
- **calibrage sur de vrais PDF d'assureurs : à faire.** Les tests utilisent des PDF fabriqués.

## Tester avec Claude Code

Serveur lancé (voir plus haut). **Cette étape n'est pas faite par le projet** : elle modifie la
configuration Claude Code de la personne qui la lance.

```
claude mcp add --transport http mcp-fichiers http://127.0.0.1:8765/mcp
```

Dans Claude Code, demander l'import d'un petit PDF, puis vérifier :
- `vault_import_file` **n'est pas proposé** : Claude Code ne déclare pas l'extension files ;
- `vault_import_base64` **réussit** sur ce PDF.

Noter le résultat (ce qui a marché, ce qui non) : c'est la matière de l'évaluation du projet.

Retirer le serveur ensuite :

```
claude mcp remove mcp-fichiers
```

## Pas encore fait

- Envoi et téléchargement par morceaux (un fichier n'est envoyé qu'en un seul bloc) et reprise après coupure.
- Authentification, et donc tout usage hors de la machine locale.
- Conteneur Docker.
- Calibrage des notes d'assurance sur de vrais PDF.
