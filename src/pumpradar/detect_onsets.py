
from pathlib import Path
from zipfile import ZipFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_FILE = PROJECT_ROOT / "data" / "processed" / "events.parquet"
KLINE_DIR = PROJECT_ROOT / "data" / "raw" / "binance_klines"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "onset_results.parquet"
FIGURE_FILE = PROJECT_ROOT / "figures" / "telegram_minus_onset.png"
ALT_FIGURE_FILE = PROJECT_ROOT / "figures" / "telegram_minus_onset_alt.png"

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
    """Load available daily Binance kline ZIPs for a UTC time range."""
    frames = []

    for day in pd.date_range(start=start.floor("D"), end=end.floor("D"), freq="D"):
        date_text = day.strftime("%Y-%m-%d")
        archive = KLINE_DIR / pair / "1m" / f"{pair}-1m-{date_text}.zip"

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

            open_time = pd.to_numeric(bars.iloc[:, 0], errors="coerce")
            valid_times = open_time.dropna()
            if valid_times.empty:
                continue

            unit = "us" if valid_times.iloc[0] > 1e14 else "ms"
            frames.append(pd.DataFrame({
                "minute": pd.to_datetime(
                    open_time, unit=unit, utc=True, errors="coerce"
                ),
                "taker_buy_quote": pd.to_numeric(
                    bars.iloc[:, 10], errors="coerce"
                ),
            }))

        except (OSError, ValueError, IndexError, KeyError):
            continue

    if not frames:
        return pd.DataFrame(columns=["minute", "taker_buy_quote"])

    combined = pd.concat(frames, ignore_index=True)
    combined = (
        combined.dropna(subset=["minute"])
        .drop_duplicates("minute")
        .sort_values("minute")
    )

    return combined.loc[
        (combined["minute"] >= start) & (combined["minute"] <= end)
    ].reset_index(drop=True)


def robust_threshold(values: pd.Series) -> tuple[float, str]:
    """Guide method: median plus 10 robust SDs, with robust SD = IQR / 1.349."""
    values = pd.to_numeric(values, errors="coerce").dropna()

    if len(values) < MIN_BASELINE_MINUTES:
        return np.nan, "insufficient_baseline"

    median = values.median()
    iqr = values.quantile(0.75) - values.quantile(0.25)

    if not np.isfinite(iqr) or iqr <= 0:
        return np.nan, "zero_iqr"

    return float(median + SPIKE_MULTIPLIER * (iqr / 1.349)), "iqr"


def first_spike(
    search: pd.DataFrame,
    threshold: float,
) -> object:
    """Return the first search minute meeting a valid threshold."""
    if not np.isfinite(threshold):
        return pd.NaT

    spikes = search.loc[search["taker_buy_quote"] >= threshold]
    if spikes.empty:
        return pd.NaT
    return spikes.iloc[0]["minute"]


def alternative_threshold(values: pd.Series) -> tuple[float, str]:
    """
    Sensitivity-only deviation: use the standard deviation of nonzero
    baseline observations. This is not the guide's main method.
    """
    nonzero = pd.to_numeric(values, errors="coerce").dropna()
    nonzero = nonzero[nonzero > 0]

    if len(nonzero) < 2:
        return np.nan, "alt_scale_unavailable"

    scale = nonzero.std(ddof=1)
    if not np.isfinite(scale) or scale <= 0:
        return np.nan, "alt_scale_unavailable"

    # Retain the full baseline median as the centre, changing only the scale.
    centre = pd.to_numeric(values, errors="coerce").dropna().median()
    return float(centre + SPIKE_MULTIPLIER * scale), "nonzero_sd_sensitivity"


