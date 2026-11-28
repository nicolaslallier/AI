import asyncio

from portail.arbitre import Arbitre, LLMArbitre


async def _ceder():
    for _ in range(5):
        await asyncio.sleep(0)


async def _tache(arbitre, modele, priorite, nom, ordre, libere=None):
    async with arbitre.tour(modele, priorite):
        ordre.append(nom)
        if libere:
            await libere.wait()


async def test_un_appel_a_la_fois_par_modele():
    a, ordre, fin = Arbitre(), [], asyncio.Event()
    t1 = asyncio.create_task(_tache(a, "m", "fond", "A", ordre, fin))
    await _ceder()
    t2 = asyncio.create_task(_tache(a, "m", "fond", "B", ordre))
    await _ceder()
    assert ordre == ["A"]
    fin.set()
    await asyncio.gather(t1, t2)
    assert ordre == ["A", "B"]


async def test_modeles_differents_en_parallele():
    a, ordre, fin = Arbitre(), [], asyncio.Event()
    t1 = asyncio.create_task(_tache(a, "m1", "fond", "A", ordre, fin))
    t2 = asyncio.create_task(_tache(a, "m2", "fond", "B", ordre, fin))
    await _ceder()
    assert sorted(ordre) == ["A", "B"]
    fin.set()
    await asyncio.gather(t1, t2)


async def test_interactif_passe_devant():
    a, ordre, fin = Arbitre(), [], asyncio.Event()
    ta = asyncio.create_task(_tache(a, "m", "fond", "A", ordre, fin))
    await _ceder()
    tb = asyncio.create_task(_tache(a, "m", "fond", "B", ordre))
    await _ceder()
    tc = asyncio.create_task(_tache(a, "m", "interactif", "C", ordre))
    await _ceder()
    fin.set()
    await asyncio.gather(ta, tb, tc)
    assert ordre == ["A", "C", "B"]


async def test_pas_de_famine():
    a, ordre, fin = Arbitre(), [], asyncio.Event()
    tenant = asyncio.create_task(_tache(a, "m", "interactif", "I0", ordre, fin))
    await _ceder()
    taches = [asyncio.create_task(_tache(a, "m", "fond", "F", ordre))]
    await _ceder()
    for i in range(1, 6):
        taches.append(asyncio.create_task(_tache(a, "m", "interactif", f"I{i}", ordre)))
        await _ceder()
    fin.set()
    await asyncio.gather(tenant, *taches)
    assert ordre == ["I0", "I1", "I2", "I3", "F", "I4", "I5"]  # le fond passe 4e après le tenant


async def test_annulation_libere_le_tour():
    a, ordre, fin = Arbitre(), [], asyncio.Event()
    tenant = asyncio.create_task(_tache(a, "m", "fond", "A", ordre, fin))
    await _ceder()
    attente = asyncio.create_task(_tache(a, "m", "interactif", "B", ordre))
    await _ceder()
    attente.cancel()
    fin.set()
    await tenant
    await asyncio.wait_for(_tache(a, "m", "fond", "C", ordre), 1)  # ne bloque pas
    # annulée pendant son tour
    t = asyncio.create_task(_tache(a, "m", "fond", "D", ordre, asyncio.Event()))
    await _ceder()
    t.cancel()
    await asyncio.wait_for(_tache(a, "m", "fond", "E", ordre), 1)
    assert ordre == ["A", "C", "D", "E"]


async def test_annulation_en_attente_puis_liberation_dans_la_meme_etape():
    a, ordre, debut = Arbitre(), [], asyncio.Event()
    attente = None

    async def tenant():
        async with a.tour("m", "fond"):
            await debut.wait()
            attente.cancel()  # puis sortie immédiate : la Future annulée est encore en file

    t = asyncio.create_task(tenant())
    await _ceder()
    attente = asyncio.create_task(_tache(a, "m", "interactif", "B", ordre))
    suivant = asyncio.create_task(_tache(a, "m", "interactif", "C", ordre))
    await _ceder()
    debut.set()
    await t  # le tenant ne doit pas échouer
    await asyncio.wait_for(suivant, 1)  # le suivant est réveillé
    await asyncio.gather(attente, return_exceptions=True)
    await asyncio.wait_for(_tache(a, "m", "fond", "D", ordre), 1)  # le modèle reste utilisable
    assert ordre == ["C", "D"]


