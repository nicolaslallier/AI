# Contrat `v1` : portail et agents en conteneur

Les exemples de chaque message sont dans `docs/agents-contrat-v1.json` ; la bibliothèque Rust des agents et les tests Python lisent le même fichier. Les types côté portail sont dans `backend/portail/missions.py`.

## Rôles

Le portail autorise, l'agent raisonne. Le portail garde le modèle, la température, les schémas d'outils offerts, les compteurs, les limites et la fin de la mission. L'agent ne choisit que le contenu de ses messages, s'il veut offrir les outils, le format de réponse et le flux, puis le nom et les arguments des outils qu'il appelle. Toute demande venue d'un agent est refusée si elle porte un champ inconnu (422).

## Messages

Un message (`MessageLLM`) a pour champs `role` (`system`, `user`, `assistant`, `tool`), `content` (texte ou nul), et, facultatifs, `tool_calls` (liste, 64 au plus), `tool_call_id` et `name`. Tout autre champ est refusé (422). Bornes : 2000 messages par demande, 500 000 caractères par `content`, 128 caractères pour le nom d'un outil, 200 000 pour ses arguments. Le portail mesure le contexte sur la taille du message entier (JSON), pas sur `content` seul, et il ne rend à l'agent que `role`, `content` et `tool_calls`.

## `POST /missions` (portail vers agent)

- En-tête `Authorization: Bearer <secret de l'agent>`. Corps : `DemandeMission` (exemple `mission`).
- Réponse `application/x-ndjson` : zéro ou plusieurs lignes `texte`, puis exactement une ligne `fin` ou `erreur`.
- Fermer la connexion annule la mission.
- Codes : 401 mauvais secret, 403 mission pour un autre agent, 422 contrat inconnu ou corps invalide.

## `GET /sante` (agent)

Sans authentification. Réponse `Sante` : le contrat parlé, le nom de l'agent, la version de l'image.

## `POST /interne/modele` et `POST /interne/outils` (agent vers portail)

En-tête `Authorization: Bearer <jeton de mission>`.

- `/interne/modele` : corps `DemandeModele`, réponse `ReponseModele`.
- `/interne/outils` : corps `DemandeOutil`, réponse `ReponseOutil` ; `arret` demande à l'agent de conclure.
- Codes : 401 jeton invalide ou expiré, 409 mission arrêtée, 413 contexte dépassé, 422 demande invalide, 429 limite d'appels au modèle, 502 modèle indisponible.
- Corps d'erreur : `ReponseErreur`, `{"erreur": "<texte fixe>"}`. Le texte ne reprend jamais un contenu venu de l'agent ou du modèle.

### Option `flux` de `/interne/modele`

Permise seulement avec `outils: false`. Les lignes sont distinctes de celles de `/missions` (modèles `LigneFluxTexte`, `LigneFluxFin`, `LigneErreur`). La réponse est en lignes JSON : `{"type": "texte", "texte"}` zéro ou plusieurs fois, puis `{"type": "fin", "message": {"role": "assistant", "content"}}` ou `{"type": "erreur", "erreur"}`.

## Limites tenues par le portail

Le nombre de tours de la mission, le nombre d'appels d'outils par tour, le contexte maximal et le nombre d'appels au modèle sont comptés par le portail, pas par l'agent. Au-delà, le portail répond par le code ci-dessus (413, 429, 409) ; une limite atteinte est rendue à l'appelant avec `limite_atteinte: true`, quoi que dise l'agent.

## Validité du jeton

Un jeton vaut pour une mission et un agent, pendant la durée de la mission seulement. Il meurt à la fin de la mission (fermeture, annulation, délai dépassé) ; les appels en vol sont alors annulés. Il n'apparaît dans aucun journal ni aucune métrique.

## Compatibilité

Un champ nouveau facultatif ne change pas `v1`. Tout le reste (champ retiré, champ rendu obligatoire, sens modifié, nouveau code) demande `v2`.
