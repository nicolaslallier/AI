"""Tests pour les thèmes CSS : style.css doit contenir les quatre blocs [data-theme]."""

import re
from pathlib import Path

# Fichier source à vérifier
STYLE_CSS = Path(__file__).parents[2] / "frontend" / "src" / "style.css"

# Variables attendues dans chaque bloc de thème
VARIABLES_THEME = [
    "--fond",
    "--surface",
    "--creux",
    "--texte",
    "--discret",
    "--bord",
    "--accent",
    "--sur-accent",
    "--danger",
    "--alerte",
    "--succes",
]

# Thèmes attendus
THEMES = ["clair", "sombre", "high-contrast", "ocean"]


def _contenu() -> str:
    return STYLE_CSS.read_text()


def test_bloc_root_existe():
    """Le sélecteur :root doit exister."""
    contenu = _contenu()
    assert re.search(r":root\s*\{", contenu), ":root absent"


def test_root_ne_contient_pas_color_scheme_light_dark():
    """Le bloc :root ne doit plus contenir color-scheme: light dark."""
    contenu = _contenu()
    # Extraire le bloc :root (jusqu'à la prochaine accolade fermante de niveau 0)
    m = re.search(r":root\s*\{", contenu)
    assert m, ":root absent"
    # Trouver la fin du bloc :root
    debut = m.end() - 1
    profondeur = 0
    i = debut
    while i < len(contenu):
        if contenu[i] == "{":
            profondeur += 1
        elif contenu[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                break
        i += 1
    bloc_root = contenu[debut:i + 1]
    assert "light dark" not in bloc_root, (
        ":root contient encore 'color-scheme: light dark'"
    )


def test_themes_present():
    """Chaque sélecteur [data-theme='…'] doit être présent."""
    contenu = _contenu()
    for theme in THEMES:
        assert f'[data-theme="{theme}"]' in contenu, (
            f"[data-theme=\"{theme}\"] absent"
        )


def test_themes_variables():
    """Chaque bloc [data-theme] doit contenir toutes les variables."""
    contenu = _contenu()
    for theme in THEMES:
        # Extraire le bloc du thème
        pattern = re.escape(f'[data-theme="{theme}"]') + r"\s*\{"
        m = re.search(pattern, contenu)
        assert m, f"[data-theme=\"{theme}\"] absent"
        debut = m.end() - 1
        profondeur = 0
        i = debut
        while i < len(contenu):
            if contenu[i] == "{":
                profondeur += 1
            elif contenu[i] == "}":
                profondeur -= 1
                if profondeur == 0:
                    break
            i += 1
        bloc_theme = contenu[debut:i + 1]
        for var in VARIABLES_THEME:
            assert var in bloc_theme, f"Variable {var} manquante dans [data-theme=\"{theme}\"]"


def test_themes_color_scheme_clair():
    """Le thème clair doit avoir color-scheme: light."""
    contenu = _contenu()
    m = re.search(r'\[data-theme="clair"\]\s*\{', contenu)
    assert m, '[data-theme="clair"] absent'
    debut = m.end() - 1
    profondeur = 0
    i = debut
    while i < len(contenu):
        if contenu[i] == "{":
            profondeur += 1
        elif contenu[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                break
        i += 1
    bloc = contenu[debut:i + 1]
    assert "color-scheme: light" in bloc, (
        '[data-theme="clair"] doit contenir color-scheme: light'
    )


def test_themes_color_scheme_sombre():
    """Le thème sombre doit avoir color-scheme: dark."""
    contenu = _contenu()
    m = re.search(r'\[data-theme="sombre"\]\s*\{', contenu)
    assert m, '[data-theme="sombre"] absent'
    debut = m.end() - 1
    profondeur = 0
    i = debut
    while i < len(contenu):
        if contenu[i] == "{":
            profondeur += 1
        elif contenu[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                break
        i += 1
    bloc = contenu[debut:i + 1]
    assert "color-scheme: dark" in bloc, (
        '[data-theme="sombre"] doit contenir color-scheme: dark'
    )


def test_themes_color_scheme_high_contrast():
    """Le thème high-contrast doit avoir color-scheme: dark."""
    contenu = _contenu()
    m = re.search(r'\[data-theme="high-contrast"\]\s*\{', contenu)
    assert m, '[data-theme="high-contrast"] absent'
    debut = m.end() - 1
    profondeur = 0
    i = debut
    while i < len(contenu):
        if contenu[i] == "{":
            profondeur += 1
        elif contenu[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                break
        i += 1
    bloc = contenu[debut:i + 1]
    assert "color-scheme: dark" in bloc, (
        '[data-theme="high-contrast"] doit contenir color-scheme: dark'
    )


def test_themes_color_scheme_ocean():
    """Le thème ocean doit avoir color-scheme: dark."""
    contenu = _contenu()
    m = re.search(r'\[data-theme="ocean"\]\s*\{', contenu)
    assert m, '[data-theme="ocean"] absent'
    debut = m.end() - 1
    profondeur = 0
    i = debut
    while i < len(contenu):
        if contenu[i] == "{":
            profondeur += 1
        elif contenu[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                break
        i += 1
    bloc = contenu[debut:i + 1]
    assert "color-scheme: dark" in bloc, (
        '[data-theme="ocean"] doit contenir color-scheme: dark'
    )


def test_themes_ne_contiennent_pas_color_scheme_light_dark():
    """Aucun bloc [data-theme] ne doit contenir 'light dark'."""
    contenu = _contenu()
    for theme in THEMES:
        m = re.search(re.escape(f'[data-theme="{theme}"]') + r"\s*\{", contenu)
        assert m, f"[data-theme=\"{theme}\"] absent"
        debut = m.end() - 1
        profondeur = 0
        i = debut
        while i < len(contenu):
            if contenu[i] == "{":
                profondeur += 1
            elif contenu[i] == "}":
                profondeur -= 1
                if profondeur == 0:
                    break
            i += 1
        bloc = contenu[debut:i + 1]
        assert "light dark" not in bloc, (
            f"[data-theme=\"{theme}\"] ne doit pas contenir 'light dark'"
        )
