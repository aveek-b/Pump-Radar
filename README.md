# PumpRadar: Leakage-Honest Early Warning and Cross-Sectional Ranking for Cryptocurrency Pump-and-Dump Events

Team implementation of the **26 October 2026 compressed build guide (v2)**. The React dashboard includes synthetic preview mode, real Binance prices, and a frozen Experiment B live ranking model. The five-bar volume heuristic remains a separate demo. Live alert performance and a calibrated threshold have not been established.

## Run the real research ranking locally

Close any running project backend before syncing Python dependencies. In PowerShell:

```powershell
Set-Location 'D:\FME Project\pumpradar'
uv sync --locked --extra dev --extra model
Set-Location web
npm ci
```

Start the API in one terminal:

```powershell
Set-Location 'D:\FME Project\pumpradar'
$env:PUMPRADAR_MOCK = '0'
$env:PUMPRADAR_ALLOW_BACKFILL = '1'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, request recent closed 1-minute Binance bars to warm the model, then start the feeder:

```powershell
Set-Location 'D:\FME Project\pumpradar'
Invoke-RestMethod -Method Post 'http://127.0.0.1:8000/scores/backfill'
.\.venv\Scripts\python.exe -m pumpradar.live --all-btc
```

In a third terminal, run `Set-Location 'D:\FME Project\pumpradar\web'` and `npm run dev`, then open **http://127.0.0.1:5173/**. Check `/health` for `model_loaded: true` and `/scores/live` for `status: scored`. A pair needs sufficient real bar history and valid features before a score appears. Scores are raw linear SVM decision margins for ranking at 10 minutes; they are not probabilities. The committed alert threshold is provisional and its live false-alert rate is unvalidated. Backfill requires explicit `PUMPRADAR_ALLOW_BACKFILL=1`; restart the backend after changing environment variables.

## Start the dashboard on Windows (PowerShell)

These steps open the React dashboard with **synthetic preview data**.
Radar, All Markets, Coin, Replay, Honesty and Method are available. For real model ranking, follow the section above. No market-data download or live feeder is needed for this preview.

### 1. Check the prerequisites

Use PowerShell terminals in VS Code. Install Python and Node.js if they are not
already installed; the project uses Python **3.12** and Node **22.14.0**.
`uv` can install the required Python version for you. In a fresh terminal with
no virtual environment activated, check:

```powershell
python --version
node --version
npm --version
uv --version
```

If `uv` is not installed, install it using your system Python:

```powershell
python -m pip install uv==0.13.5
```

Reopen the terminal if needed so the installed `uv` command is on PATH. Use
**`uv run`**, not `python -m uv run`: the project's virtual environment does not
include the `uv` Python module. You do not need to activate `.venv` for these steps.

### 2. Install the project dependencies once

For this existing checkout, run:

```powershell
Set-Location 'D:\FME Project\pumpradar'
uv python install 3.12
uv sync --locked --extra dev
Set-Location web
npm ci
```

Run `uv sync --locked --extra dev` from the project root and `npm ci` from `web`
again after dependency files change. For a new clone, use the cloning instructions
below and substitute its path for `D:\FME Project\pumpradar`.

### 3. Terminal 1: start the backend in mock mode

```powershell
Set-Location 'D:\FME Project\pumpradar'
$env:PUMPRADAR_MOCK = '1'
uv run --locked --extra dev python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Leave this terminal running. Wait for `Application startup complete`. Set the
mock variable in this same terminal every time you start from a new terminal.
It enables the synthetic coins and replay example.

If dependencies are already synced, you can also start the backend directly:

