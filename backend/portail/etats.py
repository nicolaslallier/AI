from enum import StrEnum


class Etat(StrEnum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    EN_ATTENTE = "en_attente"
    TERMINEE = "terminee"
    ECHOUEE = "echouee"


def etat_pipeline(etats: list[Etat]) -> Etat:
    if Etat.ECHOUEE in etats:
        return Etat.ECHOUEE
    if Etat.EN_ATTENTE in etats:
        return Etat.EN_ATTENTE
    if all(e == Etat.TERMINEE for e in etats):
        return Etat.TERMINEE
    return Etat.EN_COURS
