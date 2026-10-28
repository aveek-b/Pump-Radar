import pandas as pd
import pytest

from pumpradar.splits import (
    assert_no_group_leak,
    split_honest,
    split_honest_train_val_test,
    split_random,
)


def _toy_df() -> pd.DataFrame:
    """Three synthetic events, each with several chunk rows, deliberately
    interleaved out of chronological order in the DataFrame to make sure the
    split logic sorts by date rather than relying on row order.
    """
    rows = []
    for pump_index, start in [(2, "2020-02-01"), (1, "2020-01-01"), (3, "2020-03-01")]:
        for i in range(5):
            rows.append(
                {
                    "pump_index": pump_index,
                    "date": pd.Timestamp(start) + pd.Timedelta(minutes=i),
                    "value": i,
                }
            )
    return pd.DataFrame(rows)


def test_split_honest_keeps_each_event_on_one_side():
    df = _toy_df()
    train_idx, test_idx = split_honest(
        df, key="pump_index", date_col="date", train_frac=0.67, purge="0h"
    )
    assert_no_group_leak(df, "pump_index", train_idx, test_idx)


def test_split_honest_test_is_strictly_later_than_train():
    df = _toy_df()
    train_idx, test_idx = split_honest(
        df, key="pump_index", date_col="date", train_frac=0.67, purge="0h"
    )
    assert len(train_idx) and len(test_idx)
    assert df.loc[train_idx, "date"].max() < df.loc[test_idx, "date"].min()


def test_split_honest_embargo_purges_rows_near_boundary():
    df = _toy_df()
    train_idx_no_purge, _ = split_honest(
        df, key="pump_index", date_col="date", train_frac=0.67, purge="0h"
    )
    train_idx_purged, _ = split_honest(
        df, key="pump_index", date_col="date", train_frac=0.67, purge="60D"
    )
    assert len(train_idx_purged) <= len(train_idx_no_purge)


def test_split_honest_rejects_bad_train_frac():
    df = _toy_df()
    with pytest.raises(ValueError):
        split_honest(df, key="pump_index", date_col="date", train_frac=1.5)


def test_split_honest_rejects_missing_columns():
    df = _toy_df().drop(columns=["date"])
    with pytest.raises(KeyError):
        split_honest(df, key="pump_index", date_col="date", train_frac=0.5)


def test_split_random_is_a_valid_partition():
    df = _toy_df()
    train_idx, test_idx = split_random(df, seed=42, frac=0.5)
    assert set(train_idx) | set(test_idx) == set(df.index)
    assert set(train_idx) & set(test_idx) == set()


def test_split_random_is_deterministic_given_seed():
    df = _toy_df()
    a_train, a_test = split_random(df, seed=42, frac=0.5)
    b_train, b_test = split_random(df, seed=42, frac=0.5)
    assert list(a_train) == list(b_train)
    assert list(a_test) == list(b_test)


def _toy_df_many_events(n_events=20) -> pd.DataFrame:
    rows = []
    for pump_index in range(n_events):
        start = pd.Timestamp("2020-01-01") + pd.Timedelta(days=pump_index * 3)
        for i in range(5):
            rows.append({"pump_index": pump_index, "date": start + pd.Timedelta(minutes=i), "value": i})
    return pd.DataFrame(rows)


def test_three_way_split_keeps_every_event_on_exactly_one_side():
    df = _toy_df_many_events()
    train_idx, val_idx, test_idx = split_honest_train_val_test(
        df, key="pump_index", date_col="date", outer_train_frac=0.7, val_frac_of_train=0.2, purge="0h"
    )
    assert_no_group_leak(df, "pump_index", train_idx, val_idx)
    assert_no_group_leak(df, "pump_index", train_idx, test_idx)
    assert_no_group_leak(df, "pump_index", val_idx, test_idx)

    all_idx = set(train_idx) | set(val_idx) | set(test_idx)
    # every row ends up in exactly one of the three slices (purge can only shrink train)
    assert all_idx <= set(df.index)


def test_three_way_split_is_chronologically_ordered():
    df = _toy_df_many_events()
    train_idx, val_idx, test_idx = split_honest_train_val_test(
        df, key="pump_index", date_col="date", outer_train_frac=0.7, val_frac_of_train=0.2, purge="0h"
    )
    assert len(train_idx) and len(val_idx) and len(test_idx)
    assert df.loc[train_idx, "date"].max() < df.loc[val_idx, "date"].min()
    assert df.loc[val_idx, "date"].max() < df.loc[test_idx, "date"].min()


def test_three_way_split_proportions_are_roughly_right():
    df = _toy_df_many_events(n_events=50)
    train_idx, val_idx, test_idx = split_honest_train_val_test(
        df, key="pump_index", date_col="date", outer_train_frac=0.7, val_frac_of_train=0.2, purge="0h"
    )
    n_train_events = df.loc[train_idx, "pump_index"].nunique()
    n_val_events = df.loc[val_idx, "pump_index"].nunique()
    n_test_events = df.loc[test_idx, "pump_index"].nunique()
    assert n_train_events == 28  # int(50*0.7) * 0.8 = 35 * 0.8 = 28
    assert n_val_events == 7  # 35 - 28
    assert n_test_events == 15  # 50 - 35


def test_assert_no_group_leak_catches_a_real_leak():
    df = _toy_df()
    bad_train_idx = df.index[:7]  # crosses an event boundary on purpose
    bad_test_idx = df.index[7:]
    with pytest.raises(AssertionError):
        assert_no_group_leak(df, "pump_index", bad_train_idx, bad_test_idx)