```powershell
$env:PUMPRADAR_MOCK = '1'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### 4. Terminal 2: start the frontend

Open a **second PowerShell terminal**, then run:

```powershell
Set-Location 'D:\FME Project\pumpradar\web'
npm run dev
```

Leave this terminal running too. The frontend forwards `/api` requests to the
backend on port 8000; no `VITE_API_URL` setting is needed for this local setup.

### 5. Open and explore the dashboard

Open **http://127.0.0.1:5173/** in your browser. Use this exact address:
`localhost` can resolve to the IPv6 address `::1` and reach a different Vite
server if another instance is running on the same port.

- Radar shows 60 synthetic coins. Prices update about every 2 seconds and scores
  every 10 seconds. Use the horizon, search and tier controls or All Markets tab.
- Click a scored pair to open its Coin chart and synthetic drivers.
- Open Replay, choose the synthetic example, select **16×**, then click **Play**.
- Honesty shows the measured historical Experiment A leakage audit alongside
  unavailable live-model metrics; Method includes its two measured figures.
  These audit results do not evaluate the dashboard's mock scores.

The API docs are at http://127.0.0.1:8000/docs. Port **8000** serves the backend
and older static demo; port **5173** is the new React dashboard.

To check the backend in another terminal:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health'
```

For this preview, expect `status: ok`, `mock: True`, and `scorer: mock`.
Mock mode hides model ranking even if the model extra is installed.

Press **Ctrl+C in both server terminals** to stop. On later visits, repeat only
steps 3–5 unless dependencies changed.

### Startup troubleshooting

| Symptom | What to do |
| --- | --- |
| `No module named uv` | Use `uv run ...` instead of `python -m uv run ...`, or use the direct `.\.venv\Scripts\python.exe` startup command above after syncing. |
| Access denied removing `.venv\Scripts` | Stop this project's servers/debugger, close terminals using its environment, and reopen PowerShell without activating it. Run `uv sync --locked --extra dev` from the root. The project pins Python 3.12; an old 3.13 environment prompts `uv` to replace it. If still locked, restart VS Code before retrying. |
| No coins, or `mock: False` | Stop the backend, set `$env:PUMPRADAR_MOCK = '1'` in its terminal, then restart it. |
| API unavailable or feed reconnecting | Keep Terminal 1 running on port 8000; check `/health` and its terminal output. |
| `Reconnecting` and no data, although both terminals are open | Open `http://127.0.0.1:8000/health`. If it hangs or does not show `status: ok`, stop the backend with Ctrl+C and restart it using the command in step 3. Then refresh `http://127.0.0.1:5173/`. The frontend can stay open while the backend restarts. |
| Port 8000 or 5173 is already in use | Stop the previous instance with Ctrl+C in its terminal, then rerun the corresponding startup command. |
| `npm.ps1` cannot run because scripts are disabled | Use `npm.cmd ci` and `npm.cmd run dev` in PowerShell. |

## Clone and set up another checkout

Clone the shared repository once. The folder containing this README, `api/`,
`web/` and `pyproject.toml` is the only project root:

```bash
git clone https://github.com/aveek-b/Pump-Radar.git
cd Pump-Radar
python -m pip install uv==0.13.5
uv sync --locked --extra dev
cd web
npm ci
cd ..
```

Use Python 3.12 (selected by `.python-version`; uv can provision it) and Node
22.14.0 (`.nvmrc`). Install Node before running npm. `uv.lock` and
`web/package-lock.json` pin the platform dependencies used by CI. Run these
commands after pulling dependency changes; do not share `.venv` or `node_modules`.

The broader `requirements.txt` is an optional research setup with unpinned ML
packages. It is not required for the platform or CI; research dependencies and
artifacts still need agreement with their owners.

Run the backend and frontend in separate terminals:

```bash
uv run --locked --extra dev python -m uvicorn api.main:app --reload
```

```bash
cd web
npm run dev
```

Open `http://127.0.0.1:5173/` for React and `http://127.0.0.1:8000/docs` for the
API. Start both terminals from the project root. In this original local checkout,
that is `D:\FME Project\pumpradar`, with no second nested `pumpradar` directory.

## B1 mock preview

B1 now provides a typed API contract, deterministic mock mode and a minimal
streaming React radar. From this directory, start the mock backend in PowerShell:

```powershell
$env:PUMPRADAR_MOCK = '1'
uv run --locked --extra dev python -m uvicorn api.main:app --reload
```

