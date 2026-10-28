"""Leakage-aware rolling features for PumpRadar minute bars."""

import gc

import numpy as np
import pandas as pd

WINDOWS = (5, 15, 60)

REQUIRED_COLUMNS = {
    "minute",
    "close",
    "quote_volume",
    "count",
    "taker_buy_quote",
}


def robust_z(series: pd.Series, window: int) -> pd.Series:
    """Compare rolling sums against a trailing robust baseline."""
    rolling_sum = series.rolling(window, min_periods=window).sum()
    reference = rolling_sum.shift(60)
    baseline = reference.rolling(1380, min_periods=600)

    median = baseline.median()
    q75 = baseline.quantile(0.75)
    q25 = baseline.quantile(0.25)
    robust_scale = (q75 - q25) / 1.349

    result = (rolling_sum - median) / (robust_scale + 1e-9)

    del reference, baseline, median, q75, q25, robust_scale
    gc.collect()

    return result


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Return one row per input minute with causal rolling features."""
    missing = REQUIRED_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = bars.copy()
    df["minute"] = pd.to_datetime(df["minute"], utc=True, errors="raise")
    df = (
        df.sort_values("minute")
        .drop_duplicates("minute", keep="last")
        .reset_index(drop=True)
    )

    for column in ("close", "quote_volume", "count", "taker_buy_quote"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["abs_return"] = df["close"].pct_change().abs()

    for window in WINDOWS:
        for name, source in (
            ("buy", "taker_buy_quote"),
            ("volume", "quote_volume"),
            ("trades", "count"),
            ("abs_return", "abs_return"),
        ):
            df[f"z_{name}_{window}"] = robust_z(df[source], window)

        df[f"quiet_accumulation_{window}"] = (
            df[f"z_volume_{window}"] - df[f"z_abs_return_{window}"]
        )

    df["buy_share"] = (
        df["taker_buy_quote"]
        / df["quote_volume"].replace(0, np.nan)
    )

    return df
