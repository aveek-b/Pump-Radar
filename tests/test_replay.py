import zipfile

import numpy as np
import pandas as pd
import pytest

from pumpradar.replay import (
    build_replay_files,
    extract_replay_window,
    load_pair_day_ohlcv,
)


def _write_fake_kline_zip(kline_dir, pair: str, day: str, n_minutes: int = 1440, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    day_start = pd.Timestamp(day, tz="UTC")
    rows = []
    price = 1.0
    for m in range(n_minutes):
        open_time_ms = int((day_start + pd.Timedelta(minutes=m)).timestamp() * 1000)
        price *= 1 + rng.normal(0, 0.002)
        high, low = price * 1.01, price * 0.99
        rows.append([
            open_time_ms, price, high, low, price, 10.0, open_time_ms + 59999,
            100.0, 5, 5.0, 50.0, 0,
        ])
    archive_dir = kline_dir / pair / "1m"
    archive_dir.mkdir(parents=True, exist_ok=True)
    csv_path = archive_dir / f"{pair}-1m-{day}.csv"
    pd.DataFrame(rows).to_csv(csv_path, header=False, index=False)
    zip_path = archive_dir / f"{pair}-1m-{day}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_path, arcname=csv_path.name)
    csv_path.unlink()


def test_load_pair_day_ohlcv_missing_archive_returns_empty(tmp_path):
    out = load_pair_day_ohlcv("NOPEBTC", pd.Timestamp("2024-01-01", tz="UTC"), tmp_path)
    assert out.empty
    assert list(out.columns) == ["minute", "open", "high", "low", "close", "volume"]


def test_load_pair_day_ohlcv_reads_real_shaped_archive(tmp_path):
    _write_fake_kline_zip(tmp_path, "ABCBTC", "2024-01-01")
    out = load_pair_day_ohlcv("ABCBTC", pd.Timestamp("2024-01-01", tz="UTC"), tmp_path)
    assert len(out) == 1440
    assert (out["high"] >= out["low"]).all()


def test_extract_replay_window_spans_multiple_days(tmp_path):
    _write_fake_kline_zip(tmp_path, "ABCBTC", "2023-12-31", seed=1)
    _write_fake_kline_zip(tmp_path, "ABCBTC", "2024-01-01", seed=2)

    onset = pd.Timestamp("2024-01-01 00:30:00", tz="UTC")
    window = extract_replay_window(
        "ABCBTC", onset, tmp_path,
        window_before=pd.Timedelta(minutes=150), window_after=pd.Timedelta(minutes=30),
    )
    assert not window.empty
    assert window["minute"].min() >= onset - pd.Timedelta(minutes=150)
    assert window["minute"].max() <= onset + pd.Timedelta(minutes=30)


def test_extract_replay_window_missing_data_returns_empty(tmp_path):
    onset = pd.Timestamp("2024-01-01 00:30:00", tz="UTC")
    window = extract_replay_window("NOPEBTC", onset, tmp_path)
    assert window.empty


def test_build_replay_files_writes_json_for_confirmed_events_only(tmp_path):
    kline_dir = tmp_path / "klines"
    out_dir = tmp_path / "replay"
    for day in ("2023-12-31", "2024-01-01"):
        _write_fake_kline_zip(kline_dir, "PUMPBTC", day, seed=5)

    events = pd.DataFrame([
        {
            "event_id": "event_0001", "pair": "PUMPBTC", "symbol": "PUMP", "era": "train",
            "t_onset": pd.Timestamp("2024-01-01 00:30:00", tz="UTC"), "onset_flag": "ok",
        },
        {
            "event_id": "event_0002", "pair": "NODATABTC", "symbol": "NODATA", "era": "train",
            "t_onset": pd.Timestamp("2024-01-01 00:30:00", tz="UTC"), "onset_flag": "ok",
        },
        {
            "event_id": "event_0003", "pair": "PUMPBTC", "symbol": "PUMP", "era": "train",
            "t_onset": pd.Timestamp("2024-01-01 00:30:00", tz="UTC"), "onset_flag": "zero_iqr",
        },
    ])

    result = build_replay_files(events, kline_dir, out_dir=out_dir)

    assert result["n_total"] == 2  # only onset_flag == "ok" events are considered
    assert result["n_available"] == 1  # only PUMPBTC has real archive data
    assert (out_dir / "event_0001.json").exists()
    assert not (out_dir / "event_0002.json").exists()
    assert not (out_dir / "event_0003.json").exists()

    import json
    with open(out_dir / "event_0001.json") as f:
        payload = json.load(f)
    assert payload["pair"] == "PUMPBTC"
    assert len(payload["candles"]) > 0
    assert all({"time", "open", "high", "low", "close", "volume"} <= set(c) for c in payload["candles"])


def test_build_replay_files_requires_expected_columns():
    with pytest.raises(ValueError):
        build_replay_files(pd.DataFrame({"event_id": [1]}), kline_dir=None)
