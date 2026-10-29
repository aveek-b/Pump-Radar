# API contract and measurement boundaries

`api/schemas.py` defines response shapes. After changing routes or schemas, run
`python -m api.export_openapi`, then `cd web` and `npm run typegen`. Commit both
`api/openapi.json` and `web/src/api/types.ts`.

## Modes

- `PUMPRADAR_MOCK=1`: deterministic synthetic prices, risk fields, alerts and replay. Fake pairs start with `MOCK`. Values are examples, not model predictions.
- `PUMPRADAR_MOCK=0`: `/markets` returns real public Binance prices. `/coin/{pair}` returns real candles. A Binance failure returns 503; mock data is never substituted.
- The retained `/radar`, `/alerts`, `/bars`, `/batches`, `/events` and `/replay` demo routes keep their five-bar heuristic separate from Experiment B. Its score has no probability or measured false-alert interpretation.

## Live Experiment B ranking

`/scores/live` returns raw 10-minute linear SVM decision margins from the frozen `models/model_B.joblib` bundle and the ordered columns in `models/features_B.json`. Larger margins rank higher; they are not probabilities. The response reports status, score type, model version, threshold, tracked pair count, and per-pair score, timestamp, scoring status and provisional alert. No score is shown until the BTC pair has sufficient real closed-minute history.

`/markets` and real `/coin/{pair}` expose the same margin as optional `model_score`; `scored` is true only when a score exists. A displayed USDT market maps to its BTC pair for scoring.

`POST /scores/backfill` loads recent Binance minute bars only when `PUMPRADAR_ALLOW_BACKFILL=1` and mock mode is off. Backfill is operator-triggered and not part of startup. The standalone `pumpradar.live --all-btc` feeder posts subsequent closed-minute batches. Both paths populate one in-memory model engine. Restarting the API clears its history; only one API process should own that state. The threshold in `models/threshold_B.json` is provisional and its live false-alert rate is unvalidated.

## Research, replay and stream

`/research/experiment-a` and `/research/experiment-b` report committed historical measurements and provenance. Average precision and Hit@5 do not describe live alert precision or recall. `/honesty` leaves live precision, recall, warning lead, Hit@5 and alert budget unavailable until measured.

Real `/replay/events` and `/replay/{event_id}` expose historical test-era prices and onset markers. They contain no evaluated per-minute model scores or alert lead measurements.

The mock `/stream` emits synthetic `prices` and `tick` SSE events about every 2 and 10 seconds respectively. Outside mock mode it emits explanatory keepalives; real model ranking is polled from `/scores/live`. `/health` distinguishes model load status from process availability.
