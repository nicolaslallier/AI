import json
import subprocess
from pathlib import Path

import pytest

from portail.contexte import estimer_jetons
from portail.outils import OutilsDepot, apercu


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    r = tmp_path / "arbre"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return r


def valider(racine: Path) -> OutilsDepot:
    """Commite (pour que git grep voie les fichiers) et renvoie les outils."""
    subprocess.run(["git", "add", "-A"], cwd=racine, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        cwd=racine,
        check=True,
    )
    return OutilsDepot(racine)


def test_lire_simple(racine):
    (racine / "a.txt").write_text("bonjour\n")
    assert OutilsDepot(racine).lire("a.txt") == "bonjour"


def test_lire_plage_de_lignes(racine):
    (racine / "a.txt").write_text("1\n2\n3\n4\n")
    assert OutilsDepot(racine).lire("a.txt", debut=2, fin=3) == "2\n3"


def test_lire_tronque_par_lignes(racine):
    (racine / "a.txt").write_text("\n".join(str(i) for i in range(2500)))
    sortie = OutilsDepot(racine).lire("a.txt")
    assert sortie.endswith(
        "[… tronqué : lignes 1–2000 sur 2500 ; suite : lire('a.txt', debut=2001)]"
    )
    assert "1999" in sortie
    assert "\n2000\n" not in sortie


def test_lire_ligne_geante_tronquee_par_octets(racine):
    (racine / "min.js").write_text("x" * 5_000_000)
    assert len(OutilsDepot(racine).lire("min.js").encode()) <= 100_000


@pytest.mark.parametrize(
    "chemin", ["../x", "/etc/passwd", ".git/config", "sous/../../x", "lien/passwd"]
)
def test_chemins_interdits(racine, chemin):
    (racine / "lien").symlink_to("/etc")
    assert OutilsDepot(racine).lire(chemin) == "erreur : chemin interdit"


@pytest.mark.parametrize("nom", [".env", ".env.prod", "cle.pem", "a/b/serveur.key", "id_rsa"])
async def test_secrets_refuses(racine, nom):
    f = racine / nom
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("MOTSECRETUNIQUE\n")
    (racine / "ok.txt").write_text("rien\n")
    outils = valider(racine)
    assert outils.lire(nom).startswith("erreur : ")
    assert "MOTSECRETUNIQUE" not in await outils.chercher("MOTSECRETUNIQUE")
    assert Path(nom).name not in outils.lister(".")


def test_binaire_refuse(racine):
    (racine / "b.bin").write_bytes(b"abc\0def")
    assert OutilsDepot(racine).lire("b.bin").startswith("erreur : ")


def test_lister_profondeur_et_plafond(racine):
    (racine / "a" / "b" / "c").mkdir(parents=True)
    (racine / "a" / "b" / "c" / "profond.txt").write_text("x")
    (racine / "a" / "b" / "mi.txt").write_text("x")
    sortie = OutilsDepot(racine).lister(".")
    assert sortie == "a/\na/b/"
    for i in range(400):
        (racine / f"f{i:03}.txt").write_text("x")
    sortie = OutilsDepot(racine).lister(".")
    assert sortie.count("\n") <= 300  # 300 entrées + la mention
    assert "tronquée" in sortie


async def test_chercher_trouve_et_plafonne(racine):
    (racine / "a.txt").write_text("aiguille\nfoin\n")
    (racine / "m.txt").write_text("tas\n" * 150)
    outils = valider(racine)
    assert await outils.chercher("aiguille") == "a.txt:1:aiguille"
    assert await outils.chercher("zzz") == "aucun résultat"
    sortie = await outils.chercher("tas", "m.txt")
    assert sortie.splitlines()[-1] == "[… 150 résultats au total]"
    assert len(sortie.splitlines()) == 101


async def test_chercher_motif_invalide(racine):
    (racine / "a.txt").write_text("x\n")
    outils = valider(racine)
    assert (await outils.chercher("(")).startswith("erreur : motif invalide")


async def test_executer_mal_forme(racine):
    outils = OutilsDepot(racine)
    assert (await outils.executer("lire", "pas du json"))[1] is True
    assert (await outils.executer("ecrire", "{}"))[1] is True
    assert (await outils.executer("lire", "{}"))[1] is True
    assert await outils.executer("lire", json.dumps({"chemin": "../x"})) == (
        "erreur : chemin interdit",
        False,
    )


def test_apercu_respecte_le_budget(racine):
    (racine / "README.md").write_text("y" * 100_000)
    (racine / "src.py").write_text("x")
    sortie = apercu(racine, 500)
    assert estimer_jetons([{"content": sortie}]) <= 500
    assert "src.py" in sortie
    assert sortie.endswith("[… tronqué]")


async def test_executer_ne_leve_jamais(racine):
    (racine / "a.txt").write_text("x\n")
    outils = valider(racine)
    for nom, args in [
        ("lire", {"chemin": "a\0b"}),
        ("chercher", {"motif": "a\0b"}),
        ("lister", {"chemin": "a.txt"}),
        ("lire", {"chemin": 5}),
        ("chercher", {"motif": 5}),
    ]:
        texte, mal = await outils.executer(nom, json.dumps(args))
        assert texte.startswith("erreur : ") and mal is False, (nom, args, texte)


