import pytest

from portail.etats import Etat, etat_pipeline

E = Etat


@pytest.mark.parametrize(
    ("etats", "attendu"),
    [
        ([E.TERMINEE, E.ECHOUEE, E.EN_ATTENTE], E.ECHOUEE),
        ([E.TERMINEE, E.EN_ATTENTE], E.EN_ATTENTE),
        ([E.TERMINEE, E.TERMINEE], E.TERMINEE),
        ([E.TERMINEE, E.EN_COURS], E.EN_COURS),
        ([E.TERMINEE, E.A_FAIRE], E.EN_COURS),
        ([E.A_FAIRE, E.A_FAIRE], E.EN_COURS),
    ],
)
def test_etat_pipeline(etats, attendu):
    assert etat_pipeline(etats) == attendu
