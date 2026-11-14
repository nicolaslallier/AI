# MCP Fichiers

Serveur MCP (Python) qui implémente l'extension expérimentale `io.modelcontextprotocol/files`
sur une copie d'un coffre Obsidian, plus le client en ligne de commande `mcpf`.

But : vérifier qu'un client MCP (Claude Code, par exemple) peut envoyer et récupérer des fichiers
via l'extension. Le serveur sert `vault-test/` par défaut ; le viser sur le coffre réel est un choix
délibéré, pas le réglage par défaut.

## Spécification

- Commit de spec de référence : `8a859b8` dans le dépôt externe
  `modelcontextprotocol/experimental-ext-file-uploads` (`specification/draft/file-uploads.md`). C'est un brouillon.
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
rsync -a --exclude .git ~/Obsidian/Maison/ vault-test/   # copie de travail, ignorée par git
uv run python -m server.app [--vault CHEMIN]   # MCP sur http://127.0.0.1:8765/mcp, coffre : vault-test/ par défaut
```

Le coffre doit exister (le serveur refuse de démarrer sinon, sans le créer). Au démarrage, `<coffre>/.staging/`
est vidé (fichiers et liens, sans jamais suivre un lien) : les jetons d'envoi sont en mémoire, aucun fichier qui y reste n'est valide après un redémarrage ; si `.staging` est un lien symbolique, le serveur refuse de démarrer.

Client `mcpf` (il parle au serveur ci-dessus) ; `--url` avant la sous-commande, pour une autre adresse :

```
uv run mcpf put <fichier> [--dossier D] [--note N]      # envoie dans <D>/Pièces jointes/ (défaut : 00 - Inbox)
uv run mcpf get <chemin> [-o <sortie>]                  # télécharge un fichier du coffre
uv run mcpf --url http://127.0.0.1:8765 put <fichier>   # autre adresse
```

## Outils MCP

| Outil | Rôle |
|---|---|
| `vault_search(query, limit)` | Cherche (sans casse) dans les notes `.md`, renvoie chemin et extrait |
| `vault_read_note(chemin)` | Lit une note `.md` |
| `vault_import_file(file, dossier, note_liée)` | Import via l'extension files (base64 en ligne ou hors bande) |
| `vault_import_base64(name, mimeType, data_base64, dossier, note_liée)` | Import pour les clients **sans** l'extension (limite 1 Mio) |
| `vault_export(chemin)` | Export ; lien de téléchargement si le client déclare `download`, sinon contenu en ligne (1 Mio max) |

Un PDF importé sans `note_liée` ne donne une note de ressource (à partir du modèle
`06 - Modèles/Modèle - Note de ressource.md`) que s'il est reconnu comme police d'assurance (voir plus bas).

## Choix de sécurité

- Écoute sur `127.0.0.1` seulement. Aucune authentification : ne pas exposer le port.
- Chemins confinés au coffre. Les dossiers et fichiers cachés (commençant par `.`) sont refusés,
  y compris via un lien symbolique.
- Pas d'écrasement : un nom déjà pris reçoit un suffixe (`-2`, `-3`…).
- Noms de fichiers assainis : `/ \ [ ] | # ^ < > % { } $` et l'apostrophe inverse sont retirés, ainsi
  qu'une partie des caractères de contrôle, pour qu'un nom ne transporte pas de marqueurs Templater ou Dataview.
- **Jetons d'envoi** (PUT) : à usage unique, valables **15 min** (900 s).
- **Jetons de téléchargement** : **pas** à usage unique. Ils sont relisibles (plusieurs GET, plages
  comprises) jusqu'à leur expiration, 15 min (900 s).
- `requestState` valable **1800 s**.
- Rejeu, sans authentification :
  - l'ensemble des jetons consommés (`TransferStore.consume`, synchrone) protège l'appel de finalisation
    (l'import) : deux relances concurrentes ne passent pas toutes les deux ;
  - le PUT est protégé séparément par son drapeau d'écriture unique (un second PUT reçoit 409) ;
  - les jetons de téléchargement ne sont pas protégés contre le rejeu pendant leur durée de vie.
- Types de fichiers filtrés par `x-mcp-file.accept` : le type MIME déclaré **et**, si le nom a une extension,
  le type que cette extension suggère doivent tous deux être acceptés (`x.html` déclaré `image/png` est refusé) ;
  un nom sans extension passe si le type MIME passe.
- Un fichier importé n'est jamais modifié ; sans `note_liée`, la note de lien est toujours nouvelle (`-2`, `-3`…).

## Notes d'assurance

Un PDF est considéré comme une police s'il contient au moins deux des mots « assur », « police », « prime ».
Extraction par règles simples (pas de LLM), sur le texte du PDF :
- le numéro de police apparaît **masqué** (`****` suivi des 4 derniers chiffres), y compris dans
  les autres occurrences du texte de la note ;
- les champs extraits (assureur, dates, montants) sont assainis : pas de Markdown, ni de syntaxe
  Obsidian, Templater ou Dataview (neutralisation des injections) ;
- un PDF dont le *nom de fichier* contient le numéro de police (en entier ou en chiffres seuls) est stocké
  sous un nom masqué (`****1234`), de même que sa note : aucun numéro en clair dans un nom, une note ou un résultat ;
- **calibrage sur de vrais PDF d'assureurs : à faire.** Les tests utilisent des PDF fabriqués.

## Tester avec Claude Code

Serveur lancé (voir plus haut). **Cette étape n'est pas faite par le projet** : elle modifie la
configuration Claude Code de la personne qui la lance.

```
claude mcp add --transport http mcp-fichiers http://127.0.0.1:8765/mcp
```

Dans Claude Code, demander l'import d'un petit PDF, puis vérifier :
- `vault_import_file` **n'est pas proposé** dans `tools/list` : Claude Code ne déclare pas l'extension files
  (c'est couvert par `test_outil_fichier_cache_sans_upload`) ;
- `vault_import_base64` **réussit** sur ce PDF ;
- côté serveur, un appel hors bande sans la capacité `upload` reçoit l'erreur `-32021`
  (couvert par `test_sans_data_sans_upload_32021`).

Noter le résultat (ce qui a marché, ce qui non) : c'est la matière de l'évaluation du projet.

Retirer le serveur ensuite :

```
claude mcp remove mcp-fichiers
```

## Pas encore fait

- Envoi par morceaux (un fichier n'est envoyé qu'en un seul bloc) et reprise après coupure.
- `mcpf get` n'utilise pas `Range` : le serveur sait répondre aux plages (206/416), le client ne les demande pas encore.
- Authentification, et donc tout usage hors de la machine locale.
- Conteneur Docker.
- Calibrage des notes d'assurance sur de vrais PDF.
