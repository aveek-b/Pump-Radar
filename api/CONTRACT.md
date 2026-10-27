# B1 contract and pending handoff decisions

This is Aveek's provisional platform contract based on B1 of the supplied v2 guide.
Hannah and Kaashvi have **not** approved these shape choices. Their research files,
features, frozen models and threshold files are unchanged.

## Response conventions

- `/radar` retains `scorer`, `minute`, and `coins`. B1 uses `rows: CoinRisk[]`;
  mock mode leaves legacy `coins` empty. Demo mode leaves `rows` empty and returns
  the original heuristic scores in `coins`.
- Mock responses carry `mock: true`, `scorer: "mock"`, and a notice. Model provenance
  is null. Fake pairs start with `MOCK`; none represents a listed market.
- Risk keys are strings `1`, `3`, `5`, `10`, `30`, `60` (minutes), with values in
  [0, 1]. Including 3 minutes reconciles research horizons with the shorter F2 tab
  list. Mock values have no probability interpretation.
- UTC timestamps are ISO 8601. The synthetic clock starts at 2026-10-26 00:00 UTC
  and advances with process uptime. Seed 42 plus sequence makes frames repeatable
  across restarts. REST and SSE share the clock. Price and score sequences are
  separate (2-second and 10-second steps).
- `/markets` returns 60 scored BTC fixtures and one unscored USDT fixture.
  `change_24h_pct` is percentage points; `volume_24h_quote` and candle `volume_quote`
  use the stated quote asset. All values are synthetic.
- `/coin/{pair}` returns a scored fixture's market, risks, 120 synthetic minute
  candles, up to 12 score points, current-frame alerts and five synthetic drivers.
  Unknown/unscored pairs return 404. Six-hour charts and real explanations are later work.
- Mock tiers cycle through low/medium/high. Mock levels use 10-minute risk and
  illustrative cutoffs 0.4 (Watch) and 0.8 (Alert), **not** Kaashvi's thresholds.
  One rotating synthetic alert per tick exercises transport; B3 entry detection
  and the 30-minute cooldown are not implemented here.
- `/alerts` returns current-frame mock alerts with stable IDs
  `mock-{sequence}-{pair}`. Demo mode retains SQLite history and the original
  record format. OpenAPI declares the union explicitly.
- `/replay/events` exposes only `mock-example` in mock mode, with `era: "mock"`.
  Its detail has 12 synthetic ten-second frames; lead and onset rank are null.
  This transport example is not a held-out pump replay.
- `/honesty` reports unavailable metrics as null. `/health` separates process
  availability from `model_loaded: false` and market-feed state.

## Stream protocol and lifecycle

`GET /stream` uses `text/event-stream` and named `prices` and `tick` events.
Payloads are `PricesEvent` and `RadarTick` in OpenAPI and generated TypeScript;
the response's `x-event-schemas` links them.

Connections receive a comment and current price/score snapshots. Prices follow
about every 2 seconds and scores every 10 seconds. `tick.rows` replaces ranking;
`tick.newAlerts` contains fixture alerts. Deduplicate alerts by stable IDs.
Reconnect sends current snapshots, not a backlog; Last-Event-ID is unsupported.
Slow clients skip old frames. Each response pulls shared-clock snapshots with
bounded memory, without queues or producer tasks. Cancellation propagates through
the sleep; the browser closes EventSource on unmount.

Without mock mode, `/stream` sends explanatory keepalive comments only; `/events`
still delivers demo alerts. `/markets` and `/replay/events` return labeled empty
results, coin detail returns 503, and replay detail returns 404 until integration.
No synthetic market/model data silently appears in non-mock mode.

`POST /bars`, `POST /batches`, `POST /replay`, the static dashboard and `/events`
retain demo behavior. Mock reads never ingest bars or persist mock alerts.
Use mock mode for React and non-mock for the legacy static dashboard. Set the
environment before starting the server.

## Decisions for Hannah and Kaashvi

Confirm the `rows` envelope, six horizons, quote units, tier names, threshold/model
provenance representation and final alert-history format before engine integration.
Confirm replay timestamps, frame resolution, index metadata, metric denominators
and artifact formats before B4/F4/F5. These types propose an adapter boundary;
they do not change Section 3.2 Parquet/model/replay handoffs or imply artifacts exist.

Next Aveek milestone: F2 Radar/Markets UI with two tabs, horizon/search/tier
controls, prices, ranking and alert feedback, still clearly labeled in mock mode.
