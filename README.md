# PumpRadar

## Project status (as of 2026-10-29, commit `95cf346`)

Three deliverables: a deployed web platform, an executed research notebook, and a
research-style report. This section summarizes what's real and working right now,
what's missing, and where the risk is. Everything below is verifiable by running
`python -m pytest` and the commands in this file -- nothing here is aspirational.

### What's done

**Experiment A (leakage audit) -- complete.** Six models compared under a random-split
audit baseline (P0) vs. an honest, event-grouped, chronologically embargoed split (P2),
across six horizons and two feature sets, on the real SystemsLab-Sapienza dataset
(482,157 rows, 317 confirmed pump events, 85 coins, 2018-2021). Finding: clean
(volume/trade) features show no leakage-driven inflation; full features (adds
price-level + time-of-day) show a real, protocol-driven inflation gap that permutation
importance traces to **time-of-day encoding**, not price level as first hypothesized --
whether that's genuine pump-timing behavior or a small-sample artifact is unresolved.
Hyperparameters verified with a true joint grid search. **Has no live deployment path
and never will** -- its features are 25-second resolution with an undocumented
formula; live Binance data is 1-minute resolution with a known, different formula.
Full writeup: `paper/sections/results_kaashvi.md`. Notebook:
`notebooks/KD_pumpradar_complete.ipynb` (0 errors, restart-and-run-all verified).

