"""Build the pre-onset cross-sectional dataset with bounded memory.

Place this file at src/pumpradar/build_xsec.py, then run
``python -m pumpradar.build_xsec`` from the repository root.
Requires pyarrow (also used by pandas to read/write Parquet).
"""

from collections import Counter
from pathlib import Path
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pumpradar.features import compute_features, WINDOWS

ROOT = Path(__file__).resolve().parents[2]
EVENTS_FILE = ROOT / "data" / "processed" / "events.parquet"
MANIFEST_FILE = ROOT / "data" / "processed" / "kline_manifest.csv"
OUTPUT_FILE = ROOT / "data" / "processed" / "xsec.parquet"

COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count", "taker_buy_base",
    "taker_buy_quote", "ignore",
]
BAR_COLS = ["minute", "close", "quote_volume", "count", "taker_buy_quote"]
RANK_SOURCES = [
    (f"z_{name}_{window}", f"r_{name}_{window}")
    for window in WINDOWS
    for name in ("buy", "volume", "trades", "abs_return")
]


def load_bars(path: Path) -> pd.DataFrame:
    """Read only the fields needed from one Binance daily ZIP."""
    with zipfile.ZipFile(path) as archive:
        csv_name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        with archive.open(csv_name) as file:
            bars = pd.read_csv(
                file, header=None, names=COLS,
                usecols=["open_time", "close", "quote_volume", "count", "taker_buy_quote"],
            )
    if bars.empty:
        return pd.DataFrame(columns=BAR_COLS)
    open_time = pd.to_numeric(bars.pop("open_time"), errors="raise")
    if open_time.iloc[0] > 1e14:
        open_time //= 1000
    bars.insert(0, "minute", pd.to_datetime(open_time, unit="ms", utc=True))
    return bars


def archive_index(manifest: pd.DataFrame) -> dict:
    result = {}
    for row in manifest.itertuples(index=False):
        if row.status not in ("downloaded", "exists") or pd.isna(row.path):
            continue
        path = ROOT / str(row.path).replace("\\", "/")
        if path.is_file():
            result[(str(row.pair).upper(), str(row.date)[:10])] = path
    return result


