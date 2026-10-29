
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EVENTS_FILE = PROJECT_ROOT / "data" / "processed" / "events.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "binance_klines"
MANIFEST_FILE = PROJECT_ROOT / "data" / "processed" / "kline_manifest.csv"

BASE_URL = "https://data.binance.vision/data/spot/daily/klines"
WORKERS = 16
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
BATCH_SIZE = 100


def build_tasks(events):
    """Create unique pair/date tasks for event days and the day before."""
    required = {"pair", "t_telegram"}
    missing = required - set(events.columns)

    if missing:
        raise ValueError(f"Missing event columns: {sorted(missing)}")

    events = events.copy()
    events["t_telegram"] = pd.to_datetime(
        events["t_telegram"], utc=True, errors="raise"
    )

    pairs = sorted(events["pair"].dropna().astype(str).str.upper().unique())
    dates = set()

    for timestamp in events["t_telegram"]:
        event_date = timestamp.date()
        dates.add(event_date)
        dates.add(event_date - pd.Timedelta(days=1))

    return [
        (pair, date.isoformat())
        for pair in pairs
        for date in sorted(dates)
    ]


def get_archive_path(pair, date):
    return OUTPUT_DIR / pair / "1m" / f"{pair}-1m-{date}.zip"


def download_one(pair, date):
    """Download one ZIP safely, retrying temporary failures."""
    destination = get_archive_path(pair, date)
    destination.parent.mkdir(parents=True, exist_ok=True)

    relative_path = str(destination.relative_to(PROJECT_ROOT))
    url = f"{BASE_URL}/{pair}/1m/{pair}-1m-{date}.zip"
    temporary = destination.with_suffix(".zip.part")

    if destination.exists() and zipfile.is_zipfile(destination):
        return {
            "pair": pair, "date": date, "status": "exists",
            "path": relative_path, "detail": ""
        }

    if destination.exists():
        destination.unlink()

    last_error = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = Request(
                url,
                headers={"User-Agent": "PumpRadar-Research/1.0"},
            )

            with urlopen(request, timeout=TIMEOUT_SECONDS) as response, open(temporary, "wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)

            if not zipfile.is_zipfile(temporary):
                raise ValueError("Downloaded file is not a valid ZIP")

            temporary.replace(destination)

            return {
                "pair": pair, "date": date, "status": "downloaded",
                "path": relative_path, "detail": ""
            }

        except HTTPError as exc:
            temporary.unlink(missing_ok=True)

            if exc.code == 404:
                return {
                    "pair": pair, "date": date, "status": "missing_404",
                    "path": "", "detail": "Archive not found"
                }

            last_error = f"HTTP {exc.code}: {exc.reason}"

        except (URLError, TimeoutError, OSError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < MAX_ATTEMPTS:
            time.sleep(attempt * 2)

    return {
        "pair": pair, "date": date, "status": "error",
        "path": "", "detail": last_error
    }


def append_manifest(records):
    """Persist each batch so progress survives interruption."""
    if not records:
        return

    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(records)

    frame.to_csv(
        MANIFEST_FILE,
        mode="a",
        header=not MANIFEST_FILE.exists(),
        index=False,
    )


def main():
    if not EVENTS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {EVENTS_FILE}. Run prepare_events.py first."
        )

    events = pd.read_parquet(EVENTS_FILE)
    tasks = build_tasks(events)

    print(f"Events: {len(events)}")
    print(f"Unique pairs: {events['pair'].nunique()}")
    print(f"Unique pair/date tasks: {len(tasks)}")
    print(f"Parallel workers: {WORKERS}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Manifest: {MANIFEST_FILE}")

    # Remove old manifest so this run has one clean record.
    # Existing valid ZIP archives are still skipped.
    MANIFEST_FILE.unlink(missing_ok=True)

    total = len(tasks)
    completed = 0

    for start in range(0, total, BATCH_SIZE):
        batch = tasks[start:start + BATCH_SIZE]
        results = []

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(download_one, pair, date): (pair, date)
                for pair, date in batch
            }

            for future in as_completed(futures):
                pair, date = futures[future]

                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - record each worker failure and continue the batch
                    result = {
                        "pair": pair, "date": date, "status": "error",
                        "path": "",
                        "detail": f"{type(exc).__name__}: {exc}",
                    }

                results.append(result)
                completed += 1

        append_manifest(results)

        counts = pd.DataFrame(results)["status"].value_counts().to_dict()
        print(
            f"Progress: {completed}/{total} | "
            f"Batch results: {counts}"
        )

    manifest = pd.read_csv(MANIFEST_FILE)

    print("\nFinal download summary:")
    print(manifest["status"].value_counts().to_string())
    print(f"\nManifest saved to: {MANIFEST_FILE}")

    available = manifest["status"].isin(["downloaded", "exists"]).sum()
    print(f"Archives available: {available}/{len(manifest)}")

    print(
        "\nNext: validate candle coverage and missing archives "
        "before onset detection."
    )


if __name__ == "__main__":
    main()