In a second terminal, run `cd web` then `npm run dev`. Open `http://127.0.0.1:5173/`
to see 60 labeled synthetic coins, prices about every 2 seconds and scoring ticks
every 10 seconds. The fixture timestamps are synthetic, not market time.
Use `curl.exe -N http://127.0.0.1:8000/stream` to inspect SSE directly.
Set `PUMPRADAR_MOCK=0` and restart for the retained manual/live-feeder demo.

The B1 endpoints are `/markets`, `/radar`, `/coin/{pair}`, `/alerts`, `/stream`,
`/replay/events`, `/replay/{event_id}`, `/honesty`, and `/health`.
[Contract notes](api/CONTRACT.md) record provisional handoff choices and non-mock
behavior. Synthetic replay is not held-out evidence; evaluation metrics remain
null. The platform now includes Radar/Markets filters, Coin charts, Replay playback,
Honesty availability states and a Method explanation. All these views keep synthetic
data and missing evaluation results explicit.

## Platform screens

- Radar: horizon, search, tier and sort controls are stored in the URL. All Markets
  includes unscored pairs. One shared SSE connection updates prices across pages;
  new alerts produce deduplicated toasts and opt-in browser notifications.
- Coin: six hours of synthetic candles and risk history, alert markers and five
  explicitly synthetic drivers. TradingView Lightweight Charts provides zoom/pan.
- Replay: event list, 1x/4x/16x playback, scrubber, onset marker and per-frame ranks.
  Playback reveals only data through the cursor. The current example is synthetic;
  first-alert lead, rank-at-onset and catch-rate results remain unavailable.
- Honesty and Method: live metrics stay unavailable; both pages display Kaashvi's
  measured historical Experiments A and B with source provenance. Method also shows
  Experiment A figures. The live model provides raw ranking margins; there is no final paper link.
- Responsive layout, light-theme toggle, keyboard focus and feed-down status are
  included. Alert counts describe this browser session only, not measured error rates.

The local frontend sends requests through `/api`, which Vite proxies to port 8000.
This keeps API paths separate from browser routes such as `/replay`. In a separately
hosted frontend, set `VITE_API_URL` to the backend origin **at build time**, configure
backend CORS for that origin, and preserve SPA fallbacks (`web/public/_redirects`).
Public hosting and production CORS configuration are still pending.

With `PUMPRADAR_MOCK=0`, All Markets requests public Binance prices. Kaashvi's
`LiveUniverseCache` refreshes the snapshot at most once every 30 seconds; this is
separate from the 2-second synthetic stream. Real markets are marked scored when
their BTC pairs have sufficient model-ready minute bars. If Binance is unreachable, the
page shows an explicit feed error. Radar also shows a **price-only watch** of the
largest USDT markets by 24-hour USDT volume; it is not
a pump-risk ranking. Honesty shows the count and timestamp of public priced markets
separately from its still-unavailable model precision and alert-budget metrics.
The retained demo heuristic appears only when manually ingested bars or the old
feeder supplies them.

Click a live market to view public Binance candlesticks on its Coin page. The
range selector offers week (hourly), month (4-hour), and year (daily) history.
These charts contain prices only; they do not imply a model score or alert.
The Honesty and Method pages also show held-out Experiment B research AP and
Hit@5 from `origin/main` commit `389fe61`, separate from the unavailable live
model metrics. The frozen research candidate provides local rankings, with an unvalidated live alert budget.

To check a real-price session, restart the backend with `$env:PUMPRADAR_MOCK = '0'`
and open `http://127.0.0.1:8000/markets`. Its `markets` list should contain
real pairs with `mock: false`. A 503 means the backend cannot
reach Binance; check network access from the backend machine. If `/markets` has
pairs but the browser does not, check that the frontend is running on port 5173,
then open `http://127.0.0.1:5173/api/markets` to verify the Vite proxy.

Browser checks run against their own mock backend on port 8765 and frontend on 5174:

```bash
cd web
npx playwright install chromium
npm run test:e2e
```