def pair_features_for_day(pair, day, paths, start, end):
    """Compute only rows needed on this event day, without bridging candle gaps.

    Two preceding days cover pre-midnight event windows and the shifted
    rolling baseline. Missing whole days and individual minutes split the
    history into separate continuous runs.
    """
    chunks = []
    for offset in (2, 1, 0):
        date = (day - pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
        path = paths.get((pair, date))
        if path is None:
            continue
        try:
            chunk = load_bars(path)
            if not chunk.empty:
                chunks.append(chunk)
        except (OSError, ValueError, StopIteration, zipfile.BadZipFile) as exc:
            print(f"Warning: skipped {pair} {date}: {exc}", flush=True)
    if not chunks:
        return None

    bars = (pd.concat(chunks, ignore_index=True)
            .drop_duplicates("minute", keep="last")
            .sort_values("minute").reset_index(drop=True))
    runs = bars["minute"].diff().ne(pd.Timedelta(minutes=1)).cumsum()
    needed = []
    for _, segment in bars.groupby(runs, sort=False):
        # A segment before the requested window cannot contribute output.
        if segment["minute"].iloc[-1] < start or segment["minute"].iloc[0] > end:
            continue
        features = compute_features(segment.reset_index(drop=True))
        features = features.loc[features["minute"].between(start, end)].copy()
        if not features.empty:
            features["pair"] = pair
            needed.append(features)
    return pd.concat(needed, ignore_index=True) if needed else None


def event_windows_for_day(day_events, universe, paths, day):
    bounds = [
        (event.t_onset - pd.Timedelta(minutes=120),
         event.t_onset - pd.Timedelta(minutes=1))
        for event in day_events.itertuples(index=False)
    ]
    start, end = min(s for s, _ in bounds), max(e for _, e in bounds)
    pair_frames = []
    for pair in universe:
        features = pair_features_for_day(pair, day, paths, start, end)
        if features is not None:
            # Keep only the union of actual event windows for this day.
            mask = pd.Series(False, index=features.index)
            for s, e in bounds:
                mask |= features["minute"].between(s, e)
            if mask.any():
                pair_frames.append(features.loc[mask].copy())
    if not pair_frames:
        return

    # All available coins at a given minute are present before ranking.
    ranked = pd.concat(pair_frames, ignore_index=True)
    del pair_frames
    for source, target in RANK_SOURCES:
        if source not in ranked:
            raise KeyError(f"compute_features did not return {source}")
        ranked[target] = ranked.groupby("minute")[source].rank(pct=True)

    for event in day_events.itertuples(index=False):
        start = event.t_onset - pd.Timedelta(minutes=120)
        end = event.t_onset - pd.Timedelta(minutes=1)
        window = ranked.loc[ranked["minute"].between(start, end)].copy()
        if window.empty:
            continue
        window["event_id"] = event.event_id
        window["event_pair"] = event.pair
        window["t_onset"] = event.t_onset
        window["era"] = event.era
        window["onset_status"] = event.onset_status
        window["no_spike"] = event.no_spike
        window["lead_min"] = float("nan")
        pumped = window["pair"].eq(event.pair)
        window.loc[pumped, "lead_min"] = (
            event.t_onset - window.loc[pumped, "minute"]
        ).dt.total_seconds() / 60
        yield window


def main():
    events = pd.read_parquet(EVENTS_FILE).copy()
    manifest = pd.read_csv(MANIFEST_FILE, dtype=str)
    events["pair"] = events["pair"].str.upper()
    events["t_onset"] = pd.to_datetime(events["t_onset"], utc=True)
    events = events.dropna(subset=["t_onset", "pair"]).copy()
    manifest["pair"] = manifest["pair"].str.upper()
    universe = sorted(events["pair"].unique())
    paths = archive_index(manifest)
    print(f"Events: {len(events)} | Universe: {len(universe)} pairs", flush=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_FILE.with_name(OUTPUT_FILE.name + ".partial")
    writer = None
    schema = None
    rows = 0
    event_rows = []
    pair_counts = Counter()
    null_counts = Counter()
    feature_cols = None
    try:
        events["onset_day"] = events["t_onset"].dt.floor("D")
        for day_number, (day, day_events) in enumerate(events.groupby("onset_day"), 1):
            for window in event_windows_for_day(day_events, universe, paths, day):
                if feature_cols is None:
                    feature_cols = [
                        c for c in window.columns
                        if c.startswith(("z_", "r_", "quiet_accumulation_"))
                        or c == "buy_share"
                    ]
                batch = len(window)
                rows += batch
                event_rows.append(batch)
                pair_counts.update(window["pair"].unique())
                for col in feature_cols:
                    null_counts[col] += int(window[col].isna().sum())
                table = pa.Table.from_pandas(window, preserve_index=False)
                if writer is None:
                    schema = table.schema
                    writer = pq.ParquetWriter(temporary, schema, compression="snappy")
                else:
                    table = table.select(schema.names).cast(schema)
                writer.write_table(table)
            print(f"Processed event day {day_number}: {day.date()}", flush=True)
        if writer is None:
            raise RuntimeError("No event windows could be assembled.")
    except BaseException:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
        raise
    writer.close()
    temporary.replace(OUTPUT_FILE)

    print(f"Saved: {OUTPUT_FILE}", flush=True)
    print(f"Rows: {rows:,}")
    print(f"Events represented: {len(event_rows)} / {len(events)}")
    print(f"Universe pairs: {len(pair_counts)}")
    print(f"Median rows per event: {pd.Series(event_rows).median():.0f}")
    missing = pd.Series({c: null_counts[c] / rows for c in feature_cols}).sort_values(ascending=False)
    print("\nFeature missingness (%):")
    print((missing * 100).round(2).to_string())
    if (missing > 0.02).any():
        print("\nWARNING: some features exceed 2% missingness.")
    if len(event_rows) < len(events):
        print("\nWARNING: some events have no rows in xsec.")


if __name__ == "__main__":
    main()
