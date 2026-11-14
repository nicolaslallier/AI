import httpx
import pytest

from orchestrateur import issue


@pytest.mark.parametrize(
    "ref",
    ["nicolaslallier/AI#15", "https://github.com/nicolaslallier/AI/issues/15", " https://github.com/nicolaslallier/AI/issues/15/ "],
)
def test_analyser(ref):
    assert issue.analyser(ref) == issue.RefIssue("nicolaslallier", "AI", 15)


@pytest.mark.parametrize("ref", ["AI#15", "nicolaslallier/AI", "https://github.com/nicolaslallier/AI/pull/15", "a/b#x"])
def test_analyser_refuse(ref):
    with pytest.raises(ValueError):
        issue.analyser(ref)


def client(reponse: dict, statut: int = 200, vus: list | None = None) -> httpx.Client:
    def gerer(requete: httpx.Request) -> httpx.Response:
        if vus is not None:
            vus.append(requete)
        return httpx.Response(statut, json=reponse)

    return httpx.Client(transport=httpx.MockTransport(gerer))


def test_lire(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "jeton")
    vus: list[httpx.Request] = []
    texte = issue.lire(issue.RefIssue("o", "d", 3), client({"title": "Titre", "body": "Corps"}, vus=vus))
    assert texte == "Issue o/d#3 : Titre\n\nCorps"
    assert vus[0].url.path == "/repos/o/d/issues/3"
    assert vus[0].headers["Authorization"] == "Bearer jeton"


def test_lire_sans_jeton_ni_corps(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    vus: list[httpx.Request] = []
    texte = issue.lire(issue.RefIssue("o", "d", 3), client({"title": "T", "body": None}, vus=vus))
    assert "(pas de description)" in texte
    assert "Authorization" not in vus[0].headers


def test_lire_refuse_une_pr():
    with pytest.raises(ValueError, match="pull request"):
        issue.lire(issue.RefIssue("o", "d", 3), client({"title": "T", "pull_request": {}}))


def test_lire_404():
    with pytest.raises(httpx.HTTPStatusError):
        issue.lire(issue.RefIssue("o", "d", 3), client({"message": "Not Found"}, statut=404))
