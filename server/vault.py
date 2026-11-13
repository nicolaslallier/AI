"""Règles du coffre : chemins sûrs, noms assainis, écriture sans écrasement, notes."""
import asyncio
import os
import unicodedata
from pathlib import Path


class VaultPathError(ValueError):
    pass


def sanitize_name(name: str) -> str:
    name = "".join(c for c in name if c not in "/\\[]|#^" and unicodedata.category(c) != "Cc").strip()
    if not name.strip("."):  # "", ".", ".." : désigneraient le dossier ou son parent
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

    async def write_unique(self, folder_rel: str, name: str, data: bytes | Path) -> Path:
        folder = self.resolve(folder_rel)
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

    def attach(self, note_rel: str | None, folder_rel: str, file_path: Path) -> Path:
        link = f"![[{file_path.name}]]\n"
        note = None
        if note_rel:
            if not note_rel.endswith(".md") or any(c.startswith(".") for c in Path(note_rel).parts):
                raise VaultPathError(f"Note invalide : {note_rel}")
            note = self.resolve(note_rel)
            if note.exists() and not note.is_file():
                raise VaultPathError(f"Note invalide : {note_rel}")
        if not (note and note.exists()):
            note = self.resolve(f"{folder_rel}/{file_path.stem}.md")
            note.parent.mkdir(parents=True, exist_ok=True)
            if not note.exists():
                with note.open("x", encoding="utf-8") as f:
                    f.write(link)
                return note
        with note.open("a", encoding="utf-8") as f:
            f.write("\n" + link)
        return note
