# PumpRadar platform slice

This implements Aveek's **platform** workstream from the build guide: a same-origin dashboard, minute-bar API, public Binance closed-candle feeder, exchange-minute batching, SQLite alert log, Server-Sent Events (SSE), and replay through the same `Radar.ingest` code. The scorer is still a **demo heuristic**, not a trained pump probability, calibrated alert, or trading signal.

Requires Python 3.12. From this directory:

```bash
pip install -r requirements.txt
python -m uvicorn pumpradar.api:app --reload
```

On Windows Git Bash after creating a `.venv`, use `./.venv/Scripts/python.exe` instead of `python`. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the dashboard and `/docs` for the API. The API binds to localhost by default.

## Feed live public candles

In a **second terminal** in the project directory, start with a small set of BTC pairs:

```bash
python -m pumpradar.live --symbols ETHBTC,BNBBTC
```

After verifying the connection and local scoring, use `--all-btc` to discover all currently trading BTC spot pairs. The feeder fetches five recently completed minute bars per symbol for warmup, connects to Binance's public market-data stream, ignores unfinished candles, and sends one minute at a time to `/batches`. It waits up to three seconds for the selected symbols and retries unacknowledged batches after reconnecting. A missing coin is absent from that minute's ranking. The feed requires network access to `data-api.binance.vision` and `data-stream.binance.vision` from your machine; it needs no API key.

To check every discovered pair across three completed minutes, run `python -m pumpradar.live --all-btc --verify-minutes 3` with the API running. The terminal prints `coverage <minute>: received/expected pairs; missing: ...` for each frame and exits with code 0 only when all three frames included every pair. A nonzero exit means at least one minute missed a pair or the five-minute verification timeout elapsed. The current BTC pair count is discovered at runtime, so it need not equal the historical estimate of 130. Compare `/radar` at the reported minute with the received count. An empty or sparse pair may fail this strict completeness check; investigate its missing candles before claiming full coverage.

Run with `--no-warmup` if the local API already has recent bars. Stop the feeder with Ctrl+C. The dashboard refreshes the latest minute every five seconds and receives new alerts over `/events`.

## Manual and replay API

`POST /bars` accepts one closed UTC minute bar. A coin needs five **earlier accepted bars** before it receives a demo score. Submit consecutive minutes in increasing order. `POST /batches` accepts `{"bars": [...]}` for multiple coins with the same close time; identical batch retries succeed without double scoring. `GET /radar` returns only the latest minute's coins, and `GET /alerts` reads up to 100 persisted alerts.

The demo score is `clip((current BTC volume / earlier median BTC volume − 1) / 9, 0, 1) × taker-buy share`. Zero is common during ordinary minutes: volume at or below the median yields 0 regardless of buy share. The dashboard shows both parts of the calculation; this is not a pump probability.

Example bar:

```json
{"symbol":"FOOBTC","close_time":"2020-01-01T00:00:00+00:00","close":0.00001,"volume_btc":1.2,"taker_buy_btc":0.9,"trade_count":42}
```

`POST /replay` accepts `{ "bars": [...], "onset_time": "2020-01-01T00:10:00+00:00" }`. Replay sorts the bars by time, creates fresh state, and reports a first pre-onset alert and lead time when one exists. It does not alter live state or persist replay alerts.

## Development

```bash
python -m pytest
python -m ruff check .
```

Set `PUMPRADAR_DB` to an SQLite file path if you want alerts outside the project directory. The default is `alerts.sqlite3` in the server's working directory. Scores and warmup history remain in memory; restarting the API clears those, while alert records stay in SQLite. Run one API worker because this slice has in-process state.

### Next integration

- Replace `Radar.ingest`'s volume heuristic with the team's **one shared feature module** and trained hazard model. The feature and scoring path must remain identical in replay and live use.
- Add historical archive warmup and gap recovery, a 24-hour baseline, liquidity-tier thresholds and a tested false-alert budget. The current five-bar median and fixed 0.8 threshold are for wiring the platform only.
- Implement trade-based features, candlestick and risk-curve views, event selection and the full two-hour replay after research data contracts settle.
- Measure 5-second latency and 48-hour stability before claiming the build guide's platform acceptance criteria. Live Binance connectivity has not been exercised by the local unit tests.
