"""Binance kline archive downloader for PumpRadar.

Fulfills Step D2 of the build guide:
Fetches 1-minute klines from data.binance.vision for universe pairs on event dates and preceding days.
"""

from pumpradar.download_klines import (  # noqa: F401
    BASE_URL,
    BATCH_SIZE,
    EVENTS_FILE,
    MANIFEST_FILE,
    MAX_ATTEMPTS,
    OUTPUT_DIR,
    TIMEOUT_SECONDS,
    WORKERS,
    append_manifest,
    build_tasks,
    download_one,
    get_archive_path,
    main,
)

if __name__ == "__main__":
    main()
