"""Shared cross-sectional feature module.

compute_features() is the ONE feature implementation for both research
(exp_b.py's cross-sectional model) and the live platform (api/engine) --
per the build guide, the scoring path must be identical in both uses, so
this module has no research-only or platform-only branches.

Each feature asks "how unusual is this coin right now, compared with its
own recent normal, and with every other coin trading at the same minute."
Raw price level and coin identity are deliberately excluded: they are not
inputs here, so the model cannot use them as a shortcut (see the
Experiment A leakage audit's finding that price-level/time encodings can
let models exploit the split protocol rather than genuine signal).
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KLINE_DIR = PROJECT_ROOT / "data" / "raw" / "binance_klines"
XSEC_OUTPUT = PROJECT_ROOT / "data" / "processed" / "xsec.parquet"

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_base", "taker_buy_quote", "ignore",
]

WINDOW_BEFORE_ONSET_MIN = 120  # sample minutes onset-120 .. onset-1
LOOKBACK_BUFFER_HOURS = 25  # baseline (~23h) + embargo (1h) + safety margin

WINDOWS_MIN = (5, 15, 60)
BASELINE_MINUTES = 1380  # ~23 hours
EMBARGO_MINUTES = 60  # baseline ends 60 minutes before t, per the guide
MIN_BASELINE_OBS = 600

REQUIRED_BAR_COLUMNS = {"pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"}


def robust_z(series: pd.Series, window: int) -> pd.Series:
    """Rolling-window robust z-score: (window-sum - baseline median) /
    (baseline robust SD), where the baseline is the ~23 hours ending 60
    minutes before each point (excluding the window itself and the most
    recent hour, so nothing in the baseline can overlap the signal being
    scored). Robust SD = IQR / 1.349, floored at 1e-9 to avoid division by
    zero when a coin is extremely quiet.
    """
    roll = series.rolling(window, min_periods=window).sum()
    baseline = roll.shift(EMBARGO_MINUTES)
    quantiles = baseline.rolling(BASELINE_MINUTES, min_periods=MIN_BASELINE_OBS)
    iqr = quantiles.quantile(0.75) - quantiles.quantile(0.25)
    return (roll - quantiles.median()) / (iqr / 1.349 + 1e-9)


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: one row per (pair, minute) with columns pair, minute, close,
    quote_volume, count, taker_buy_quote (the shape load_kline_zip-style
    loaders produce, tagged with a pair column). Sorted order is not
    assumed -- this function sorts internally.

    Returns a new DataFrame with the original columns plus, for each
    window in WINDOWS_MIN: a robust z-score of taker-buy volume, total
    volume, trade count and absolute return (z_buy_<w>, z_vol_<w>,
    z_trades_<w>, z_absret_<w>); a market-relative percentile rank of each
    z-score among all pairs at the same minute (r_buy_<w>, r_vol_<w>,
    r_trades_<w>, r_absret_<w>); and quiet accumulation (volume z minus
    absolute-return z) per window. Also adds instantaneous buy_share
    (taker-buy / total volume this minute). Does not mutate the input.
    """
    missing = REQUIRED_BAR_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"bars is missing required columns: {sorted(missing)}")

    out = bars.sort_values(["pair", "minute"]).reset_index(drop=True).copy()

    out["buy_share"] = out["taker_buy_quote"] / out["quote_volume"].clip(lower=1e-9)

    ret = out.groupby("pair")["close"].pct_change()
    out["abs_return"] = ret.abs()

    signal_columns = {
        "buy": "taker_buy_quote",
        "vol": "quote_volume",
        "trades": "count",
        "absret": "abs_return",
    }

    for window in WINDOWS_MIN:
        for label, source_col in signal_columns.items():
            z_col = f"z_{label}_{window}"
            out[z_col] = out.groupby("pair")[source_col].transform(
                lambda s, w=window: robust_z(s, w)
            )

        for label in signal_columns:
            z_col = f"z_{label}_{window}"
            r_col = f"r_{label}_{window}"
            out[r_col] = out.groupby("minute")[z_col].rank(pct=True)

        out[f"quiet_accum_{window}"] = out[f"z_vol_{window}"] - out[f"z_absret_{window}"]

    return out


def load_pair_day_bars(pair: str, day: pd.Timestamp, kline_dir: Path = KLINE_DIR) -> pd.DataFrame:
    """Load one pair's downloaded daily kline ZIP, if it exists. Returns an
    empty frame (not an error) for a missing archive -- a coin not listed
    or not downloaded for that day is an unknown observation, not a zero.
    """
    archive = kline_dir / pair / "1m" / f"{pair}-1m-{day.strftime('%Y-%m-%d')}.zip"
    if not archive.exists():
        return pd.DataFrame(columns=["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"])

    try:
        with ZipFile(archive) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                return pd.DataFrame(columns=["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"])
            with zf.open(csv_names[0]) as f:
                raw = pd.read_csv(f, header=None, names=KLINE_COLS)
    except (OSError, ValueError, IndexError, KeyError):
        return pd.DataFrame(columns=["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"])

    open_time = pd.to_numeric(raw["open_time"], errors="coerce")
    valid = open_time.dropna()
    if valid.empty:
        return pd.DataFrame(columns=["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"])
    unit = "us" if valid.iloc[0] > 1e14 else "ms"

    return pd.DataFrame({
        "pair": pair,
        "minute": pd.to_datetime(open_time, unit=unit, utc=True, errors="coerce"),
        "close": pd.to_numeric(raw["close"], errors="coerce"),
        "quote_volume": pd.to_numeric(raw["quote_volume"], errors="coerce"),
        "count": pd.to_numeric(raw["count"], errors="coerce"),
        "taker_buy_quote": pd.to_numeric(raw["taker_buy_quote"], errors="coerce"),
    }).dropna(subset=["minute"])


