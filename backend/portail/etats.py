from enum import StrEnum


class Etat(StrEnum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    EN_ATTENTE = "en_attente"
    TERMINEE = "terminee"
    ECHOUEE = "echouee"


# Erreurs d'étape d'un arrêt voulu : le pipeline échoue sans que le code ait raté (hors alerte).
ANNULE = "annulé"
REPRISE_ABANDONNEE = "tâche déplacée avant la reprise"


def etat_pipeline(etats: list[Etat]) -> Etat:
    if Etat.ECHOUEE in etats:
        return Etat.ECHOUEE
    if Etat.EN_ATTENTE in etats:
        return Etat.EN_ATTENTE
    if all(e == Etat.TERMINEE for e in etats):
        return Etat.TERMINEE
    return Etat.EN_COURS
