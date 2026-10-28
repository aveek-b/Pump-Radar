# B1 contract and pending handoff decisions

This is Aveek's provisional platform contract based on B1 of the supplied v2 guide.
Hannah and Kaashvi have **not** approved the shared live-model shape choices.
Kaashvi's committed Experiment A artifacts and price module are copied unchanged;
the live feature, frozen-model and threshold handoffs remain unavailable.

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
- In mock mode, `/markets` returns 60 scored BTC fixtures and one unscored USDT fixture.
  `change_24h_pct` is percentage points; `volume_24h_quote` and candle `volume_quote`
  use the stated quote asset. All mock values are synthetic. Outside mock mode,
  `/markets` reads public Binance exchange information and 24-hour tickers through
  Kaashvi's `LiveUniverseCache` (30-second TTL). It returns one preferred display
  quote per base coin, with the Binance fetch timestamp. Every `scored` value is
  false because the cross-sectional model is not loaded. A feed failure returns
  503; it never substitutes mock prices or demo scores.
- `/coin/{pair}` returns a scored fixture's market, risks, 360 synthetic minute
  candles, 360 score points, current-frame alerts and five synthetic drivers.
  Unknown/unscored pairs return 404. Candle and risk history cover six hours;
  historical synthetic risk points are illustrative, not a recorded tick history.
  The final risk point matches the current frame. Real explanations remain later work.
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
- `/research/experiment-a` reports Kaashvi's committed historical audit separately:
  random and honest average precision, inflation, prevalence, 10-minute
  bootstrap intervals and permutation importance from commit `a434e86`.
  The source artifacts are returned
  with the response. Its two measured figures are served under
  `/research/experiment-a/figures/{name}` with an explicit filename allowlist.
  The audit contains no calibrated risk, live precision/recall or alert budget;
  those `/honesty` fields remain null.

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
still delivers demo alerts. `/markets` returns live price snapshots when Binance
is reachable; `/replay/events` returns a labeled empty result. Coin detail returns
503, and replay detail returns 404 until integration.
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

The frontend now renders Radar/Markets, Coin and Replay against these fixtures.
Honesty displays missing live metrics alongside the measured historical Experiment A
table. Method shows the two measured Experiment A figures and describes the planned
cross-sectional protocol. Browser requests use a local `/api` proxy prefix.
Replay null lead values are displayed as unavailable, not inferred misses; aggregate
catch rate needs an explicit evaluation/miss convention agreed with the researchers.
The stream is shared across pages, suppresses snapshot notifications on reconnect,
and tracks only bounded session alert history. Badges still use the 10-minute level,
even when a different horizon determines sorting. The brief mock sparkline is labeled
"Recent trend", not a measured two-hour series.
