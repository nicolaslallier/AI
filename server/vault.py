"""Règles du coffre : chemins sûrs, noms assainis, écriture sans écrasement, notes."""
import asyncio
import os
import unicodedata
from pathlib import Path


class VaultPathError(ValueError):
    pass


def sanitize_name(name: str) -> str:
    name = "".join(c for c in name if c not in "/\\[]|#^<>%{}$`" and unicodedata.category(c) != "Cc").strip()
    name = name.lstrip(". ")  # ni fichier caché, ni "." / ".." (le dossier ou son parent)
    if not name:
        return "fichier"
    if len(name) > 120:
        stem, ext = os.path.splitext(name)
        ext = ext[:20]
        name = stem[: 120 - len(ext)] + ext
    return name


class Vault:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._lock = asyncio.Lock()

    def resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root):
            raise VaultPathError(f"Chemin hors du coffre : {rel}")
        return p

    def safe(self, rel: str) -> Path:
        """`resolve` + refus de tout composant caché (`.obsidian`, `.staging`...), avant et après résolution."""
        if any(c.startswith(".") for c in Path(rel).parts):
            raise VaultPathError(f"Chemin caché refusé : {rel}")
        p = self.resolve(rel)
        if any(c.startswith(".") for c in p.relative_to(self.root).parts):  # lien vers une cible cachée
            raise VaultPathError(f"Chemin caché refusé : {rel}")
        return p

    async def write_unique(self, folder_rel: str, name: str, data: bytes | Path) -> Path:
        folder = self.safe(folder_rel)
        stem, ext = os.path.splitext(sanitize_name(name))
        async with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            n = 1
            while True:
                dest = folder / f"{stem}{ext}" if n == 1 else folder / f"{stem}-{n}{ext}"
                n += 1
                if os.path.lexists(dest):  # lexists : un lien brisé compte comme pris
                    continue
                if isinstance(data, Path):
                    os.replace(data, dest)  # même système de fichiers : .staging/ est dans le coffre
                    break
                try:
                    with open(dest, "xb") as f:  # O_EXCL : ne suit jamais un lien
                        f.write(data)
                    break
                except FileExistsError:
                    continue
        return dest

    def note_target(self, note_rel: str | None) -> Path | None:
        """Valide `note_liée` (à appeler avant d'écrire le fichier : pas d'orphelin)."""
        if not note_rel:
            return None
        if not note_rel.endswith(".md"):
            raise VaultPathError(f"Note invalide : {note_rel}")
        note = self.safe(note_rel)
        if note.exists() and not note.is_file():
            raise VaultPathError(f"Note invalide : {note_rel}")
        return note

    def attach(self, note_rel: str | None, folder_rel: str, file_path: Path) -> Path:
        link = f"![[{file_path.name}]]\n"
        note = self.note_target(note_rel)
        if note == file_path:  # ne jamais modifier le fichier importé
            note = None
        if file_path.suffix.lower() == ".md" and not (note and note.exists()):
            return file_path  # une note importée est déjà une note : pas de note par défaut
        if not (note and note.exists()):
            note = self.safe(f"{folder_rel}/{file_path.stem}.md")
            note.parent.mkdir(parents=True, exist_ok=True)
            if not note.exists():
                with note.open("x", encoding="utf-8") as f:
                    f.write(link)
                return note
        with note.open("a", encoding="utf-8") as f:
            f.write("\n" + link)
        return note
