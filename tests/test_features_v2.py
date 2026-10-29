
import numpy as np
import pandas as pd
import pytest

from pumpradar.features_v2 import compute_features


def make_bars(n=1600):
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "minute": pd.date_range(
                "2024-01-01", periods=n, freq="min", tz="UTC"
            ),
            "close": 100 + np.cumsum(rng.normal(0, 0.1, n)),
            "quote_volume": rng.uniform(100, 500, n),
            "count": rng.integers(10, 100, n),
            "taker_buy_quote": rng.uniform(20, 250, n),
        }
    )


def test_expected_feature_columns_exist():
    result = compute_features(make_bars())

    for window in (5, 15, 60):
        for name in ("buy", "volume", "trades", "abs_return"):
            assert f"z_{name}_{window}" in result.columns

        assert f"quiet_accumulation_{window}" in result.columns

    assert "buy_share" in result.columns


def test_rows_are_sorted_and_unique():
    bars = make_bars(100).iloc[::-1]
    result = compute_features(bars)

    assert result["minute"].is_monotonic_increasing
    assert result["minute"].is_unique


def test_buy_share():
    bars = make_bars(100)
    bars["quote_volume"] = 200.0
    bars["taker_buy_quote"] = 50.0

    result = compute_features(bars)

    assert np.allclose(result["buy_share"], 0.25)


def test_future_volume_changes_do_not_change_past_features():
    bars = make_bars()
    cutoff = 1200

    original = compute_features(bars)

    changed_bars = bars.copy()
    changed_bars.loc[cutoff + 1 :, "quote_volume"] *= 1000

    changed = compute_features(changed_bars)

    feature_columns = [
        column
        for column in original.columns
        if column.startswith(("z_", "quiet_accumulation_")) or column == "buy_share"
    ]

    pd.testing.assert_frame_equal(
        original.loc[:cutoff, feature_columns],
        changed.loc[:cutoff, feature_columns],
    )


def test_missing_required_column_raises():
    bars = make_bars().drop(columns=["close"])

    with pytest.raises(ValueError, match="Missing required columns"):
        compute_features(bars)
