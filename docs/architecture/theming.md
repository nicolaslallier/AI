# Système de Thémisation

Ce document décrit le fonctionnement du système de thèmes CSS utilisé dans l'application.

## Approche

L'application utilise une approche de **thémisation explicite par attributs de données** (`data-theme`), complétée par un mécanisme de repli (fallback) pour la compatibilité.

### Gestion des thèmes

Le système repose sur l'attribut HTML `data-theme` appliqué sur un élément parent (généralement `<html>` ou `<body>`).

| Thème | Sélecteur CSS | `color-scheme` | Usage principal |
| :--- | :--- | :--- | :--- |
| **Clair** | `[data-theme="clair"]` | `light` | Interface standard lumineuse. |
| **Sombre** | `[data-theme="sombre"]` | `dark` | Interface sombre standard. |
| **High Contrast** | `[data-theme="high-contrast"]` | `dark` | Accessibilité (forts contrastes). |
| **Ocean** | `[data-theme="ocean"]` | `dark` | Thème coloré (bleu/cyan). |

## Variables CSS

Toutes les couleurs de l'interface sont pilotées par un jeu de variables CSS définies dans les blocs de thèmes.

### Variables de base (Core)
Ces variables sont obligatoirement présentes dans chaque thème :
- `--fond` : Couleur de l'arrière-plan principal.
- `--surface` : Couleur des conteneurs de premier niveau (cartes, menus).
- `--creux` : Couleur des éléments incrustés (inputs, zones de texte).
- `--texte` : Couleur du texte principal.
- `--discret` : Couleur du texte secondaire ou des éléments de faible importance.
- `--bord` : Couleur des bordures.
- `--accent` : Couleur de l'élément d'accentuation (boutons primaires, liens).
- `--sur-accent` : Couleur du texte sur l'élément d'accentuation.
- `--danger` : Couleur des états d'erreur ou de suppression.
- `--alerte` : Couleur des avertissements.
- `--succes` : Couleur des messages de succès.

## Compatibilité et Fallback

### Navigateurs modernes
Le navigateur utilise la valeur `color-scheme` déclarée dans le bloc `[data-theme]` pour adapter les éléments natifs (barres de défilement, boutons, etc.).

### Navigateurs anciens (Fallback)
Pour les navigateurs ne supportant pas les sélecteurs d'attributs complexes ou les nouvelles fonctionnalités CSS, le bloc `:root` contient les valeurs par défaut (équivalentes au thème **clair**). Cela garantit que l'application reste lisible même sans support des thèmes dynamiques.

## Implémentation technique

Les thèmes sont définis dans `frontend/src/style.css`. 

**Note de sécurité/accessibilité :** Chaque thème a été conçu pour respecter un ratio de contraste minimal de 4.5:1 pour le texte principal par rapport au fond.
