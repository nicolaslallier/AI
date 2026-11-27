"""La configuration admin_emails : lecture depuis l'environnement et garde admin.

- `PORTAIL_ADMIN_EMAILS` (chaîne séparée par des virgules) remplit `Reglages.admin_emails`.
- Valeur vide ou absente : liste vide.
- En mode local (`exiger_utilisateur=False`), la garde admin renvoie True pour tout utilisateur.
- Un test unitaire vérifie le parsing de la chaîne.
"""

from portail.config import Reglages
from tests.conftest import URL


def _reglages(**kw):
    return Reglages(database_url=URL, **kw)


# --- parsing de la chaîne (test unitaire) --------------------------------


def test_parsing_chaine_virgules():
    # Critère : 'a@x.fr,b@x.fr' produit ['a@x.fr', 'b@x.fr'].
    r = _reglages(admin_emails="a@x.fr,b@x.fr")
    assert r.admin_emails == ["a@x.fr", "b@x.fr"]


def test_parsing_chaine_vide():
    # Critère : valeur vide produit une liste vide.
    r = _reglages(admin_emails="")
    assert r.admin_emails == []


def test_parsing_chaine_absente():
    # Critère : valeur absente produit une liste vide.
    r = _reglages()
    assert r.admin_emails == []


def test_parsing_chaine_espaces():
    # Les espaces autour des adresses sont tolérés et ignorés.
    r = _reglages(admin_emails=" a@x.fr , b@x.fr ")
    assert r.admin_emails == ["a@x.fr", "b@x.fr"]


def test_parsing_chaine_un_element():
    r = _reglages(admin_emails="seul@x.fr")
    assert r.admin_emails == ["seul@x.fr"]


# --- lecture depuis l'environnement --------------------------------------


def test_lecture_environnement(monkeypatch):
    # Critère : PORTAIL_ADMIN_EMAILS='a@x.fr,b@x.fr' produit ['a@x.fr', 'b@x.fr'].
    monkeypatch.setenv("PORTAIL_ADMIN_EMAILS", "a@x.fr,b@x.fr")
    r = Reglages(database_url=URL)
    assert r.admin_emails == ["a@x.fr", "b@x.fr"]


def test_environnement_vide(monkeypatch):
    monkeypatch.setenv("PORTAIL_ADMIN_EMAILS", "")
    r = Reglages(database_url=URL)
    assert r.admin_emails == []


def test_environnement_absent(monkeypatch):
    monkeypatch.delenv("PORTAIL_ADMIN_EMAILS", raising=False)
    r = Reglages(database_url=URL)
    assert r.admin_emails == []


# --- garde admin ---------------------------------------------------------


def _garde():
    """La garde admin, où qu'elle vive dans le portail."""
    from portail import config

    return config.est_admin


def test_garde_mode_local_tout_utilisateur():
    # Critère : en mode local, la garde renvoie True pour tout utilisateur.
    garde = _garde()
    r = _reglages(exiger_utilisateur=False, admin_emails=["a@x.fr"])
    assert garde(r, "n'importe-qui@exemple.net") is True
    assert garde(r, "local") is True
    assert garde(r, "") is True


def test_garde_mode_local_sans_admins():
    garde = _garde()
    r = _reglages(exiger_utilisateur=False)
    assert garde(r, "quiconque@exemple.net") is True


def test_garde_mode_produit_admin():
    garde = _garde()
    r = _reglages(exiger_utilisateur=True, admin_emails=["a@x.fr", "b@x.fr"])
    assert garde(r, "a@x.fr") is True
    assert garde(r, "b@x.fr") is True


def test_garde_mode_produit_non_admin():
    garde = _garde()
    r = _reglages(exiger_utilisateur=True, admin_emails=["a@x.fr"])
    assert garde(r, "intrus@exemple.net") is False


def test_garde_mode_produit_sans_admins():
    # En mode produit sans admin configuré, personne n'est admin.
    garde = _garde()
    r = _reglages(exiger_utilisateur=True)
    assert garde(r, "n'importe-qui@exemple.net") is False
