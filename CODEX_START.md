# Start here: Aveek's next PumpRadar task

The 26 October compressed build guide is in `docs/build-guide-v2.pdf`. The code is a scaffold plus an earlier functioning demo. Do not assume that the guide's B1/F1–F7 deliverables are complete just because their directories exist.

## Current state

- The repository is consolidated: `api/`, `web/`, `src/`, and this file share the Git root. There is no second nested project. `api/main.py` exposes the retained demo plus the B1 contract in `api/schemas.py`.
- The demo handles manual closed bars, batches, replay input, radar, alerts, an event stream, and a health check. `src/pumpradar/live.py` is a Binance WebSocket demo feeder with minute coverage reporting.
- `web/` now includes Radar/Markets with URL filters, Coin charts, Replay playback,
  Honesty availability states and a planned-Method page. Mock data remains labeled.
- `api/engine/ingest.py`, `score.py`, and `prices.py` reserve Hannah's engine work;
  research features and frozen models have not been integrated. Kaashvi's separate
  `src/pumpradar/prices.py` supports unscored live market prices, and Experiment A
  audit artifacts are displayed separately from live-model metrics. Deployment files
  are local starters, not public deployment.
- B1 was implemented with 21 Python tests, generated OpenAPI/TypeScript, lint and a frontend build. Re-run checks after changes. `api/CONTRACT.md` documents provisional choices pending Hannah and Kaashvi's review.

## Completed first task: B1

The following was the B1 scope and remains its acceptance checklist. Read guide section B1 and the current `api/schemas.py`, `src/pumpradar/api.py`, `web/src/api/client.ts`, and tests before changing it.

1. Define response models and routes for `/markets`, `/radar`, `/coin/{pair}`, `/alerts`, `/stream`, `/replay/events`, `/replay/{event_id}`, `/honesty`, and `/health`. Agree on or document any unresolved shape choices with Hannah and Kaashvi before changing shared handoff fields. Preserve the current demo endpoints where practical.
2. Add `PUMPRADAR_MOCK=1` with repeatable sample coins and risk values that are visibly labeled mock data. Make `/stream` produce SSE price events and mock scoring ticks on the guide's cadence (prices about 2 s; mock scoring ticks 10 s). Ensure cancellation and disconnected clients do not leak tasks.
3. Generate `api/openapi.json` and `web/src/api/types.ts` from the backend contract. Wire a small browser view to the new mock radar and stream so the contract can be inspected end to end; leave empirical performance, real model, and held-out replay claims absent until teammate artifacts arrive.
4. Add focused endpoint/stream checks, run Python tests and lint, and run the frontend build. Show the exact commands and outcomes. Report remaining decisions and a suggested next Aveek milestone (Radar/Markets UI).

## Platform screens implemented; next milestone: real artifact integration

Radar/Markets controls, alert feedback, six-hour Coin charts and Replay playback
are implemented against B1 fixtures. Browser tests live in `web/tests/`; run
`cd web && npm run test:e2e` after installing Playwright Chromium. Local API requests
use `/api` to avoid collisions with browser routes such as `/replay`.

The updated data branch is merged into `origin/main` and now includes shared
`features.py` alongside event preparation, archive downloads/validation and onset
detection. This platform branch has not merged the updated main; its real engine,
frozen model and held-out replay files are still unavailable locally.
Preserve its documented zero-IQR/missing-data onset limitations when integrating.

Kaashvi's fetched branch at `a434e86` provides an Experiment A audit, committed
results/figures and a live price-universe module. The platform now displays these
in a separate historical audit and unscored All Markets feed. It does not supply
Experiment B, frozen model/threshold/features, or held-out replay files.

Agree the pending contract choices before real-engine integration, including
model-ready provenance, evaluated Honesty status and the distinction between a
missing replay metric and a measured miss. Complete the evaluated scoreboard,
research figures and final paper link only after those artifacts exist. Public
deployment, accessibility audit, motion/table polish and the demo video remain.
Use the locked checks in README; regenerate API artifacts together when shapes change.

Do not invent Hannah's feature calculation or Kaashvi's thresholds, deploy publicly, create another GitHub repository, or imply the mock risk is a trained prediction. Inspect and preserve existing local changes before editing.
