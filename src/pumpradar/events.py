"""Event table and onset detection pipeline for PumpRadar.

Fulfills Step D1 and D3 of the build guide:
- Builds events table from pump_telegram.csv (Binance pairs, UTC timestamps, 30m merging, train/test era split).
- Identifies market onset (t_onset) using pre-announcement trading volume spikes.
- Saves clean contract hand-off table to data/processed/events.parquet.
"""

from pathlib import Path
import pandas as pd

from pumpradar.prepare_events import (
    INPUT_FILE as TELEGRAM_CSV,
    MERGE_WINDOW,
    PROJECT_ROOT,
    TEST_START,
    prepare_events,
)
from pumpradar.detect_onsets import (
    EVENTS_FILE,
    FIGURE_FILE,
    OUTPUT_FILE as ONSET_RESULTS_FILE,
    detect_event_onset,
    load_pair_bars,
    plot_offsets,
    robust_threshold,
)

CONTRACT_COLUMNS = ["event_id", "pair", "t_telegram", "t_onset", "era"]


def get_contract_events(events_df: pd.DataFrame) -> pd.DataFrame:
    """Filter and order columns to strictly match Section 3.2 hand-off contract."""
    missing = set(CONTRACT_COLUMNS) - set(events_df.columns)
    if missing:
        raise ValueError(f"Events table missing contract columns: {sorted(missing)}")
    return events_df[CONTRACT_COLUMNS].copy()


def run_pipeline() -> pd.DataFrame:
    """Run full event preparation and onset detection pipeline."""
    print("=== Step D1: Preparing event table ===")
    events = prepare_events()

    print("\n=== Step D3: Detecting market onsets ===")
    from pumpradar.detect_onsets import main as run_detect_onsets
    run_detect_onsets()

    # Re-read the resulting events table
    full_events = pd.read_parquet(EVENTS_FILE)
    print("\n=== Hand-off Contract Check (Section 3.2) ===")
    contract_df = get_contract_events(full_events)
    print(f"Total events: {len(contract_df)}")
    print(f"Contract columns: {list(contract_df.columns)}")
    print(f"Era distribution:\n{contract_df['era'].value_counts().to_string()}")

    return full_events


if __name__ == "__main__":
    run_pipeline()
