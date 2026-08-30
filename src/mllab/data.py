"""Data processing helpers (pandas).

All transformations here are **pure**: they take a ``DataFrame`` in and return
a new ``DataFrame`` out, with no side effects and no file I/O. File/network I/O
stays at the call sites (see ``read_csv`` / ``write_csv`` at the bottom of this
module).

Design rules:
- Explicit `.loc` / `.copy()` — no chained indexing, no ignored
  ``SettingWithCopyWarning``.
- Vectorised: no ``iterrows`` unless the fallback is justified in a comment.
- No data leakage: helpers that split data keep train/test disjoint.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

__all__ = [
    "impute_missing",
    "standardize",
    "train_test_split",
    "read_csv",
    "write_csv",
    "fit_standardize",
]


def impute_missing(data: pd.DataFrame, strategy: str = "median") -> pd.DataFrame:
    """Return a copy of *data* with numeric missing values imputed.

    Parameters
    ----------
    data:
        Input frame.
    strategy:
        ``"mean"``, ``"median"``, ``"mode"`` or a literal fill ``"0"``.
        Non-numeric columns are left untouched.

    Returns
    -------
    pd.DataFrame
        A new frame (the input is not mutated).
    """
    out = data.copy()
    numeric = out.select_dtypes(include="number")
    if strategy in {"mean", "median", "mode"}:
        fill = (
            numeric.mean(numeric_only=True)
            if strategy == "mean"
            else numeric.median(numeric_only=True)
        )
        if strategy == "mode":
            fill = numeric.mode()
            out.loc[:, numeric.columns] = numeric.fillna(fill)
        else:
            out.loc[:, numeric.columns] = numeric.fillna(fill)
    elif strategy == "0":
        out.loc[:, numeric.columns] = numeric.fillna(0)
    else:
        raise ValueError(f"unknown strategy: {strategy!r}")
    return out


def fit_standardize(data: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Compute per-column ``mean`` and ``std`` of numeric columns.

    Pure: returns ``(mean, std)`` as ``Series`` indexed by column. The caller
    applies these to a single, consistent split to avoid leakage — i.e. fit the
    transform on training data *only*, then apply to test.
    """
    numeric = data.select_dtypes(include="number")
    std = numeric.std(ddof=0)
    # Avoid division by zero on constant columns at apply time.
    std = std.where(std != 0, 1.0)
    return numeric.mean(), std


def standardize(data: pd.DataFrame, mean: pd.Series, std: pd.Series) -> pd.DataFrame:
    """Apply a ``standardize`` fit to *data* (numeric columns only).

    Returns a new ``DataFrame`` of imputed/standardized numeric columns; the input
    is not mutated.
    """
    numeric = data.select_dtypes(include="number")
    return (numeric - mean) / std


def train_test_split(
    data: pd.DataFrame,
    test_size: float = 0.25,
    *,
    seed: int = 0,
    cols: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split *data* into disjoint train/test frames.

    Deterministic: *seed* is forwarded to ``sample``. Returns two views that do
    not overlap and that are copied out so the caller can freely add columns
    without mutating the source.
    """
    if not 0.0 < test_size < 1.0:
        raise ValueError("test_size must be in the open interval (0, 1)")
    source = data[list(cols)] if cols is not None else data
    sampled = source.sample(frac=1, random_state=seed)
    n_test = int(round(len(sampled) * test_size))
    test = sampled.iloc[:n_test].copy()
    train = sampled.iloc[n_test:].copy()
    return train, test


# --- I/O borders ---------------------------------------------------------------


def read_csv(path: str) -> pd.DataFrame:
    """Read a CSV file into a ``DataFrame`` (I/O edge)."""
    return pd.read_csv(path)


def write_csv(frame: pd.DataFrame, path: str) -> None:
    """Write *frame* to a CSV file (I/O edge)."""
    frame.to_csv(path, index=False)
