# Contrat `v1` : portail et agents en conteneur

Les exemples de chaque message sont dans `docs/agents-contrat-v1.json` ; la bibliothèque Rust des agents et les tests Python lisent le même fichier. Les types côté portail sont dans `backend/portail/missions.py`.

## Rôles

Le portail autorise, l'agent raisonne. Le portail garde le modèle, la température, les schémas d'outils offerts, les compteurs, les limites et la fin de la mission. L'agent ne choisit que le contenu de ses messages, s'il veut offrir les outils, le format de réponse et le flux, puis le nom et les arguments des outils qu'il appelle. Toute demande venue d'un agent est refusée si elle porte un champ inconnu (422).

## Messages

Un message (`MessageLLM`) a pour champs `role` (`system`, `user`, `assistant`, `tool`), `content` (texte ou nul), et, facultatifs, `tool_calls` (64 au plus, chacun `{id, type: "function", function: {name, arguments}}` avec `arguments` en chaîne, aucun autre champ), `tool_call_id` et `name`. Tout autre champ est refusé (422). Bornes : 2000 messages par demande, 500 000 caractères par `content`, 128 caractères pour le nom d'un outil, 200 000 pour ses arguments. Le portail mesure le contexte sur la taille du message entier (JSON), pas sur `content` seul, plus celle du `response_format`, et il ne rend à l'agent que `role`, `content` et `tool_calls`.

## `POST /missions` (portail vers agent)

- En-tête `Authorization: Bearer <secret de l'agent>`. Corps : `DemandeMission` (exemple `mission`).
- Réponse `application/x-ndjson` : zéro ou plusieurs lignes `texte`, puis exactement une ligne `fin` ou `erreur`.
- Fermer la connexion annule la mission.
- Codes : 401 mauvais secret, 403 mission pour un autre agent, 422 contrat inconnu ou corps invalide.

## `GET /sante` (agent)

Sans authentification. Réponse `Sante` : le contrat parlé (16 caractères au plus, `[A-Za-z0-9_.-]`), le nom de l'agent (64 au plus, `[A-Za-z0-9_-]`, égal au nom du catalogue : sinon le portail n'envoie ni secret ni mission), la version de l'image (64 au plus, `[A-Za-z0-9_.:@+-]`). Une réponse hors bornes vaut « l'agent ne répond pas ».

## `POST /interne/modele` et `POST /interne/outils` (agent vers portail)

En-tête `Authorization: Bearer <jeton de mission>`.

- Une seule demande `/interne/` à la fois par mission : une demande reçue pendant qu'une autre est en cours est refusée (429), sans lire son corps.
- `/interne/modele` : corps `DemandeModele`, réponse `ReponseModele`. `response_format` est soit `{"type": "json_object"}`, soit `{"type": "json_schema", "json_schema": {…}}` d'au plus 32 000 caractères de JSON ; tout autre format est refusé (422).
- `/interne/outils` : corps `DemandeOutil`, réponse `ReponseOutil` ; `arret` demande à l'agent de conclure. Les outils ne s'exécutent qu'à la suite d'un appel à `/interne/modele` qui les a offerts (`outils: true`, au plus `tours_max` appels) : sinon 409. Le dernier appel permis (`tours_max + 1`) n'en offre aucun et marque `limite_atteinte`.
- Codes : 401 jeton invalide ou expiré, 409 mission arrêtée, 413 contexte dépassé, 422 demande invalide, 429 limite d'appels au modèle, 502 modèle indisponible.
- Corps d'erreur : `ReponseErreur`, `{"erreur": "<texte fixe>"}`. Le texte ne reprend jamais un contenu venu de l'agent ou du modèle.

### Option `flux` de `/interne/modele`

Permise seulement avec `outils: false`. Les lignes sont distinctes de celles de `/missions` (modèles `LigneFluxTexte`, `LigneFluxFin`, `LigneErreur`). La réponse est en lignes JSON : `{"type": "texte", "texte"}` zéro ou plusieurs fois, puis `{"type": "fin", "message": {"role": "assistant", "content"}}` ou `{"type": "erreur", "erreur"}`.

## Limites tenues par le portail

Le nombre de tours de la mission, le nombre d'appels d'outils par tour, le contexte maximal et le nombre d'appels au modèle sont comptés par le portail, pas par l'agent. Au-delà, le portail répond par le code ci-dessus (413, 429, 409) ; une limite atteinte est rendue à l'appelant avec `limite_atteinte: true`, quoi que dise l'agent : le champ `limite_atteinte` de la ligne `fin` n'est jamais lu. La réponse d'un agent est bornée en taille de ligne, en nombre de lignes et en total d'octets ; au-delà, la mission est interrompue. Le `texte` d'une ligne `texte` ou `fin` ne dépasse pas 500 000 caractères, et le total des caractères de `texte` relayés par mission non plus ; au-delà, la mission est interrompue. Aucun texte venu de l'agent (ligne `erreur`, `contrat`) n'entre dans une erreur du portail : les messages sont fixes.

## Validité du jeton

Un jeton vaut pour une mission et un agent, pendant la durée de la mission seulement. Il meurt à la fin de la mission (fermeture, annulation, délai dépassé) ; après l'échéance ou la fermeture, une NOUVELLE demande reçoit 401 (jeton mort) ; seul un appel déjà authentifié, en cours ou en vol, reçoit 409 ; les appels en vol sont annulés. Il n'apparaît dans aucun journal ni aucune métrique.

## Compatibilité

Un champ nouveau facultatif ne change pas `v1`. Tout le reste (champ retiré, champ rendu obligatoire, sens modifié, nouveau code) demande `v2`.
