# Schémas XSD du format d'échange ArchiMate

Copies non modifiées, utilisées uniquement par les tests (`tests/test_archimate.py`) pour valider
hors ligne le fichier produit par `portail.archimate.xml_echange`.

| Fichier | Source |
| --- | --- |
| `archimate3_Model.xsd` | https://www.opengroup.org/xsd/archimate/3.1/archimate3_Model.xsd |
| `archimate3_View.xsd` | https://www.opengroup.org/xsd/archimate/3.1/archimate3_View.xsd |
| `archimate3_Diagram.xsd` | https://www.opengroup.org/xsd/archimate/3.1/archimate3_Diagram.xsd |
| `xml.xsd` | https://www.w3.org/2001/xml.xsd (importé par `archimate3_Model.xsd` pour `xml:lang`) |

Version 3.1 : la 3.2 n'est pas publiée à cet emplacement.

## Droits d'auteur

Les trois fichiers de l'Open Group ne portent aucun avis de droits d'auteur dans leur contenu
(seulement « Author: The Open Group ArchiMate Exchange Team »). L'avis figure sur la page
https://www.opengroup.org/xsd/archimate/ qui les publie :

> Copyright © 2015-2019 The Open Group, All Rights Reserved.
> ArchiMate® is a registered trademark of The Open Group

Cette page n'interdit pas la redistribution. `xml.xsd` est le schéma de l'espace de noms XML du W3C,
publié pour être importé par d'autres schémas ; il ne porte aucun avis.
