
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_FILE = PROJECT_ROOT / "data" / "processed" / "events.parquet"
KLINE_DIR = PROJECT_ROOT / "data" / "raw" / "binance_klines"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "onset_results.parquet"

BASELINE_HOURS = 24
EXCLUDED_RECENT_MINUTES = 60
SEARCH_BEFORE_MINUTES = 5
SEARCH_AFTER_MINUTES = 2
SPIKE_MULTIPLIER = 10
MIN_BASELINE_MINUTES = 60


def load_pair_bars(
    pair: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Load available daily ZIP files overlapping a UTC time range."""
    dates = pd.date_range(
        start=start.floor("D"),
        end=end.floor("D"),
        freq="D",
    )

    frames = []

    for day in dates:
        date_text = day.strftime("%Y-%m-%d")
        archive = (
            KLINE_DIR / pair / "1m"
            / f"{pair}-1m-{date_text}.zip"
        )

        if not archive.exists():
            continue

        try:
            with ZipFile(archive) as zf:
                csv_names = [
                    name for name in zf.namelist()
                    if name.lower().endswith(".csv")
                ]

                if not csv_names:
                    continue

                with zf.open(csv_names[0]) as file:
                    bars = pd.read_csv(file, header=None)

            if bars.shape[1] < 11:
                continue

            # Binance kline columns:
            # 0=open time, 7=quote volume, 8=trade count,
            # 10=taker-buy quote volume.
            open_time = pd.to_numeric(
                bars.iloc[:, 0], errors="coerce"
            )
            valid_times = open_time.dropna()

            if valid_times.empty:
                continue

            unit = "us" if valid_times.iloc[0] > 1e14 else "ms"

            frame = pd.DataFrame({
                "minute": pd.to_datetime(
                    open_time,
                    unit=unit,
                    utc=True,
                    errors="coerce",
                ),
                "quote_volume": pd.to_numeric(
                    bars.iloc[:, 7], errors="coerce"
                ),
                "count": pd.to_numeric(
                    bars.iloc[:, 8], errors="coerce"
                ),
                "taker_buy_quote": pd.to_numeric(
                    bars.iloc[:, 10], errors="coerce"
                ),
            })

            frames.append(frame)

        except (OSError, ValueError, IndexError, KeyError):
            continue

    if not frames:
        return pd.DataFrame(
            columns=[
                "minute",
                "quote_volume",
                "count",
                "taker_buy_quote",
            ]
        )

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["minute"])
    combined = combined.drop_duplicates("minute")
    combined = combined.sort_values("minute")

    return combined.loc[
        (combined["minute"] >= start)
        & (combined["minute"] <= end)
    ].reset_index(drop=True)


def robust_threshold(
    values: pd.Series,
) -> tuple[float, str]:
    """
    Calculate median + 10 estimated robust standard deviations.

    Use MAD when its scale is positive. If MAD is zero, use IQR
    as a fallback. Return an unavailable method if neither scale
    estimate is usable.
    """
    values = pd.to_numeric(values, errors="coerce").dropna()

    if len(values) < MIN_BASELINE_MINUTES:
        return np.nan, "insufficient_baseline"

    median = values.median()
    mad = (values - median).abs().median()
    robust_sd = 1.4826 * mad

    if np.isfinite(robust_sd) and robust_sd > 0:
        threshold = median + SPIKE_MULTIPLIER * robust_sd
        return float(threshold), "mad"

    q25 = values.quantile(0.25)
    q75 = values.quantile(0.75)
    iqr = q75 - q25

    if np.isfinite(iqr) and iqr > 0:
        iqr_scale = iqr / 1.349
        threshold = median + SPIKE_MULTIPLIER * iqr_scale
        return float(threshold), "iqr_fallback"

    return np.nan, "unavailable"


def detect_event_onset(row: pd.Series) -> dict:
    pair = str(row["pair"]).strip().upper()
    telegram_time = pd.to_datetime(row["t_telegram"], utc=True)

    baseline_end = telegram_time - pd.Timedelta(
        minutes=EXCLUDED_RECENT_MINUTES
    )
    baseline_start = baseline_end - pd.Timedelta(
        hours=BASELINE_HOURS
    )

    search_start = telegram_time - pd.Timedelta(
        minutes=SEARCH_BEFORE_MINUTES
    )
    search_end = telegram_time + pd.Timedelta(
        minutes=SEARCH_AFTER_MINUTES
    )

    bars = load_pair_bars(pair, baseline_start, search_end)

    result = {
        "event_id": row["event_id"],
        "t_onset": telegram_time,
        "no_spike": pd.NA,
        "onset_status": "missing_data",
        "threshold_method": "unavailable",
        "baseline_minutes": 0,
        "search_minutes": 0,
        "threshold": np.nan,
    }

    if bars.empty:
        return result

    baseline = bars.loc[
        (bars["minute"] >= baseline_start)
        & (bars["minute"] < baseline_end),
        "taker_buy_quote",
    ].dropna()

    search = bars.loc[
        (bars["minute"] >= search_start)
        & (bars["minute"] <= search_end)
    ].sort_values("minute")

    result["baseline_minutes"] = len(baseline)
    result["search_minutes"] = len(search)

    if len(baseline) < MIN_BASELINE_MINUTES:
        result["onset_status"] = "insufficient_baseline"
        return result

    expected_minutes = pd.date_range(
        search_start.floor("min"),
        search_end.floor("min"),
        freq="min",
    )
    available_minutes = pd.DatetimeIndex(search["minute"].unique())

    if not expected_minutes.isin(available_minutes).all():
        result["onset_status"] = "missing_search_data"
        return result

    threshold, threshold_method = robust_threshold(baseline)

    result["threshold"] = threshold
    result["threshold_method"] = threshold_method

    if not np.isfinite(threshold):
        if threshold_method == "insufficient_baseline":
            result["onset_status"] = "insufficient_baseline"
        else:
            result["onset_status"] = "threshold_unavailable"
        return result

    spikes = search.loc[
        search["taker_buy_quote"] >= threshold
    ]

    if spikes.empty:
        result["no_spike"] = True
        result["onset_status"] = "no_spike"
    else:
        result["t_onset"] = spikes.iloc[0]["minute"]
        result["no_spike"] = False
        result["onset_status"] = "spike_detected"

    return result


def main() -> None:
    if not EVENTS_FILE.exists():
        raise FileNotFoundError(
            f"Events file not found: {EVENTS_FILE}"
        )

    events = pd.read_parquet(EVENTS_FILE)

    required = {"event_id", "pair", "t_telegram", "era"}
    missing = required - set(events.columns)

    if missing:
        raise ValueError(
            f"Events table missing columns: {sorted(missing)}"
        )

    results = []

    for number, (_, row) in enumerate(
        events.iterrows(), start=1
    ):
        results.append(detect_event_onset(row))

        if number % 25 == 0 or number == len(events):
            print(f"Processed {number}/{len(events)} events")

    onset_results = pd.DataFrame(results)
    onset_results["no_spike"] = onset_results["no_spike"].astype(
        "boolean"
    )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    onset_results.to_parquet(OUTPUT_FILE, index=False)

    print("\nOnset status summary:")
    print(
        onset_results["onset_status"]
        .value_counts(dropna=False)
        .to_string()
    )

    print("\nThreshold method summary:")
    print(
        onset_results["threshold_method"]
        .value_counts(dropna=False)
        .to_string()
    )

    print(f"\nSaved onset results to: {OUTPUT_FILE}")
    print("The original events.parquet file was not modified.")


if __name__ == "__main__":
    main()
