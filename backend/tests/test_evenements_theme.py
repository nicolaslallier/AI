"""Le bus SSE doit transmettre un événement de type 'theme' avec son payload.

Critères d'acceptation :
- bus.emettre('theme', {'nom': 'sombre'}) ne lève pas d'erreur ;
- un client SSE connecté reçoit l'événement de type 'theme' avec le payload correct ;
- l'annotation de type (si présente) inclut 'theme'.
"""

import asyncio
import json

import pytest

from portail.evenements import Bus, Signal, bus, flux


def _vider(file):
    sortie = []
    while not file.empty():
        sortie.append(file.get_nowait())
    return sortie


async def test_emettre_theme_ne_leve_pas():
    """bus.emettre('theme', payload) doit exister et ne rien lever."""
    b = Bus()
    file = b.abonner()
    try:
        b.emettre("theme", {"nom": "sombre"})
    finally:
        b.desabonner(file)


async def test_emettre_theme_diffuse_le_payload():
    """L'événement 'theme' doit arriver aux abonnés avec son payload intact."""
    b = Bus()
    file = b.abonner()
    try:
        b.emettre("theme", {"nom": "sombre"})
        signaux = _vider(file)
    finally:
        b.desabonner(file)
    assert ("theme", {"nom": "sombre"}) in signaux


async def test_flux_relaye_theme_avec_payload():
    """Le flux SSE doit transmettre l'événement 'theme' avec son payload."""
    b = Bus()
    it = flux(b)
    tache = asyncio.ensure_future(anext(it))
    await asyncio.sleep(0)
    b.emettre("theme", {"nom": "sombre"})
    ligne = await asyncio.wait_for(tache, 5)
    await it.aclose()
    assert ligne == 'event: theme\ndata: {"nom": "sombre"}\n\n'


async def test_flux_theme_via_route(client):
    """Un client SSE connecté à /api/evenements reçoit l'événement 'theme'."""
    get = asyncio.create_task(client.get("/api/evenements"))
    # Attendre que le client soit bien abonné au bus global.
    for _ in range(500):
        if bus.abonnes:
            break
        await asyncio.sleep(0.01)
    else:
        get.cancel()
        raise AssertionError("le client ne s'est pas abonné au bus")

    bus.emettre("theme", {"nom": "sombre"})
    r = await asyncio.wait_for(get, 5)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert 'event: theme' in r.text
    assert json.loads(r.text.split("data: ", 1)[1].split("\n", 1)[0]) == {"nom": "sombre"}


def test_annotation_inclut_theme():
    """Si l'annotation de type est stricte, 'theme' doit y figurer."""
    import typing

    origin = typing.get_origin(Signal)
    if origin is None:
        pytest.skip("Signal n'est pas un alias de type paramétré")
    args = typing.get_args(Signal)
    assert "theme" in args
