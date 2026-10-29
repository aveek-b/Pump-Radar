
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "data" / "raw" / "pump_telegram.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "events.parquet"

MERGE_WINDOW = pd.Timedelta(minutes=30)
TEST_START = pd.Timestamp("2020-01-01", tz="UTC")


def prepare_events() -> pd.DataFrame:
    # 1. Read the original dataset.
    df = pd.read_csv(INPUT_FILE)

    required = {"symbol", "group", "date", "hour", "exchange"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    # 2. Keep only Binance events.
    df = df.loc[
        df["exchange"].astype(str).str.strip().str.lower() == "binance"
    ].copy()

    # 3. Combine date and hour into a UTC timestamp.
    df["event_time"] = pd.to_datetime(
        df["date"].astype(str).str.strip()
        + " "
        + df["hour"].astype(str).str.strip(),
        format="%Y-%m-%d %H:%M",
        errors="raise",
        utc=True,
    )

    # 4. Create the BTC trading pair and sort chronologically.
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["pair"] = df["symbol"] + "BTC"

    df = df.sort_values(
        ["pair", "event_time"]
    ).reset_index(drop=True)

    # 5. Merge events for the same pair when consecutive
    # events are no more than 30 minutes apart.
    gap = df.groupby("pair")["event_time"].diff()

    new_event = gap.isna() | (gap > MERGE_WINDOW)

    df["event_number"] = new_event.groupby(df["pair"]).cumsum()

    events = (
        df.groupby(["pair", "event_number"], as_index=False)
        .agg(
            symbol=("symbol", "first"),
            t_telegram=("event_time", "min"),
            source_group=("group", "first"),
            source_event_count=("symbol", "size"),
        )
        .drop(columns="event_number")
        .sort_values(["t_telegram", "pair"])
        .reset_index(drop=True)
    )

    # 6. Assign event IDs.
    events.insert(
        0,
        "event_id",
        [f"event_{i:04d}" for i in range(1, len(events) + 1)],
    )

    # 7. Assign train/test eras using the event timestamp.
    events["era"] = events["t_telegram"].lt(TEST_START).map(
        {True: "train", False: "test"}
    )

    # 8. Save the processed event table.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    events.to_parquet(OUTPUT_FILE, index=False)

    # 9. Print a summary for verification.
    print(f"Input Binance rows: {len(df)}")
    print(f"Processed events: {len(events)}")

    print("\nEvents by era:")
    print(events["era"].value_counts().sort_index().to_string())

    print(f"\nSaved to: {OUTPUT_FILE}")

    print("\nFirst five events:")
    print(events.head().to_string(index=False))

    return events


if __name__ == "__main__":
    prepare_events()