async def test_debut_fin_de_mauvais_type_pas_mal_forme(racine):
    (racine / "a.txt").write_text("x\n")
    texte, mal = await OutilsDepot(racine).executer("lire", '{"chemin": "a.txt", "debut": "2"}')
    assert texte == "erreur : debut et fin doivent être des entiers" and mal is False


async def test_traversee_par_lister_et_chercher(racine):
    (racine / "a.txt").write_text("x\n")
    outils = valider(racine)
    assert outils.lister("../") == "erreur : chemin interdit"
    assert await outils.chercher("x", "../") == "erreur : chemin interdit"
    assert await outils.chercher("x", ".git") == "erreur : chemin interdit"


def test_lien_vers_secret_refuse(racine):
    (racine / ".env").write_text("S=1\n")
    (racine / "x").symlink_to(".env")
    assert OutilsDepot(racine).lire("x").startswith("erreur : ")


def test_lire_gros_fichier_marque_partiel(racine):
    (racine / "g.txt").write_text("ligne\n" * 600_000)
    assert "au moins" in OutilsDepot(racine).lire("g.txt")


@pytest.mark.parametrize("nom", [".ENV", "Cle.PEM", ".env/x", "secrets.pem/y.txt", "A/.Env.Prod"])
async def test_secrets_casse_et_dossiers(racine, nom):
    f = racine / nom
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("MOTSECRETUNIQUE\n")
    (racine / "ok.txt").write_text("rien\n")
    outils = valider(racine)
    assert outils.lire(nom).startswith("erreur : ")
    assert "MOTSECRETUNIQUE" not in await outils.chercher("MOTSECRETUNIQUE")
    assert "MOTSECRETUNIQUE" not in await outils.chercher("MOTSECRETUNIQUE", Path(nom).parts[0])
    assert ".env" not in outils.lister(".").casefold()
    assert "cle.pem" not in outils.lister(".").casefold()
    assert "secrets.pem" not in outils.lister(".").casefold()


def test_git_en_majuscules_interdit(racine):
    assert OutilsDepot(racine).lire(".Git/config") == "erreur : chemin interdit"


async def test_chercher_coupe_tot_sur_gros_resultat(racine):
    (racine / "m.txt").write_text("tas\n" * 5000)
    outils = valider(racine)
    sortie = await outils.chercher("tas")
    assert sortie.splitlines()[-1].startswith("[… plus de ")
    assert len(sortie.splitlines()) == 101


async def test_json_trop_imbrique_est_mal_forme(racine):
    assert (await OutilsDepot(racine).executer("lire", "[" * 100_000))[1] is True


async def test_chercher_ligne_geante(racine):
    (racine / "g.txt").write_text("tas" * 500_000 + "\n")
    sortie = await valider(racine).chercher("tas")
    assert sortie == "[… résultats tronqués]"


def test_lire_plafond_explicite_et_suite_sans_trou(racine):
    lignes = [f"ligne {i}" for i in range(1, 3001)]
    (racine / "a.txt").write_text("\n".join(lignes) + "\n")
    o = OutilsDepot(racine, max_octets=2000)
    lu, debut = [], 1
    while True:
        sortie = o.lire("a.txt", debut=debut)
        assert len(sortie.encode()) <= 2000
        corps, _, marque = sortie.rpartition("\n[… tronqué : ")
        if not marque.startswith("lignes"):
            lu += sortie.split("\n")
            break
        assert "sur 3000" in marque
        lu += corps.split("\n")
        debut = int(marque.rsplit("debut=", 1)[1].rstrip(")]"))
        o._demandes.clear()
    assert lu == lignes


async def test_troisieme_demande_identique_refusee(racine):
    (racine / "a.txt").write_text("bonjour\n")
    o = OutilsDepot(racine, max_octets=32768)
    args = json.dumps({"chemin": "a.txt"})
    assert await o.executer("lire", args) == ("bonjour", False)
    assert await o.executer("lire", '{ "chemin" : "a.txt" }') == ("bonjour", False)
    texte, mal = await o.executer("lire", args)
    assert texte.startswith("déjà lu deux fois") and mal is False
    assert (await o.executer("lire", json.dumps({"chemin": "a.txt", "debut": 1})))[0] == "bonjour"


async def test_sans_plafond_pas_de_dedoublonnage(racine):
    (racine / "a.txt").write_text("bonjour\n")
    o = OutilsDepot(racine)
    for _ in range(4):
        assert await o.executer("lire", '{"chemin": "a.txt"}') == ("bonjour", False)


async def test_chercher_plafonne(racine):
    for i in range(50):
        (racine / f"f{i}.txt").write_text("cible " * 50 + "\n")
    valider(racine)
    o = OutilsDepot(racine, max_octets=1000)
    texte, _ = await o.executer("chercher", '{"motif": "cible"}')
    assert len(texte.encode()) <= 1000
    assert texte.endswith("[… tronqué : précise le motif ou le chemin]")
