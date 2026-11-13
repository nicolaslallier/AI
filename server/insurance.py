"""PDF d'assurance -> note de ressource. Extraction par règles simples (pas de LLM)."""
import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

GABARIT = "06 - Modèles/Modèle - Note de ressource.md"
MAX_PDF = 20 * 2**20  # ponytail: au-delà, pas d'extraction (une police fait quelques Ko) ; relever si besoin
MOTS = ("assur", "police", "prime")
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b")
MONTANT = re.compile(r"\d{1,3}(?:[  ]\d{3})*(?:[.,]\d{2})?[  ]*[$€]")
ASSUREUR = re.compile(r"assureur\s*:\s*(.+)", re.I)
NUMERO = re.compile(r"(?:num[ée]ro\s+de\s+police|police\s*(?:n[o°º]|#))\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-/]*)", re.I)


@dataclass
class Police:
    assureur: str | None = None
    numero: str | None = None
    debut: str | None = None
    fin: str | None = None
    montants: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def parse_police(texte: str) -> Police | None:
    n = _norm(texte)
    if sum(m in n for m in MOTS) < 2:
        return None
    a, num, dates = ASSUREUR.search(texte), NUMERO.search(texte), DATE.findall(texte)
    return Police(
        assureur=a.group(1).strip() if a else None,
        numero=num.group(1) if num else None,
        debut=dates[0] if dates else None,
        fin=dates[1] if len(dates) > 1 else None,
        montants=[re.sub(r"\s+", " ", m).replace(" ", " ") for m in MONTANT.findall(texte)],
    )


def masquer(numero: str) -> str:
    return "****" + numero[-4:] if len(numero) > 4 else "****"


def texte_pdf(src: bytes | Path) -> str:
    """Texte du PDF ; toute erreur (PDF malformé, trop gros) = "" = pas une police."""
    try:
        from pypdf import PdfReader

        if (len(src) if isinstance(src, bytes) else src.stat().st_size) > MAX_PDF:
            return ""
        r = PdfReader(io.BytesIO(src) if isinstance(src, bytes) else str(src))
        return "\n".join(p.extract_text() or "" for p in r.pages)
    except Exception:
        return ""


def note_police(p: Police, gabarit: str, nom_pdf: str) -> str:
    """Remplit le modèle. Le numéro n'apparaît que masqué."""
    titre = f"Police {p.assureur}" if p.assureur else "Police d'assurance"
    points = [
        ("Assureur", p.assureur),
        ("Numéro de police", masquer(p.numero) if p.numero else None),
        ("Date d'effet", p.debut),
        ("Échéance", p.fin),
        ("Montants", ", ".join(p.montants) or None),
    ]
    pts = "\n".join(f"- {k} : {v}" for k, v in points if v)
    note = gabarit.replace("\n# Titre", f"\n# {titre}", 1)
    note = note.replace("source:", f"source: {nom_pdf}", 1)
    note = note.replace("## Résumé", f"## Résumé\n\nPolice d'assurance extraite de {nom_pdf}.", 1)
    note = note.replace("## Points clés", f"## Points clés\n\n{pts}", 1)
    return note.rstrip("\n").replace("## Liens", f"## Liens\n\n![[{nom_pdf}]]", 1) + "\n"
