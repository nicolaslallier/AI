"""Lecture d'une issue GitHub pour en faire la demande de l'orchestrateur."""

import os
import re
from dataclasses import dataclass

import httpx

_COURT = re.compile(r"^(?P<proprio>[\w.-]+)/(?P<depot>[\w.-]+)#(?P<numero>\d+)$")
_URL = re.compile(r"^https://github\.com/(?P<proprio>[\w.-]+)/(?P<depot>[\w.-]+)/issues/(?P<numero>\d+)/?$")


@dataclass(frozen=True)
class RefIssue:
    proprio: str
    depot: str
    numero: int

    def __str__(self) -> str:
        return f"{self.proprio}/{self.depot}#{self.numero}"


def analyser(ref: str) -> RefIssue:
    """Accepte `proprio/depot#12` ou `https://github.com/proprio/depot/issues/12`."""
    m = _COURT.match(ref.strip()) or _URL.match(ref.strip())
    if not m:
        raise ValueError(f"référence d'issue invalide : {ref!r} (attendu : proprio/depot#12 ou son URL)")
    return RefIssue(m["proprio"], m["depot"], int(m["numero"]))


def lire(ref: RefIssue, client: httpx.Client | None = None) -> str:
    """Renvoie le titre et le corps de l'issue, prêts à servir de demande."""
    entetes = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if jeton := os.environ.get("GITHUB_TOKEN"):
        entetes["Authorization"] = f"Bearer {jeton}"
    c = client or httpx.Client(timeout=30)
    try:
        r = c.get(f"https://api.github.com/repos/{ref.proprio}/{ref.depot}/issues/{ref.numero}", headers=entetes)
    finally:
        if client is None:
            c.close()
    r.raise_for_status()
    donnees = r.json()
    if "pull_request" in donnees:
        raise ValueError(f"{ref} est une pull request, pas une issue")
    return f"Issue {ref} : {donnees['title']}\n\n{donnees.get('body') or '(pas de description)'}"
