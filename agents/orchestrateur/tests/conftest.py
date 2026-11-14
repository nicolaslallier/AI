import subprocess
from pathlib import Path

import pytest


def git(depot: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(depot), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def depot_git(tmp_path: Path) -> Path:
    """Un dépôt git minimal, propre, sur la branche `main`."""
    d = tmp_path / "depot"
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "test@example.invalid")
    git(d, "config", "user.name", "Test")
    git(d, "config", "commit.gpgsign", "false")
    (d / "README.md").write_text("# Dépôt de test\n")
    git(d, "add", "README.md")
    git(d, "commit", "-q", "-m", "init")
    return d
