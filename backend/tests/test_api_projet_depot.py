import pytest

URL_OK = "https://github.com/nicolaslallier/EA"


async def test_projet_avec_depot(client):
    r = await client.post(
        "/api/projets", json={"nom": "P", "depot_url": URL_OK, "branche_ref": "main"}
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    d = (await client.get(f"/api/projets/{pid}")).json()
    assert d["depot_url"] == URL_OK
    assert d["branche_ref"] == "main"


async def test_projet_sans_depot(client):
    pid = (await client.post("/api/projets", json={"nom": "P"})).json()["id"]
    d = (await client.get(f"/api/projets/{pid}")).json()
    assert d["depot_url"] is None and d["branche_ref"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://gitlab.com/a/b",
        "https://github.com/a",
        "https://x:y@github.com/a/b",
        "file:///etc",
    ],
)
async def test_url_invalide_422(client, url):
    r = await client.post("/api/projets", json={"nom": "P", "depot_url": url})
    assert r.status_code == 422
    assert r.json()["detail"] == "URL de dépôt GitHub invalide"
    pid = (await client.post("/api/projets", json={"nom": "Q"})).json()["id"]
    r = await client.patch(f"/api/projets/{pid}", json={"depot_url": url})
    assert r.status_code == 422
    assert r.json()["detail"] == "URL de dépôt GitHub invalide"


async def test_patch_retire_le_depot(client):
    pid = (await client.post("/api/projets", json={"nom": "P", "depot_url": URL_OK})).json()["id"]
    r = await client.patch(f"/api/projets/{pid}", json={"depot_url": None})
    assert r.status_code == 200
    assert r.json()["depot_url"] is None


async def test_patch_partiel(client):
    pid = (
        await client.post(
            "/api/projets", json={"nom": "P", "depot_url": URL_OK, "branche_ref": "dev"}
        )
    ).json()["id"]
    r = await client.patch(f"/api/projets/{pid}", json={"nom": "  Neuf  "})
    d = r.json()
    assert (d["nom"], d["depot_url"], d["branche_ref"]) == ("Neuf", URL_OK, "dev")
    assert (await client.patch(f"/api/projets/{pid}", json={"nom": "  "})).status_code == 422
    assert (await client.patch(f"/api/projets/{pid}", json={"nom": None})).status_code == 422


async def test_patch_projet_inconnu(client):
    assert (await client.patch("/api/projets/999", json={"nom": "x"})).status_code == 404
