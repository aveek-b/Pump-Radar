"""Historical pump replay: real OHLCV candles around a confirmed real
onset, extracted from the downloaded Binance kline archive.

This is the "Past Events" / Replay feature from the build guide -- distinct
from the live Coin view (prices.fetch_candles), which only ever shows
recent data from Binance's live API and can never reach back to the
2018-2021 events this project's labeled data covers. Replay data is
precomputed once from the real archive (data/raw/binance_klines/, not
committed -- too large) into small per-event JSON files under data/replay/,
which the API serves statically.

No model score is included yet -- Experiment B's model is not calibrated
or frozen, so there is no honest risk score to attach to these candles.
Only the real price history and the real onset marker.
"""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from pumpradar.features import KLINE_COLS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPLAY_DIR = PROJECT_ROOT / "data" / "replay"

DEFAULT_WINDOW_BEFORE = pd.Timedelta(minutes=150)
DEFAULT_WINDOW_AFTER = pd.Timedelta(minutes=30)


def load_pair_day_ohlcv(pair: str, day: pd.Timestamp, kline_dir: Path) -> pd.DataFrame:
    """Full OHLCV (not just the slim feature columns) for one pair's
    downloaded daily archive. Returns an empty frame for a missing/corrupt
    archive -- never fabricated.
    """
    archive = kline_dir / pair / "1m" / f"{pair}-1m-{day.strftime('%Y-%m-%d')}.zip"
    empty = pd.DataFrame(columns=["minute", "open", "high", "low", "close", "volume"])
    if not archive.exists():
        return empty
    try:
        with ZipFile(archive) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                return empty
            with zf.open(csv_names[0]) as f:
                raw = pd.read_csv(f, header=None, names=KLINE_COLS)
    except (OSError, ValueError, IndexError, KeyError):
        return empty

    open_time = pd.to_numeric(raw["open_time"], errors="coerce")
    valid = open_time.dropna()
    if valid.empty:
        return empty
    unit = "us" if valid.iloc[0] > 1e14 else "ms"

    return pd.DataFrame({
        "minute": pd.to_datetime(open_time, unit=unit, utc=True, errors="coerce"),
        "open": pd.to_numeric(raw["open"], errors="coerce"),
        "high": pd.to_numeric(raw["high"], errors="coerce"),
        "low": pd.to_numeric(raw["low"], errors="coerce"),
        "close": pd.to_numeric(raw["close"], errors="coerce"),
        "volume": pd.to_numeric(raw["volume"], errors="coerce"),
    }).dropna(subset=["minute"])


def extract_replay_window(
    pair: str,
    onset: pd.Timestamp,
    kline_dir: Path,
    window_before: pd.Timedelta = DEFAULT_WINDOW_BEFORE,
    window_after: pd.Timedelta = DEFAULT_WINDOW_AFTER,
) -> pd.DataFrame:
    """Real OHLCV candles for one pair spanning [onset - window_before,
    onset + window_after], assembled from however many daily archives that
    span touches. Missing days are skipped, not fabricated.
    """
    start = onset - window_before
    end = onset + window_after
    frames = [
        load_pair_day_ohlcv(pair, day, kline_dir)
        for day in pd.date_range(start.floor("D"), end.floor("D"), freq="D")
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=["minute", "open", "high", "low", "close", "volume"])
    combined = pd.concat(frames, ignore_index=True).drop_duplicates("minute").sort_values("minute")
    return combined.loc[(combined["minute"] >= start) & (combined["minute"] <= end)].reset_index(drop=True)


def compute_window_stats(candles: pd.DataFrame, onset: pd.Timestamp) -> dict:
    """Real statistics computed directly from the replay window's candles --
    no estimation, no fabricated severity. The "pump window" highlighted on
    the chart is defined as onset -> the real post-onset price peak in this
    window, since that is the one data-grounded boundary available (there
    is no labeled "pump end" in the source data). If the window also
    captures a real decline after that peak, decline_from_peak_pct reports
    it as the (visible) "dump" side -- None if the window ends before any
    decline shows up, not assumed to be zero.
    """
    pre = candles.loc[candles["minute"] < onset]
    post = candles.loc[candles["minute"] >= onset]
    if post.empty:
        return {}

    onset_price = float(pre.iloc[-1]["close"]) if not pre.empty else float(post.iloc[0]["close"])
    peak_idx = post["close"].idxmax()
    peak_price = float(post.loc[peak_idx, "close"])
    peak_time = post.loc[peak_idx, "minute"]
    end_price = float(post.iloc[-1]["close"])

    return {
        "onset_price": onset_price,
        "peak_price": peak_price,
        "peak_time": peak_time.isoformat(),
        "max_gain_pct": ((peak_price - onset_price) / onset_price * 100) if onset_price else None,
        "window_end_price": end_price,
        "decline_from_peak_pct": ((end_price - peak_price) / peak_price * 100) if peak_price else None,
    }


def build_replay_files(
    events: pd.DataFrame,
    kline_dir: Path,
    out_dir: Path = REPLAY_DIR,
    window_before: pd.Timedelta = DEFAULT_WINDOW_BEFORE,
    window_after: pd.Timedelta = DEFAULT_WINDOW_AFTER,
) -> dict:
    """Write data/replay/{event_id}.json for every confirmed-onset event
    (onset_flag == "ok") in `events`, plus an index.json summary. Returns
    the index for convenience. Events whose archive data is missing are
    recorded in the index as unavailable rather than silently skipped.
    """
    required = {"event_id", "pair", "symbol", "t_onset", "onset_flag", "era"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"events is missing required columns: {sorted(missing)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    confirmed = events.loc[events["onset_flag"] == "ok"].copy()
    confirmed["t_onset"] = pd.to_datetime(confirmed["t_onset"], utc=True)

    index = []
    for _, ev in confirmed.iterrows():
        onset = ev["t_onset"]
        candles = extract_replay_window(ev["pair"], onset, kline_dir, window_before, window_after)
        available = not candles.empty
        stats = compute_window_stats(candles, onset) if available else {}
        if available:
            payload = {
                "event_id": ev["event_id"],
                "pair": ev["pair"],
                "symbol": ev["symbol"],
                "era": ev["era"],
                "onset": onset.isoformat(),
                **stats,
                "candles": [
                    {
                        "time": row.minute.isoformat(), "open": float(row.open), "high": float(row.high),
                        "low": float(row.low), "close": float(row.close), "volume": float(row.volume),
                    }
                    for row in candles.itertuples()
                ],
            }
            with open(out_dir / f"{ev['event_id']}.json", "w") as f:
                json.dump(payload, f)

        index.append({
            "event_id": ev["event_id"], "pair": ev["pair"], "symbol": ev["symbol"],
            "era": ev["era"], "onset": onset.isoformat(),
            "available": available, "n_candles": len(candles),
            "max_gain_pct": stats.get("max_gain_pct"),
        })

    with open(out_dir / "index.json", "w") as f:
        json.dump(index, f, indent=2)

    return {"index": index, "n_available": sum(1 for r in index if r["available"]), "n_total": len(index)}
