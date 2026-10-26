
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EVENTS_FILE = ROOT / "data" / "processed" / "events.parquet"
MANIFEST_FILE = ROOT / "data" / "processed" / "kline_manifest.csv"
KLINE_DIR = ROOT / "data" / "raw" / "binance_klines"


def main():
    events = pd.read_parquet(EVENTS_FILE)
    manifest = pd.read_csv(MANIFEST_FILE, dtype=str)

    print("=== Overall manifest ===")
    print(manifest["status"].value_counts(dropna=False).to_string())

    print("\n=== Archive status by year ===")
    manifest["year"] = pd.to_datetime(
        manifest["date"], errors="coerce"
    ).dt.year
    print(pd.crosstab(manifest["year"], manifest["status"]).to_string())

    # Check whether each event's own pair has archives for
    # its event date and the preceding calendar date.
    status_lookup = {
        (row.pair, row.date): row.status
        for row in manifest.itertuples(index=False)
    }

    event_checks = []

    for row in events.itertuples(index=False):
        event_date = pd.to_datetime(row.t_telegram, utc=True).date()
        pair = str(row.pair).upper()

        for day in [event_date - pd.Timedelta(days=1), event_date]:
            date_text = day.isoformat()
            status = status_lookup.get((pair, date_text), "not_in_manifest")
            event_checks.append({
                "event_id": row.event_id,
                "pair": pair,
                "date": date_text,
                "status": status,
            })

    checks = pd.DataFrame(event_checks)

    print("\n=== Event-pair archive coverage ===")
    print(checks["status"].value_counts(dropna=False).to_string())

    event_summary = (
        checks.assign(available=checks["status"].isin(["downloaded", "exists"]))
        .groupby("event_id")["available"]
        .sum()
    )

    print("\nEvents with both required archives available:",
          int((event_summary == 2).sum()), "/", len(events))
    print("Events with at least one required archive missing:",
          int((event_summary < 2).sum()), "/", len(events))

    # Check ZIP integrity for all archives marked downloaded or exists.
    print("\n=== ZIP integrity check ===")
    candidates = manifest.loc[
        manifest["status"].isin(["downloaded", "exists"])
    ]

    valid = 0
    invalid = []

    for row in candidates.itertuples(index=False):
        path = KLINE_DIR / row.pair / "1m" / (
            f"{row.pair}-1m-{row.date}.zip"
        )

        try:
            if not path.exists():
                raise FileNotFoundError("Archive file missing")

            with ZipFile(path) as archive:
                bad_member = archive.testzip()

            if bad_member is not None:
                raise BadZipFile(f"Corrupt member: {bad_member}")

            valid += 1

        except (OSError, BadZipFile, FileNotFoundError) as exc:
            invalid.append((row.pair, row.date, str(exc)))

    print(f"Valid ZIPs: {valid}/{len(candidates)}")
    print(f"Invalid or missing ZIPs: {len(invalid)}")

    if invalid:
        print("\nFirst 10 invalid archives:")
        for item in invalid[:10]:
            print(item)

    checks.to_csv(
        ROOT / "data" / "processed" / "event_archive_coverage.csv",
        index=False,
    )
    print("\nSaved event archive coverage report.")


if __name__ == "__main__":
    main()