**Data pipeline (`features.py`, `xsec.parquet`) -- complete and merged.** Real
`pump_telegram.csv`, `prepare_events.py` and `detect_onsets.py` re-run against a
real ~42,500-file Binance kline archive, reproducing the exact published onset counts
(127 confirmed / 187 fallback / 4 missing) before anything new was built on top.
`features.py` (robust z-scores, market-relative percentile ranks, quiet accumulation,
per the build guide's D4 formula) is the one shared feature implementation for both
research and the live platform, with the guide's required no-lookahead regression
test. Real `xsec.parquet`: 1,063,320 rows, 127 confirmed events. A known data-quality
issue (extreme z-scores for ~0.9% of rows, illiquid-coin baselines) is documented in
`data/processed/data_summary.json`, not hidden.

**Experiment B (cross-sectional "which coin, how early" scoring) -- complete,
deployed, and live.** Honest train-era/test-era split (pre-2020/2020+), zero
`(pair, minute)` leakage verified empirically. Real result: Random Forest leads on
raw test AP and Hit@1/Hit@5 (5-12x random chance across ~84 live coins), but the
proper **validation-AP-based** selection (never test, per the guide's rule) picks
**Linear SVM** instead -- the two rankings disagree, reported as-is rather than
reconciled. The selected model is frozen (`models/model_B.joblib`, trained on all 127
confirmed events now that selection is final) with a real, honestly-labeled
**PROVISIONAL** alert threshold (`models/threshold_B.json`, computed from
validation-era scores, not real background data -- live false-alert rate is
unvalidated per the guide's K11 requirement).

**Live scoring -- real, wired, and verified end to end.** `live_scoring.py`'s
cross-sectional engine tracks rolling history for the whole live BTC-pair universe
(Experiment B's features are percentile ranks relative to every other live coin at
the same minute, so no coin can be scored alone), computes real features once per
minute, scores with the frozen model, and fires cooldown-gated alerts. Wired into the
existing `/batches` endpoint (same feeder already in `live.py`, no second process).
Verified live: backfilled real history for all 38 live BTC pairs, all 38 scored with
real differentiated values, confirmed scores update continuously as real minutes
close. New endpoints: `GET /scores/live`, `POST /scores/backfill`.

**Platform.** `GET /universe`: every coin currently on live Binance (520 as of this
writing), deduplicated across quote pairs, real price + 24h change; only the 38 coins
with a live BTC pair can ever get a real score, the rest are honestly `unavailable`,
never guessed. `GET /coin/{symbol}/candles`: real OHLCV history (week/month/year) +
SMA-20/50, via TradingView's lightweight-charts (no build toolchain needed). `GET
/replay/events` + `/replay/{event_id}`: real historical pump replay with a real onset
marker, extracted from the downloaded archive (`data/replay/`, committed directly --
small and essential, like `model_B.joblib`). `GET /honesty`: both experiments' real
results, the live deployment status, and the provisional-threshold caveat, all in one
place. Dashboard has five tabs: Radar (original demo heuristic, clearly labeled),
**Live Universe** (real B-model scores, alert highlighting, toast notifications),
Coin view, **Past Events** (replay), **Honesty & Method**. Extends the existing plain
HTML/CSS/JS dashboard rather than a new React/Vite/Tailwind toolchain -- that stack
was planned but never scaffolded, and starting it now without the ability to actually
build/deploy it here would risk looking finished without being verified.

Several real bugs were caught this way -- by actually running the server against live
data, not just passing mocked tests -- and fixed: a coin with both a BTC and USDT pair
was wrongly marked `unavailable`; a replay-index-writing bug let the test suite
silently overwrite real data with a test fixture; a `row`/`snapshot` index mismatch in
Hit@k scoring.

### What's not done / blocked

- **No calibration.** Experiment B's live score is a ranking value (decision_function),
  not a probability, and the alert threshold is provisional (validation-era, not real
  background data) -- both need a disjoint calibration slice and ordinary-period
  background market data that don't exist yet.
- **Only 38 of 520 live coins can ever get a real score.** Reaching more requires
  training on an expanded quote-asset universe -- the build guide calls this
  "additional work, not a UI setting"; not scoped.
- **No live/production deployment.** Everything above runs and is verified locally;
  there is no public URL, VM, or hosting account set up from this session.
- No paper skeleton exists yet beyond the Results section; Introduction, Related Work,
  Data, Method, System, Discussion, Abstract, Conclusion are all still unwritten.
- This status reflects the **shared git repo** as of commit `95cf346` (2026-10-29). It
  may understate real progress if teammates have local, not-yet-pushed work.

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

Endpoints beyond the original skeleton's `/radar`, `/bars`, `/batches`, `/alerts`,
`/events`:

| Endpoint | Real data source |
|---|---|
| `GET /universe` | Live Binance prices for every live coin (`data-api.binance.vision`, no key), cached 30s |
| `GET /coin/{symbol}/candles?range=week\|month\|year` | Real OHLCV history + SMA-20/50 |
| `GET /replay/events`, `GET /replay/{event_id}` | `data/replay/*.json`, extracted from the real downloaded archive |
| `GET /scores/live` | `live_scoring.CrossSectionalScoringEngine`, Experiment B's frozen model scored against real ingested bars |
| `POST /scores/backfill` | Real historical backfill for the live BTC-pair universe (operator-triggered, never automatic -- so tests never hit the network) |
| `GET /honesty` | `results/*.json` (both experiments) + live deployment status; 503s rather than fabricating a response if a results file is missing |

To actually see live scores and alerts: start the API, `POST /scores/backfill` once,
then run the real feeder (`python -m pumpradar.live --all-btc`) in a second terminal
to keep `/scores/live` updating as real minutes close.

### What's left on the platform side

- Calibration + a real (non-provisional) alert threshold, once ordinary-period
  background market data exists.
- Scoring beyond the 38 live BTC pairs needs an expanded-quote-universe model --
  unscoped, not a UI change.
- Production deployment (public URL / hosting) -- everything currently runs locally.

## D3: Market Onset Detection — Limitations

The onset detection pipeline processed 318 events using the original threshold method.

- **127 events (`ok`):** A spike was detected using the robust threshold based on the previous 24 hours, excluding the most recent hour.
- **187 events (`zero_iqr`):** The baseline interquartile range (IQR) was zero, so the primary threshold could not be calculated. The onset timestamp falls back to the Telegram timestamp; this is not a confirmed market onset.
- **4 events (`no_data`):** Required market data was unavailable, so the onset could not be reliably determined.
- **0 events (`no_spike`):** No events received this flag. This does not mean all 318 events had a detected spike; zero-IQR and missing-data cases are reported separately.

An alternative onset estimate is available for 310 events. Treat it as a sensitivity analysis, not as a replacement for the primary method without further validation.

The onset histogram includes fallback timestamps for events without a confirmed primary onset. Interpret it with this limitation in mind.

These results describe the current dataset and may change if the input data or detection method changes.
