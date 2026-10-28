import zipfile

import numpy as np
import pandas as pd
import pytest

from pumpradar.features import (
    build_xsec_sample,
    compute_features,
    feature_columns,
    load_pair_day_bars,
    load_universe_window,
)


def _synthetic_bars(n_pairs=3, n_minutes=2000, seed=0) -> pd.DataFrame:
    """Synthetic multi-pair minute bars -- not real market data, used only
    to exercise compute_features()'s math in isolation. Real feature values
    are computed separately against the actual downloaded Binance klines.
    """
    rng = np.random.default_rng(seed)
    base = pd.Timestamp("2024-01-01", tz="UTC")
    rows = []
    for p in range(n_pairs):
        price = 100.0 + p * 10
        for m in range(n_minutes):
            price *= 1 + rng.normal(0, 0.001)
            rows.append(
                {
                    "pair": f"COIN{p}BTC",
                    "minute": base + pd.Timedelta(minutes=m),
                    "close": price,
                    "quote_volume": max(rng.normal(100, 20), 0.0),
                    "count": max(int(rng.normal(50, 10)), 0),
                    "taker_buy_quote": max(rng.normal(50, 15), 0.0),
                }
            )
    return pd.DataFrame(rows)


def test_compute_features_requires_expected_columns():
    bad = pd.DataFrame({"pair": ["A"], "minute": [pd.Timestamp.now(tz="UTC")]})
    with pytest.raises(ValueError):
        compute_features(bad)


def test_compute_features_does_not_mutate_input():
    bars = _synthetic_bars(n_pairs=2, n_minutes=200)
    bars_copy = bars.copy(deep=True)
    compute_features(bars)
    pd.testing.assert_frame_equal(bars, bars_copy)


def test_compute_features_produces_all_declared_columns():
    bars = _synthetic_bars(n_pairs=2, n_minutes=2000)
    out = compute_features(bars)
    for col in feature_columns():
        assert col in out.columns, f"missing declared feature column {col}"


def test_no_feature_looks_into_the_future():
    """The build guide's D5 leakage test: take one pair's bars, compute
    features, then multiply every volume/trade value strictly AFTER a
    chosen minute t by 1000, recompute, and assert every feature at or
    before t is unchanged. This is the test that guards the module's
    central claim -- no feature uses information from the future.
    """
    bars = _synthetic_bars(n_pairs=1, n_minutes=2000)
    original = compute_features(bars)

    cutoff_idx = 1500
    cutoff_minute = bars.loc[cutoff_idx, "minute"]

    altered = bars.copy()
    future_mask = altered["minute"] > cutoff_minute
    for col in ("quote_volume", "count", "taker_buy_quote"):
        altered.loc[future_mask, col] = altered.loc[future_mask, col] * 1000

    altered_features = compute_features(altered)

    for col in feature_columns():
        before_cutoff = original["minute"] <= cutoff_minute
        pd.testing.assert_series_equal(
            original.loc[before_cutoff, col].reset_index(drop=True),
            altered_features.loc[before_cutoff, col].reset_index(drop=True),
            check_names=False,
            obj=col,
        )


def test_model_feature_list_excludes_identity_and_price_level():
    """Metadata/price-level columns must never appear in the frozen feature
    list -- they are explicitly excluded from the model's inputs.
    """
    forbidden = {"pair", "minute", "close", "quote_volume", "count", "taker_buy_quote", "abs_return"}
    assert forbidden.isdisjoint(set(feature_columns()))


def test_buy_share_is_bounded_and_defined():
    bars = _synthetic_bars(n_pairs=1, n_minutes=100)
    out = compute_features(bars)
    assert out["buy_share"].notna().all()
    assert (out["buy_share"] >= 0).all()


def test_ranks_are_percentiles_across_pairs_at_the_same_minute():
    bars = _synthetic_bars(n_pairs=5, n_minutes=2000)
    out = compute_features(bars)
    sample_minute = out["minute"].iloc[1800]
    same_minute = out.loc[out["minute"] == sample_minute, "r_vol_60"].dropna()
    if len(same_minute) > 1:
        assert same_minute.min() >= 0.0
        assert same_minute.max() <= 1.0