def detect_event_onset(row: pd.Series) -> dict:
    pair = str(row["pair"]).strip().upper()
    telegram_time = pd.to_datetime(row["t_telegram"], utc=True)

    baseline_end = telegram_time - pd.Timedelta(
        minutes=EXCLUDED_RECENT_MINUTES
    )
    baseline_start = baseline_end - pd.Timedelta(hours=BASELINE_HOURS)
    search_start = telegram_time - pd.Timedelta(minutes=SEARCH_BEFORE_MINUTES)
    search_end = telegram_time + pd.Timedelta(minutes=SEARCH_AFTER_MINUTES)

    result = {
        "event_id": row["event_id"],
        "t_onset": telegram_time,
        "t_onset_alt": pd.NaT,
        "no_spike": pd.NA,
        "onset_flag": "no_data",
        "onset_status": "missing_data",
        "threshold_method": "unavailable",
        "threshold": np.nan,
        "alt_threshold": np.nan,
        "alt_method": "not_applicable",
        "baseline_minutes": 0,
        "search_minutes": 0,
    }

    bars = load_pair_bars(pair, baseline_start, search_end)
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
        result["onset_flag"] = "no_data"
        result["onset_status"] = "insufficient_baseline"
        return result

    expected = pd.date_range(
        search_start.floor("min"), search_end.floor("min"), freq="min"
    )
    available = pd.DatetimeIndex(search["minute"].unique())
    if not expected.isin(available).all():
        result["onset_flag"] = "no_data"
        result["onset_status"] = "missing_search_data"
        return result

    threshold, method = robust_threshold(baseline)
    result["threshold"] = threshold
    result["threshold_method"] = method

    if method == "zero_iqr":
        result["onset_flag"] = "zero_iqr"
        result["onset_status"] = "threshold_unavailable"

        alt_threshold, alt_method = alternative_threshold(baseline)
        result["alt_threshold"] = alt_threshold
        result["alt_method"] = alt_method

        alt_onset = first_spike(search, alt_threshold)
        if pd.notna(alt_onset):
            result["t_onset_alt"] = alt_onset
        return result

    if not np.isfinite(threshold):
        result["onset_flag"] = "no_data"
        result["onset_status"] = "insufficient_baseline"
        return result

    onset = first_spike(search, threshold)
    if pd.isna(onset):
        result["no_spike"] = True
        result["onset_flag"] = "no_spike"
        result["onset_status"] = "no_spike"
    else:
        result["t_onset"] = onset
        result["t_onset_alt"] = onset
        result["no_spike"] = False
        result["onset_flag"] = "ok"
        result["onset_status"] = "spike_detected"

    return result


def plot_offsets(
    results: pd.DataFrame,
    events: pd.DataFrame,
    timestamp_column: str,
    output_path: Path,
    title: str,
) -> None:
    telegram_times = events.set_index("event_id")["t_telegram"]
    telegram_times = pd.to_datetime(telegram_times, utc=True)
    telegram_for_result = results["event_id"].map(telegram_times)
    onset_times = pd.to_datetime(results[timestamp_column], utc=True)

    offsets = (
        (telegram_for_result - onset_times)
        .dt.total_seconds()
        .div(60)
        .dropna()
    )

    plt.figure(figsize=(8, 5))
    plt.hist(offsets, bins=np.arange(-6.5, 8.5, 1), edgecolor="black")
    plt.xlabel("Telegram timestamp minus onset (minutes)")
    plt.ylabel("Number of events")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def main() -> None:
    if not EVENTS_FILE.exists():
        raise FileNotFoundError(f"Events file not found: {EVENTS_FILE}")

    events = pd.read_parquet(EVENTS_FILE)
    required = {"event_id", "pair", "t_telegram", "era"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Events table missing columns: {sorted(missing)}")

    # Preserve original Telegram times for plots, including safe reruns.
    events["t_telegram"] = pd.to_datetime(events["t_telegram"], utc=True)

    results = []
    for number, (_, row) in enumerate(events.iterrows(), start=1):
        results.append(detect_event_onset(row))
        if number % 25 == 0 or number == len(events):
            print(f"Processed {number}/{len(events)} events")

    onset_results = pd.DataFrame(results)
    onset_results["no_spike"] = onset_results["no_spike"].astype("boolean")
    onset_results["t_onset_alt"] = pd.to_datetime(
        onset_results["t_onset_alt"], utc=True
    )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    onset_results.to_parquet(OUTPUT_FILE, index=False)

    onset_columns = [
        "event_id", "t_onset", "t_onset_alt", "no_spike", "onset_flag",
        "onset_status", "threshold_method", "threshold", "alt_threshold",
        "alt_method", "baseline_minutes", "search_minutes",
    ]
    base_events = events.drop(
        columns=[c for c in onset_columns if c != "event_id" and c in events],
        errors="ignore",
    )
    final_events = base_events.merge(
        onset_results[onset_columns],
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    final_events.to_parquet(EVENTS_FILE, index=False)

    FIGURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    plot_offsets(
        onset_results, events, "t_onset", FIGURE_FILE,
        "Main onset: Telegram Time Minus Market Onset",
    )
    plot_offsets(
        onset_results, events, "t_onset_alt", ALT_FIGURE_FILE,
        "Sensitivity analysis: Telegram Time Minus Alternative Onset",
    )

    print("\nOnset flag summary:")
    print(onset_results["onset_flag"].value_counts(dropna=False).to_string())
    print("\nOnset status summary:")
    print(onset_results["onset_status"].value_counts(dropna=False).to_string())
    print("\nNo-spike events:", int(onset_results["onset_flag"].eq("no_spike").sum()))
    print("Zero-IQR events:", int(onset_results["onset_flag"].eq("zero_iqr").sum()))
    print("No-data events:", int(onset_results["onset_flag"].eq("no_data").sum()))
    print("Alternative onset available:",
          int(onset_results["t_onset_alt"].notna().sum()))
    print(f"\nUpdated event table: {EVENTS_FILE}")
    print(f"Detailed onset results: {OUTPUT_FILE}")
    print(f"Main histogram: {FIGURE_FILE}")
    print(f"Alternative histogram: {ALT_FIGURE_FILE}")


if __name__ == "__main__":
    main()
