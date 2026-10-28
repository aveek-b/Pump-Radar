"""Leakage-safe split protocols for PumpRadar research experiments.

Two protocols are provided, matching the build guide's Experiment A audit:

- ``split_random`` (P0): rows shuffled at random, ignoring event membership.
  This reproduces the split style used in prior work. It is an AUDIT BASELINE
  ONLY, used to measure how much performance P0 inflates relative to
  ``split_honest``. Never report a deployed model's performance from P0.

- ``split_honest`` (P2): whole events kept on one side, ordered
  chronologically by first occurrence, with an embargo window purging
  training rows too close to the test period. This is how the system is
  actually evaluated.

Connected-component grouping of overlapping event windows (needed once
Experiment B's cross-sectional data defines explicit per-event time windows
over shared (pair, minute) keys) is intentionally not implemented here yet --
Hannah's xsec.parquet isn't available to validate it against.
"""
from __future__ import annotations

import pandas as pd


def split_random(
    df: pd.DataFrame,
    seed: int = 42,
    frac: float = 0.5,
) -> tuple[pd.Index, pd.Index]:
    """P0 (prior protocol): shuffle all rows at random, split frac / 1-frac.

    Ignores event membership entirely, so a single event's chunks can land on
    both sides. Use only to measure inflation against split_honest.
    """
    if not 0 < frac < 1:
        raise ValueError(f"frac must be in (0, 1), got {frac}")
    shuffled = df.sample(frac=1, random_state=seed).index
    cut = int(len(shuffled) * frac)
    return shuffled[:cut], shuffled[cut:]


def split_honest(
    df: pd.DataFrame,
    key: str,
    date_col: str,
    train_frac: float = 0.7,
    purge: str | pd.Timedelta = "24h",
) -> tuple[pd.Index, pd.Index]:
    """P2 (honest): whole events on one side, earliest train_frac of events
    (by first-seen date) go to train, the rest to test. Training rows within
    `purge` of the earliest test timestamp are dropped (embargo), so no
    feature lookback or label window can bleed across the train/test
    boundary.

    Returns (train_index, test_index). Raises AssertionError if any `key`
    value ends up on both sides -- structurally shouldn't happen given the
    grouping, but this is the one property the whole function exists to
    guarantee, so it's checked rather than assumed.
    """
    if not 0 < train_frac < 1:
        raise ValueError(f"train_frac must be in (0, 1), got {train_frac}")
    missing = {key, date_col} - set(df.columns)
    if missing:
        raise KeyError(f"df is missing required columns: {sorted(missing)}")

    first_seen = df.groupby(key)[date_col].min().sort_values(kind="stable")
    n_train = int(len(first_seen) * train_frac)
    train_keys = set(first_seen.index[:n_train])

    train_mask = df[key].isin(train_keys)
    train_df = df.loc[train_mask]
    test_df = df.loc[~train_mask]

    if len(train_df) and len(test_df):
        embargo_cutoff = test_df[date_col].min() - pd.Timedelta(purge)
        train_df = train_df.loc[train_df[date_col] < embargo_cutoff]

    assert_no_group_leak(df, key, train_df.index, test_df.index)

    return train_df.index, test_df.index


def split_honest_train_val_test(
    df: pd.DataFrame,
    key: str,
    date_col: str,
    outer_train_frac: float = 0.7,
    val_frac_of_train: float = 0.2,
    purge: str | pd.Timedelta = "24h",
) -> tuple[pd.Index, pd.Index, pd.Index]:
    """Three-way honest split: train / validation / test, each a whole-event,
    chronologically ordered, embargo-purged block (train earliest,
    validation in the middle, test latest).

    Built by composing split_honest twice: once to carve off the outer test
    set (same boundary as the two-way split), then again on the remaining
    train+validation pool to carve validation off its latest slice. Each
    boundary gets its own embargo purge, so no boundary is weaker than the
    two-way split's.

    Returns (train_index, val_index, test_index). The validation slice
    exists specifically so hyperparameter tuning never has to touch the test
    set -- per the build guide, "the test set cannot select the best model."
    """
    train_val_idx, test_idx = split_honest(
        df, key=key, date_col=date_col, train_frac=outer_train_frac, purge=purge
    )
    train_val_df = df.loc[train_val_idx]
    train_idx, val_idx = split_honest(
        train_val_df,
        key=key,
        date_col=date_col,
        train_frac=1 - val_frac_of_train,
        purge=purge,
    )

    assert_no_group_leak(df, key, train_idx, val_idx)
    assert_no_group_leak(df, key, train_idx, test_idx)
    assert_no_group_leak(df, key, val_idx, test_idx)

    return train_idx, val_idx, test_idx


def assert_no_group_leak(
    df: pd.DataFrame,
    key: str,
    train_idx: pd.Index,
    test_idx: pd.Index,
) -> None:
    """Raise if any `key` value appears on both sides of a split.

    Call this after any split -- including future splitting logic -- not
    just the functions above.
    """
    train_keys = set(df.loc[train_idx, key])
    test_keys = set(df.loc[test_idx, key])
    overlap = train_keys & test_keys
    if overlap:
        sample = sorted(overlap)[:5]
        raise AssertionError(
            f"{len(overlap)} value(s) of {key!r} leaked across train/test "
            f"(e.g. {sample}); a split_honest call should never produce this"
        )