def _write_fake_kline_zip(kline_dir, pair: str, day: str, n_minutes: int = 1440, seed: int = 0) -> None:
    """Write a synthetic daily kline ZIP matching Binance's real archive
    format (12 headerless columns), for testing the loader without needing
    a real download.
    """
    rng = np.random.default_rng(seed)
    day_start = pd.Timestamp(day, tz="UTC")
    rows = []
    for m in range(n_minutes):
        open_time_ms = int((day_start + pd.Timedelta(minutes=m)).timestamp() * 1000)
        quote_volume = max(rng.normal(100, 20), 0.0)
        taker_buy_quote = max(rng.normal(50, 15), 0.0)
        rows.append([
            open_time_ms, 1.0, 1.0, 1.0, 1.0 + rng.normal(0, 0.001),
            1.0, open_time_ms + 59999, quote_volume, int(max(rng.normal(50, 10), 0)),
            0.5, taker_buy_quote, 0,
        ])
    archive_dir = kline_dir / pair / "1m"
    archive_dir.mkdir(parents=True, exist_ok=True)
    csv_path = archive_dir / f"{pair}-1m-{day}.csv"
    pd.DataFrame(rows).to_csv(csv_path, header=False, index=False)
    zip_path = archive_dir / f"{pair}-1m-{day}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_path, arcname=csv_path.name)
    csv_path.unlink()


def test_load_pair_day_bars_missing_archive_returns_empty_not_error(tmp_path):
    out = load_pair_day_bars("NOPEBTC", pd.Timestamp("2024-01-01", tz="UTC"), kline_dir=tmp_path)
    assert out.empty
    assert list(out.columns) == ["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"]


def test_load_pair_day_bars_reads_a_real_shaped_archive(tmp_path):
    _write_fake_kline_zip(tmp_path, "ABCBTC", "2024-01-01")
    out = load_pair_day_bars("ABCBTC", pd.Timestamp("2024-01-01", tz="UTC"), kline_dir=tmp_path)
    assert len(out) == 1440
    assert out["pair"].eq("ABCBTC").all()
    assert out["minute"].min() == pd.Timestamp("2024-01-01", tz="UTC")


def test_load_universe_window_spans_multiple_days_and_pairs(tmp_path):
    _write_fake_kline_zip(tmp_path, "ABCBTC", "2024-01-01", seed=1)
    _write_fake_kline_zip(tmp_path, "ABCBTC", "2024-01-02", seed=2)
    _write_fake_kline_zip(tmp_path, "XYZBTC", "2024-01-01", seed=3)

    window = load_universe_window(
        pd.Timestamp("2024-01-01 23:00:00", tz="UTC"),
        pd.Timestamp("2024-01-02 01:00:00", tz="UTC"),
        pairs=["ABCBTC", "XYZBTC"],
        kline_dir=tmp_path,
    )
    assert set(window["pair"].unique()) == {"ABCBTC", "XYZBTC"}
    assert window["minute"].min() >= pd.Timestamp("2024-01-01 23:00:00", tz="UTC")
    assert window["minute"].max() <= pd.Timestamp("2024-01-02 01:00:00", tz="UTC")


def test_build_xsec_sample_labels_only_the_target_pair(tmp_path):
    for day in ("2023-12-31", "2024-01-01"):
        _write_fake_kline_zip(tmp_path, "PUMPBTC", day, seed=10)
        _write_fake_kline_zip(tmp_path, "OTHERBTC", day, seed=11)

    onset = pd.Timestamp("2024-01-01 10:00:00", tz="UTC")
    events = pd.DataFrame([
        {"event_id": "event_0001", "pair": "PUMPBTC", "t_onset": onset, "era": "train", "onset_flag": "ok"},
    ])

    xsec = build_xsec_sample(events, universe_pairs=["PUMPBTC", "OTHERBTC"], kline_dir=tmp_path)

    assert set(xsec["pair"].unique()) == {"PUMPBTC", "OTHERBTC"}
    assert xsec["minute"].max() <= onset - pd.Timedelta(minutes=1)
    assert xsec["minute"].min() >= onset - pd.Timedelta(minutes=120)

    pump_rows = xsec.loc[xsec["pair"] == "PUMPBTC"]
    other_rows = xsec.loc[xsec["pair"] == "OTHERBTC"]
    assert pump_rows["lead_min"].notna().all()
    assert other_rows["lead_min"].isna().all()
    # lead_min counts down to onset for the target pair
    assert pump_rows["lead_min"].min() >= 1
    assert pump_rows["lead_min"].max() <= 120


def test_build_xsec_sample_excludes_events_without_confirmed_onset():
    """t_onset is never null in real detect_onsets.py output -- zero_iqr and
    no_data events get the Telegram timestamp as a fallback instead. The
    real exclusion signal is onset_flag != "ok", not a null check.
    """
    events = pd.DataFrame([
        {
            "event_id": "event_0001", "pair": "PUMPBTC",
            "t_onset": pd.Timestamp("2024-01-01", tz="UTC"),  # a real fallback timestamp, not null
            "era": "train", "onset_flag": "zero_iqr",
        },
        {
            "event_id": "event_0002", "pair": "PUMPBTC",
            "t_onset": pd.Timestamp("2024-01-02", tz="UTC"),
            "era": "train", "onset_flag": "no_data",
        },
    ])
    xsec = build_xsec_sample(events, universe_pairs=["PUMPBTC"])
    assert xsec.empty