def load_universe_window(
    start: pd.Timestamp,
    end: pd.Timestamp,
    pairs: list[str],
    kline_dir: Path = KLINE_DIR,
) -> pd.DataFrame:
    """All available pairs' bars across every UTC calendar day touched by
    [start, end]. Missing archives are silently skipped (not fabricated) --
    whatever pairs/days were actually downloaded is what gets used.
    """
    frames = [
        load_pair_day_bars(pair, day, kline_dir)
        for day in pd.date_range(start.floor("D"), end.floor("D"), freq="D")
        for pair in pairs
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"])

    combined = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(["pair", "minute"])
        .sort_values(["pair", "minute"])
    )
    return combined.loc[(combined["minute"] >= start) & (combined["minute"] <= end)].reset_index(drop=True)


def build_xsec_sample(
    events: pd.DataFrame,
    universe_pairs: list[str],
    kline_dir: Path = KLINE_DIR,
) -> pd.DataFrame:
    """Build the cross-sectional sample: for every event with a CONFIRMED
    onset (onset_flag == "ok", i.e. a real detected volume spike -- not
    detect_onsets.py's fallback-to-Telegram-time for zero_iqr/no_data
    events), minutes from onset-120 to onset-1, every universe coin trading
    at that minute. lead_min is populated only for the event's own pair
    (minutes to its onset); every other coin's row is a same-minute
    negative with lead_min left null, per the hand-off contract.

    events must have columns event_id, pair, t_onset, era, onset_flag
    (from detect_onsets.py). t_onset is never null -- detect_onsets.py
    fills it with the Telegram timestamp for zero_iqr/no_data events rather
    than leaving it empty -- so onset_flag, not a null check, is what
    actually distinguishes a confirmed market onset from an unconfirmed
    fallback timestamp. Using the fallback here would silently mislabel
    lead_min against a timestamp the build guide itself says is "not a
    confirmed market onset."
    """
    required = {"event_id", "pair", "t_onset", "era", "onset_flag"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"events is missing required columns: {sorted(missing)}")

    confirmed = events.loc[events["onset_flag"] == "ok"].copy()
    confirmed["t_onset"] = pd.to_datetime(confirmed["t_onset"], utc=True)

    rows = []
    for _, event in confirmed.iterrows():
        onset = event["t_onset"]
        window_start = onset - pd.Timedelta(minutes=WINDOW_BEFORE_ONSET_MIN)
        window_end = onset - pd.Timedelta(minutes=1)
        load_start = window_start - pd.Timedelta(hours=LOOKBACK_BUFFER_HOURS)

        raw_bars = load_universe_window(load_start, window_end, universe_pairs, kline_dir)
        if raw_bars.empty:
            continue

        featured = compute_features(raw_bars)
        snapshot = featured.loc[
            (featured["minute"] >= window_start) & (featured["minute"] <= window_end)
        ].copy()
        if snapshot.empty:
            continue

        snapshot["event_id"] = event["event_id"]
        snapshot["era"] = event["era"]
        snapshot["lead_min"] = pd.NA
        own_pair_mask = snapshot["pair"] == event["pair"]
        snapshot.loc[own_pair_mask, "lead_min"] = (
            (onset - snapshot.loc[own_pair_mask, "minute"]).dt.total_seconds() / 60.0
        )
        rows.append(snapshot)

    if not rows:
        return pd.DataFrame(columns=["event_id", "pair", "minute", "era", "lead_min", *feature_columns()])

    xsec = pd.concat(rows, ignore_index=True)
    return xsec[["event_id", "pair", "minute", "era", "lead_min", *feature_columns()]]


def feature_columns() -> list[str]:
    """Ordered list of model feature column names this module produces
    (excluding metadata: pair, minute, close, quote_volume, count,
    taker_buy_quote, abs_return). Used to freeze feature order for a
    trained model bundle (build guide K12's features.json).
    """
    cols = ["buy_share"]
    for window in WINDOWS_MIN:
        for label in ("buy", "vol", "trades", "absret"):
            cols.append(f"z_{label}_{window}")
        for label in ("buy", "vol", "trades", "absret"):
            cols.append(f"r_{label}_{window}")
        cols.append(f"quiet_accum_{window}")
    return cols
