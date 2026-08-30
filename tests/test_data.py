"""Tests for :mod:`mllab.data`.

Each helper is exercised on a small frame whose expected output is computed by
hand, so a regression is obvious.
"""

from __future__ import annotations

import pandas as pd
import pytest

from mllab.data import (
    fit_standardize,
    impute_missing,
    standardize,
    train_test_split,
)


@pytest.fixture()
def frame() -> pd.DataFrame:
    return pd.DataFrame({"a": [1.0, 2.0, float("nan")], "b": [float("nan"), 4.0, 5.0]})


def test_impute_median_leaves_text_and_fills_numbers(frame: pd.DataFrame) -> None:
    out = impute_missing(frame, strategy="median")
    # a: median(1, 2) = 1.5 ; b: median(4, 5) = 4.5
    assert out.loc[2, "a"] == pytest.approx(1.5)
    assert out.loc[0, "b"] == pytest.approx(4.5)
    # original untouched (purity)
    math_nan_present = frame.isna().to_numpy().any()
    assert math_nan_present


def test_impute_mean(frame: pd.DataFrame) -> None:
    out = impute_missing(frame, strategy="mean")
    assert out.loc[2, "a"] == pytest.approx((1.0 + 2.0) / 2)
    assert out.loc[0, "b"] == pytest.approx((4.0 + 5.0) / 2)


def test_impute_unknown_strategy(frame: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        impute_missing(frame, strategy="bogus")


def test_fit_and_standardize_zero_mean_unit_std() -> None:
    df = pd.DataFrame({"x": [0.0, 2.0, 4.0]})
    mean, std = fit_standardize(df)
    out = standardize(df, mean, std)
    # after standardizing: values = (x - mean)/std
    assert float(out.loc[0, "x"]) == pytest.approx((0 - 2) / std.loc["x"])


def test_standardize_constant_column_does_not_divide_by_zero() -> None:
    df = pd.DataFrame({"x": [5.0, 5.0, 5.0]})
    mean, std = fit_standardize(df)
    assert std.loc["x"] == 1.0  # constant column: std forced to 1.0


def test_train_test_split_disjoint_and_deterministic() -> None:
    df = pd.DataFrame({"v": range(100)})
    tr1, te1 = train_test_split(df, test_size=0.2, seed=42)
    tr2, te2 = train_test_split(df, test_size=0.2, seed=42)
    # deterministic
    pd.testing.assert_frame_equal(tr1, tr2)
    pd.testing.assert_frame_equal(te1, te2)
    # disjoint
    tr_idx = set(tr1.index)
    te_idx = set(te1.index)
    assert tr_idx.isdisjoint(te_idx)
    assert len(tr_idx) + len(te_idx) == 100
    # ~80/20
    assert len(te_idx) == 20


def test_train_test_split_rejects_bad_size() -> None:
    df = pd.DataFrame({"v": range(10)})
    with pytest.raises(ValueError, match="open interval"):
        train_test_split(df, test_size=0.0)
