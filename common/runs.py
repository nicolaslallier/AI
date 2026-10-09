from datetime import date
from pathlib import Path


def new_run_dir(name, root="runs"):
    """Crée `runs/<date>-<name>` ; en cas de collision, un suffixe -2, -3… (un run n'est jamais écrasé)."""
    base = Path(root) / f"{date.today().isoformat()}-{name}"
    base.parent.mkdir(parents=True, exist_ok=True)
    run_dir, n = base, 2
    while True:
        try:
            run_dir.mkdir()
            return run_dir
        except FileExistsError:
            run_dir = Path(f"{base}-{n}")
            n += 1
