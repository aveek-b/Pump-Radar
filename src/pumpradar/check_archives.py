
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd


BASE_URL = "https://data.binance.vision/data/spot/daily/klines"
WORKERS = 8

# A small sample across older and newer periods.
SAMPLES = [
    ("PPTBTC", "2018-01-03"),
    ("PPTBTC", "2018-01-04"),
    ("KMDBTC", "2018-06-15"),
    ("NAVBTC", "2019-06-15"),
    ("BTCUSDT", "2020-06-15"),
    ("PPTBTC", "2021-01-18"),
]


def check_archive(pair: str, date: str) -> dict:
    url = f"{BASE_URL}/{pair}/1m/{pair}-1m-{date}.zip"
    request = Request(
        url,
        method="HEAD",
        headers={"User-Agent": "PumpRadar-Research/1.0"},
    )

    try:
        with urlopen(request, timeout=20) as response:
            return {
                "pair": pair,
                "date": date,
                "status": "available",
                "http_status": response.status,
            }
    except HTTPError as exc:
        return {
            "pair": pair,
            "date": date,
            "status": "missing" if exc.code == 404 else "http_error",
            "http_status": exc.code,
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "pair": pair,
            "date": date,
            "status": "connection_error",
            "http_status": str(exc),
        }


def main() -> None:
    print("Checking a small sample of Binance daily archives...\n")

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [
            executor.submit(check_archive, pair, date)
            for pair, date in SAMPLES
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(result)

    print("\nSummary:")
    print(pd.DataFrame(results)["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
