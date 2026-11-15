import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from portail.missions import (
    DemandeMission,
    DemandeModele,
    DemandeOutil,
    LigneMission,
    ReponseModele,
    ReponseOutil,
    Sante,
)

EXEMPLES = json.loads((Path(__file__).parents[2] / "docs/agents-contrat-v1.json").read_text())


def test_exemples_du_contrat():
    DemandeMission.model_validate(EXEMPLES["mission"])
    lignes = TypeAdapter(LigneMission)
    for cle in ("ligne_texte", "ligne_fin", "ligne_erreur"):
        lignes.validate_python(EXEMPLES[cle])
    DemandeModele.model_validate(EXEMPLES["demande_modele"])
    ReponseModele.model_validate(EXEMPLES["reponse_modele"])
    for ligne in EXEMPLES["demande_modele_flux_lignes"]:
        assert ligne["type"] in ("texte", "fin", "erreur")
    DemandeOutil.model_validate(EXEMPLES["demande_outil"])
    ReponseOutil.model_validate(EXEMPLES["reponse_outil"])
    Sante.model_validate(EXEMPLES["sante"])
    assert isinstance(EXEMPLES["erreur"]["erreur"], str)


@pytest.mark.parametrize("extra", [{"model": "gpt-x"}, {"tools": []}])
def test_demande_modele_refuse_les_champs_inconnus(extra):
    with pytest.raises(ValidationError):
        DemandeModele.model_validate({"messages": [], **extra})
