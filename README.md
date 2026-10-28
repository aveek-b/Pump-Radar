# PumpRadar

## Project status (as of 2026-10-28, commit `7b6e606`)

Three deliverables: a deployed web platform, an executed research notebook, and a
research-style report. This section summarizes what's real and working right now,
what's missing, and where the risk is. Everything below is verifiable by running
`python -m pytest` and the commands in this file -- nothing here is aspirational.

### What's done

**Models & evaluation (Kaashvi)** -- Experiment A, the leakage audit, is complete and
real:
- Built against the actual SystemsLab-Sapienza dataset (482,157 rows, 317 confirmed
  pump events, 85 coins, 2018-2021), pulled via Git LFS and SHA-256 verified.
- Six models (Logistic Regression, KNN, Decision Tree, Random Forest, linear SVM,
  LightGBM) compared under a random-split audit baseline (P0) vs. an honest,
  event-grouped, chronologically embargoed split (P2), across six horizons and two
  feature sets, with validation-selected hyperparameters.
- Finding: clean (rush-order/volume/trade) features show no leakage-driven inflation,
  robust to split-boundary and seed sensitivity checks. Full features (adds price-level
  and time-of-day) show a real, protocol-driven inflation gap (ruled out as a
  training-size artifact) -- permutation importance traces this to **time-of-day
  encoding**, not price level as first hypothesized, and whether that's genuine
  pump-timing behavior or a small-sample artifact is not yet resolved.
- Best model: Random Forest / LightGBM, full features, honest split -- AP from 0.36
  (h=1, 57x base rate) down to 0.56 (h=60, 2.1x base rate). **Not calibrated, no
  alert threshold chosen, not a deployed model yet.**
- Full writeup: `paper/sections/results_kaashvi.md` (claims ledger included).
  Executed notebook: `notebooks/KD_pumpradar_complete.ipynb` (0 errors, restart-and-run-all verified).
  Raw results: `results/*.json`.

**Platform (this session, extending Aveek's original API/dashboard)**:
- `GET /universe`: every coin currently trading on live Binance (520 as of this
  writing), deduplicated across quote pairs, with real live price + 24h change.
  Verified live: as of 2026-10-28, **only 38 of those 520 coins have an actively
  trading BTC pair** -- the quote currency the trained model is defined on. Every
  coin gets a real price; only those 38 can ever show a real `scored` status, the
  rest are honestly `unavailable`, never a fabricated or guessed score.
- `GET /honesty`: the real Experiment A numbers above, served from `results/*.json`,
  with `calibration`/`alert_threshold` explicitly `"not_yet_run"`/`"not_yet_chosen"`
  rather than a plausible-looking placeholder.
- Dashboard (`web/index.html`) gained a **Live Universe** tab (search/filter/sort
  over all live coins, scoring-status badges) and an **Honesty & Method** tab
  (dataset size, AP-by-model table, live limitations list) alongside the original
  demo radar and alerts view. This extends the existing plain HTML/CSS/JS dashboard
  rather than introducing a new React/Vite/Tailwind toolchain -- that stack was
  planned in the build guide but never scaffolded, and starting it now without the
  ability to actually install/build/deploy it here would risk looking finished
  without being verified.
- All of the above was run against the live Binance API end to end (not just
  mocked tests) during development; one real bug (coins with both a BTC and USDT
  pair were incorrectly marked `unavailable` because display-quote preference was
  conflated with scoring eligibility) was caught this way and fixed.

**Data (Hannah, `origin/feat/data-events`, PR #1, open/unmerged as of this writing)**:
event table and onset-detection scripts, with honestly-reported real limitations
(318 events processed: 127 confirmed onset, 187 fallback-to-Telegram-time, 4 missing
data), and the real Sapienza dataset via Git LFS.

### What's not done / blocked

- **Experiment B (cross-sectional "which coin, how early" scoring) has not started.**
  It needs `features.py` / `xsec.parquet` from the data workstream, which is not yet
  in the shared repo. This is the actual deployment-candidate model the build guide
  specifies -- Experiment A is the leakage audit, not the final product.
- **No calibration, no alert-budget threshold.** Needs a disjoint calibration slice
  and ordinary-period background market data, neither available yet.
- **The live feed only covers the 38 live BTC pairs for scoring.** Reaching real
  scores for more of the 520 live coins requires training on an expanded quote-asset
  universe -- the build guide calls this "additional work, not a UI setting"; it has
  not been scoped or started.
- **No live/production deployment.** Everything above runs and is verified locally;
  there is no public URL, VM, or hosting account set up from this session.
- This status reflects what's in the **shared git repo** as of commit `7b6e606`
  (2026-10-28). It may understate real progress if teammates have local,
  not-yet-pushed work.

---

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

## Research workflow (models/evaluation)

```bash
pip install -r requirements-research.txt   # pandas, scikit-learn, lightgbm, jupyterlab, ...
python -m pumpradar.exp_a                  # prepares data/processed/sapA.parquet from the real Sapienza CSV
jupyter nbconvert --to notebook --execute --inplace notebooks/KD_pumpradar_complete.ipynb
```

`data/raw/sapienza/features_25S.csv` (the real Sapienza dataset, pulled via Git LFS
from `feat/data-events`) must exist first; `exp_a.load_raw_features()` raises a clear
error naming the missing file otherwise. `GET /universe` and `GET /honesty` (below)
read from `results/*.json`, which `python -m pumpradar.exp_a` and the sweep scripts
referenced in `paper/sections/results_kaashvi.md`'s claims ledger produce.

## Development

```bash
python -m pytest
python -m ruff check .
```

Set `PUMPRADAR_DB` to an SQLite file path if you want alerts outside the project directory. The default is `alerts.sqlite3` in the server's working directory. Scores and warmup history remain in memory; restarting the API clears those, while alert records stay in SQLite. Run one API worker because this slice has in-process state.

`GET /universe` (every live coin's real price, any quote, merged with this process's
BTC-pair scoring coverage) and `GET /honesty` (the real Experiment A leakage-audit
results) are additive endpoints alongside the original `/radar`, `/bars`, `/batches`,
`/alerts`, `/events`, `/replay`. `/universe` calls the public Binance API directly
(`data-api.binance.vision`, no key) and caches for 30 seconds; `/honesty` reads
`results/metrics_A_tuned.json`, `results/bootstrap_A_h10.json` and
`results/live_binance_universe_check.json` and returns 503 if they're missing rather
than fabricating a response.

### Next integration

- Replace `Radar.ingest`'s volume heuristic with the team's **one shared feature module** and trained hazard model. The feature and scoring path must remain identical in replay and live use.
- Add historical archive warmup and gap recovery, a 24-hour baseline, liquidity-tier thresholds and a tested false-alert budget. The current five-bar median and fixed 0.8 threshold are for wiring the platform only.
- Implement trade-based features, candlestick and risk-curve views, event selection and the full two-hour replay after research data contracts settle.
- Measure 5-second latency and 48-hour stability before claiming the build guide's platform acceptance criteria. Live Binance connectivity has not been exercised by the local unit tests.