async def test_annulation_apres_transmission_du_tour_le_rend():
    a, ordre, debut = Arbitre(), [], asyncio.Event()
    attente = None

    async def tenant():
        async with a.tour("m", "fond"):
            await debut.wait()
        attente.cancel()  # le tour vient d'être donné à B, qui n'a pas encore repris la main

    t = asyncio.create_task(tenant())
    await _ceder()
    attente = asyncio.create_task(_tache(a, "m", "interactif", "B", ordre))
    suivant = asyncio.create_task(_tache(a, "m", "interactif", "C", ordre))
    await _ceder()
    debut.set()
    await t
    await asyncio.wait_for(suivant, 1)
    await asyncio.gather(attente, return_exceptions=True)
    assert ordre == ["C"]
    await asyncio.wait_for(_tache(a, "m", "fond", "D", ordre), 1)


async def test_rafale_remise_a_zero_sans_fond_en_attente():
    a, ordre, fin = Arbitre(), [], asyncio.Event()
    stop = asyncio.Event()
    t0 = asyncio.create_task(_tache(a, "m", "interactif", "I0", ordre, fin))
    await _ceder()
    fond = asyncio.create_task(_tache(a, "m", "fond", "F", ordre))
    i1 = asyncio.create_task(_tache(a, "m", "interactif", "I1", ordre, stop))
    i2 = asyncio.create_task(_tache(a, "m", "interactif", "I2", ordre))
    await _ceder()
    fin.set()  # I1 prend le tour pendant que F attend : rafale = 1
    await _ceder()
    fond.cancel()
    stop.set()
    await asyncio.gather(t0, i1, i2, fond, return_exceptions=True)
    assert a._modeles["m"].rafale == 0 and a._modeles["m"].en_cours == 0


async def test_llm_arbitre_flux_tient_le_tour(faux_llm):
    fin = asyncio.Event()
    faux_llm.morceaux = ["a", fin]
    faux_llm.reponses = [{"content": "ok"}]
    arbitre = Arbitre()
    llm = LLMArbitre(faux_llm, arbitre, "interactif")
    lu = []

    async def lire():
        async for m in llm.flux("m", [], None):
            lu.append(m)

    t1 = asyncio.create_task(lire())
    await _ceder()
    t2 = asyncio.create_task(llm.completer("m", [], None))
    await _ceder()
    assert lu == ["a"] and not t2.done()
    fin.set()
    assert await t2 == {"content": "ok"}
    await t1


async def test_capacite_deux_appels_simultanes_par_modele():
    a, ordre, fin = Arbitre(capacite=2), [], asyncio.Event()
    t1 = asyncio.create_task(_tache(a, "m", "fond", "A", ordre, fin))
    t2 = asyncio.create_task(_tache(a, "m", "fond", "B", ordre, fin))
    await _ceder()
    t3 = asyncio.create_task(_tache(a, "m", "fond", "C", ordre))
    await _ceder()
    assert ordre == ["A", "B"]  # deux Macs : deux appels ; le troisième attend
    fin.set()
    await asyncio.gather(t1, t2, t3)
    assert ordre == ["A", "B", "C"]


async def test_capacite_deux_libere_une_place_a_la_fois():
    a, ordre = Arbitre(capacite=2), []
    fin_a, fin_b = asyncio.Event(), asyncio.Event()
    ta = asyncio.create_task(_tache(a, "m", "fond", "A", ordre, fin_a))
    tb = asyncio.create_task(_tache(a, "m", "fond", "B", ordre, fin_b))
    await _ceder()
    fin_d = asyncio.Event()
    tc = asyncio.create_task(_tache(a, "m", "fond", "C", ordre))
    td = asyncio.create_task(_tache(a, "m", "interactif", "D", ordre, fin_d))
    await _ceder()
    fin_a.set()
    await _ceder()
    assert ordre == ["A", "B", "D"]  # une place libre : l'interactif passe, C attend encore
    fin_b.set()
    await _ceder()
    assert ordre == ["A", "B", "D", "C"]
    fin_d.set()
    await asyncio.gather(ta, tb, tc, td)
    await asyncio.wait_for(_tache(a, "m", "fond", "E", ordre), 1)  # plus rien de tenu


def test_capacite_au_moins_un():
    import pytest

    with pytest.raises(ValueError):
        Arbitre(capacite=0)