The checks cover filters, Coin navigation, replay completion, direct links, 375px
layouts, unscored markets and duplicate SSE alerts. They are local mock checks,
not live-feed or public-deployment acceptance tests.

## Integrated branch status (29 October 2026)

This branch contains the latest fetched `origin/main` through `c13d187` and Hannah's `feat/feature-engineering` branch. Main supplies historical Experiments A and B, a frozen Experiment B linear SVM, a provisional threshold, price-only historical replay, and the minute-bar feature contract. Hannah's newer cross-sectional builder is retained as `features_v2.py` and `build_xsec.py`; its feature names differ from the frozen model's and it is not substituted into live inference.

The model ranks real BTC-pair minute bars after backfill or feeder history. `/scores/live` reports raw decision margins and coverage; `/honesty` keeps live precision, recall, warning lead and false-alert rate unavailable until measured. Price-only replay does not provide evaluated model alert frames. The threshold's live alert budget is unvalidated. Public deployment, final paper, and demonstration materials still require team work.

`data/raw/` and `data/processed/` remain excluded from Git. Do not commit raw archives, Parquet, or SQLite state. The small frozen model artifact is already tracked in upstream main. After API contract changes, regenerate `api/openapi.json` and `web/src/api/types.ts` with `python -m api.export_openapi` and `cd web; npm run typegen`.

## Existing demo, retained for integration

- `src/pumpradar/engine.py` scores a coin after five earlier closed bars using relative BTC volume and taker-buy share. A score of zero is common and is **not** a 0% pump probability.
- `src/pumpradar/api.py` implements `/bars`, `/batches`, `/radar`, `/alerts`, `/events`, `/replay` and `/health`; `api/main.py` is the guide-compatible entry point. The small static dashboard at port 8000 remains available while React is built.
- `src/pumpradar/live.py` is the earlier public Binance **WebSocket kline** feeder. Run `python -m pumpradar.live --symbols ETHBTC,BNBBTC` for a small demo or `--all-btc --verify-minutes 3` for strict minute coverage. The compressed guide assigns Hannah a **REST polling** ingestor in `api/engine/ingest.py`; do not treat the demo feeder as that deliverable.
- SQLite alert records persist in `alerts.sqlite3` (or `PUMPRADAR_DB`); scores and bar history remain in one process's memory. Replay receives bars in the request and stays separate from live state until `replay/index.json` and event files arrive.

The fixed demo threshold of 0.8 has no measured false-alert guarantee. The live Experiment B scorer loads the committed frozen model, ordered features and provisional threshold. Do not label either score a calibrated probability or a measured live alert result.

## Collaboration and deployment

The remote is `https://github.com/aveek-b/Pump-Radar`. Each teammate starts a
work block from updated `main`, then creates a branch for one task:

```bash
git switch main
git pull --ff-only
git switch -c feat/your-task
```

Before opening a PR, run from the root:

```bash
uv run --locked --extra dev python -m pytest -q
uv run --locked --extra dev python -m ruff check .
uv run --locked --extra dev python -m api.export_openapi
cd web
npm run typegen
npm run build
cd ..
git diff --check
```

Commit regenerated `api/openapi.json` and `web/src/api/types.ts` with API changes.
CI runs the locked platform setup on Linux and Windows, verifies generated files
are current, and builds the frontend. CI results on GitHub are pending the push.
Review changes with the consuming teammate before merging shared interfaces.
Keep research artifacts outside Git; record their filenames and schemas in the
handoff docs. Keep mock data labeled and measured claims tied to result artifacts.

`.github/CODEOWNERS` remains commented until the team's GitHub handles are verified.
Repository administrators should enable PR review and passing CI requirements on
`main`; local files cannot enable those settings. `deploy/` contains local starters;
public HTTPS, frontend hosting and real-model deployment remain to be done.

Before publishing, record the data licence and limitations, demonstrate a held-out replay, and compare measured alert rate to the paper's stated budget. Research tool. Not financial advice. No trades are placed.
