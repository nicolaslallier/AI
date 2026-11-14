import base64
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from portail.github import ErreurGitHub, GitHubApp, depot_depuis_url

_CLE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = _CLE.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
CLE_B64 = base64.b64encode(PEM).decode()
PUB = _CLE.public_key()


class Horloge:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _app(gestionnaire, horloge=None):
    return GitHubApp(
        "123", CLE_B64, transport=httpx.MockTransport(gestionnaire), horloge=horloge or Horloge()
    )


def _expire(horloge, delta):
    import datetime as dt

    return dt.datetime.fromtimestamp(horloge.t + delta, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_depot_depuis_url():
    assert depot_depuis_url("https://github.com/a/b.git") == "a/b"
    assert depot_depuis_url("https://github.com/a/b") == "a/b"
    with pytest.raises(ErreurGitHub):
        depot_depuis_url("https://gitlab.com/a/b")


async def test_jeton_cache_et_renouvele():
    h = Horloge()
    appels = []

    def g(req):
        appels.append((req.method, req.url.path))
        if req.url.path == "/repos/a/b/installation":
            return httpx.Response(200, json={"id": 7})
        n = sum(1 for m, p in appels if m == "POST")
        return httpx.Response(201, json={"token": f"tok{n}", "expires_at": _expire(h, 3600)})

    app = _app(g, h)
    assert await app.jeton("a/b") == "tok1"
    h.t += 3000  # reste 600 s : encore valide
    assert await app.jeton("a/b") == "tok1"
    h.t += 400  # reste 200 s < 5 min : renouvelé
    assert await app.jeton("a/b") == "tok2"
    assert ("POST", "/app/installations/7/access_tokens") in appels


async def test_jwt_valide():
    h = Horloge()
    vus = []

    def g(req):
        vus.append(req)
        if req.url.path.endswith("/installation"):
            return httpx.Response(200, json={"id": 7})
        return httpx.Response(201, json={"token": "t", "expires_at": _expire(h, 3600)})

    await _app(g, h).jeton("a/b")
    for r in vus:
        assert r.headers["x-github-api-version"] == "2022-11-28"
        jeton = r.headers["authorization"].removeprefix("Bearer ")
        c = jwt.decode(
            jeton, PUB, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
        )
        assert c == {"iat": int(h.t) - 60, "exp": int(h.t) + 540, "iss": "123"}


def _app_repo(reponse):
    def g(req):
        if req.url.path.endswith("/installation"):
            return httpx.Response(200, json={"id": 7})
        if req.method == "POST" and "access_tokens" in req.url.path:
            return httpx.Response(201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"})
        assert req.headers["authorization"] == "Bearer tok"
        return reponse(req)

    return _app(g)


async def test_branche_protegee_vrai_faux_erreur():
    vus = []

    def rep(req):
        vus.append(req.url.raw_path.decode())
        if "main" in req.url.path or "feat" in req.url.path:
            return httpx.Response(200, json={"protected": True})
        if "dev" in req.url.path:
            return httpx.Response(200, json={"protected": False})
        if "bad" in req.url.path:
            return httpx.Response(200, content=b"pas du json")
        raise httpx.ConnectError("boum")

    app = _app_repo(rep)
    assert await app.branche_protegee("a/b", "main") is True
    assert await app.branche_protegee("a/b", "dev") is False
    with pytest.raises(ErreurGitHub):
        await app.branche_protegee("a/b", "bad")
    with pytest.raises(ErreurGitHub):
        await app.branche_protegee("a/b", "autre")
    await app.branche_protegee("a/b", "feat/x")
    assert vus[-1] == "/repos/a/b/branches/feat%2Fx"


async def test_depot_invalide():
    app = _app_repo(lambda r: httpx.Response(200, json={}))
    for d in ["a", "a/../b", "a/b/c", "../x"]:
        with pytest.raises(ErreurGitHub):
            await app.branche_defaut(d)


async def test_branche_defaut_et_erreur_http():
    app = _app_repo(
        lambda r: (
            httpx.Response(200, json={"default_branch": "main"})
            if r.url.path == "/repos/a/b"
            else httpx.Response(404, json={"message": "Not Found"})
        )
    )
    assert await app.branche_defaut("a/b") == "main"
    with pytest.raises(ErreurGitHub):
        await app.branche_defaut("a/c")


async def test_statut_et_message_assaini():
    reponses = {
        "/repos/a/b": httpx.Response(503, text="<html>" + "x" * 5000),
        "/repos/a/c": httpx.Response(
            422, json={"message": "Validation\nFailed " + "y" * 500, "doc": "secret"}
        ),
        "/repos/a/e": httpx.Response(200, json={}),
    }

    def rep(req):
        if req.url.path == "/repos/a/d":
            raise httpx.ConnectError("boum")
        return reponses[req.url.path]

    app = _app_repo(rep)
    with pytest.raises(ErreurGitHub) as e:
        await app.branche_defaut("a/b")
    assert e.value.statut == 503 and e.value.transitoire
    assert "<html>" not in str(e.value) and len(str(e.value)) < 200
    with pytest.raises(ErreurGitHub) as e:
        await app.branche_defaut("a/c")
    assert e.value.statut == 422 and not e.value.transitoire
    assert "Validation Failed" in str(e.value) and "secret" not in str(e.value)
    assert "\n" not in str(e.value) and len(str(e.value)) < 200
    with pytest.raises(ErreurGitHub) as e:
        await app.branche_defaut("a/d")
    assert e.value.statut is None and e.value.transitoire
    with pytest.raises(ErreurGitHub) as e:  # réponse inattendue : pas transitoire
        await app.branche_defaut("a/e")
    assert not e.value.transitoire
    assert ErreurGitHub("x", 429).transitoire and not ErreurGitHub("x").transitoire


async def test_creer_pr_draft():
    corps = {}

    def rep(req):
        corps.update(json.loads(req.content))
        assert req.url.path == "/repos/a/b/pulls"
        return httpx.Response(201, json={"number": 5, "html_url": "https://github.com/a/b/pull/5"})

    app = _app_repo(rep)
    assert await app.creer_pr("a/b", "feat", "main", "T", "C") == (
        5,
        "https://github.com/a/b/pull/5",
    )
    assert corps == {"title": "T", "body": "C", "head": "feat", "base": "main", "draft": True}


async def test_etat_pr():
    donnees = {
        1: {"state": "open", "merged": False},
        2: {"state": "closed", "merged": True},
        3: {"state": "closed", "merged": False},
        4: {"state": "bizarre"},
    }
    app = _app_repo(lambda r: httpx.Response(200, json=donnees[int(r.url.path.split("/")[-1])]))
    assert await app.etat_pr("a/b", 1) == "ouverte"
    assert await app.etat_pr("a/b", 2) == "fusionnee"
    assert await app.etat_pr("a/b", 3) == "fermee"
    with pytest.raises(ErreurGitHub):
        await app.etat_pr("a/b", 4)


async def test_commenter_et_fermer():
    vus = []

    def rep(req):
        vus.append((req.method, req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={})

    app = _app_repo(rep)
    await app.commenter("a/b", 3, "salut")
    await app.fermer_pr("a/b", 3)
    assert vus == [
        ("POST", "/repos/a/b/issues/3/comments", {"body": "salut"}),
        ("PATCH", "/repos/a/b/pulls/3", {"state": "closed"}),
    ]


def test_cle_base64_invalide_erreur_claire():
    with pytest.raises(ErreurGitHub, match="clé"):
        GitHubApp("1", "pas du base64 !!")
    with pytest.raises(ErreurGitHub, match="clé"):
        GitHubApp("1", base64.b64encode(b"pas une cle").decode())


def _app_lecture(donnees):
    """App dont GET /pulls|issues renvoie `donnees(req)` ; enregistre les requêtes de lecture."""
    vues = []

    def g(req):
        if req.url.path == "/repos/a/b/installation":
            return httpx.Response(200, json={"id": 7})
        if req.url.path == "/app/installations/7/access_tokens":
            return httpx.Response(201, json={"token": "t", "expires_at": "2099-01-01T00:00:00Z"})
        vues.append(req)
        return httpx.Response(200, json=donnees(req))

    return _app(g), vues


def _revue(i, **kw):
    return {
        "id": i, "user": {"login": "n", "type": "User"}, "body": "ok", "state": "COMMENTED",
        "submitted_at": "2026-11-14T10:00:00Z", "html_url": f"https://x/{i}",
    } | kw  # fmt: skip


def _com(i, **kw):
    return {
        "id": i, "user": {"login": "n", "type": "User"}, "body": "x",
        "created_at": "2026-11-14T10:00:00Z", "html_url": f"https://x/{i}",
    } | kw  # fmt: skip


async def test_revues_paginees():
    app, vues = _app_lecture(
        lambda r: [_revue(i) for i in range(100)] if r.url.params["page"] == "1" else [_revue(100)]
    )
    assert len(await app.revues("a/b", 7)) == 101
    assert [r.url.params["per_page"] for r in vues] == ["100", "100"]


async def test_revue_pending_ignoree():
    app, _ = _app_lecture(lambda r: [_revue(1), _revue(2, state="PENDING", submitted_at=None)])
    res = await app.revues("a/b", 7)
    assert [c.id for c in res] == [1]
    assert res[0].type == "revue" and res[0].etat_revue == "COMMENTED"


async def test_commentaire_ligne_champs():
    app, vues = _app_lecture(
        lambda r: [_com(5, path="a.py", line=None, original_line=12, pull_request_review_id=9)]
    )
    (c,) = await app.commentaires_ligne("a/b", 7)
    assert (c.chemin, c.ligne, c.revue_id, c.type) == ("a.py", 12, 9, "ligne")
    assert vues[0].url.path == "/repos/a/b/pulls/7/comments"


async def test_commentaire_conversation_bot():
    app, vues = _app_lecture(lambda r: [_com(1, user={"login": "bot", "type": "Bot"})])
    (c,) = await app.commentaires_conversation("a/b", 7)
    assert c.auteur_type == "Bot" and c.type == "conversation"
    assert vues[0].url.path == "/repos/a/b/issues/7/comments"


async def test_repondre_ligne_route():
    vues = []

    def g(req):
        if req.url.path == "/repos/a/b/installation":
            return httpx.Response(200, json={"id": 7})
        if req.url.path == "/app/installations/7/access_tokens":
            return httpx.Response(201, json={"token": "t", "expires_at": "2099-01-01T00:00:00Z"})
        vues.append(req)
        return httpx.Response(201, json={})

    await _app(g).repondre_ligne("a/b", 7, 123, "fait")
    assert vues[0].method == "POST"
    assert vues[0].url.path == "/repos/a/b/pulls/7/comments/123/replies"
    assert json.loads(vues[0].content) == {"body": "fait"}


async def test_champ_manquant_erreur():
    app, _ = _app_lecture(lambda r: [_com(1) | {"user": None}])
    with pytest.raises(ErreurGitHub):
        await app.commentaires_conversation("a/b", 7)
