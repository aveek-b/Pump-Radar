# PumpRadar

Team scaffold for the **26 October 2026 compressed build guide (v2)**. It keeps the earlier working API demo while giving Kaashvi, Hannah and Aveek separate folders for the three-day research and platform work. The guide's React + FastAPI product is still in progress; the current five-bar volume heuristic is a wiring test, not the evaluated model.

## Set up

Clone the shared repository once. The folder containing this README, `api/`,
`web/` and `pyproject.toml` is the only project root:

```bash
git clone https://github.com/aveek-b/Pump-Radar.git
cd Pump-Radar
python -m pip install uv==0.13.5
python -m uv sync --locked --extra dev
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
python -m uv run --locked --extra dev python -m uvicorn api.main:app --reload
```

```bash
cd web
npm run dev
```

Open `http://localhost:5173/` for React and `http://127.0.0.1:8000/docs` for the
API. Start both terminals from the project root. In this original local checkout,
that is `D:\FME Project\pumpradar`, with no second nested `pumpradar` directory.

## B1 mock preview

B1 now provides a typed API contract, deterministic mock mode and a minimal
streaming React radar. From this directory, start the mock backend in PowerShell:

```powershell
$env:PUMPRADAR_MOCK = '1'
python -m uv run --locked --extra dev python -m uvicorn api.main:app --reload
```

In a second terminal, run `cd web` then `npm run dev`. Open `http://localhost:5173/`
to see 60 labeled synthetic coins, prices about every 2 seconds and scoring ticks
every 10 seconds. The fixture timestamps are synthetic, not market time.
Use `curl.exe -N http://127.0.0.1:8000/stream` to inspect SSE directly.
Set `PUMPRADAR_MOCK=0` and restart for the retained manual/live-feeder demo.

The B1 endpoints are `/markets`, `/radar`, `/coin/{pair}`, `/alerts`, `/stream`,
`/replay/events`, `/replay/{event_id}`, `/honesty`, and `/health`.
[Contract notes](api/CONTRACT.md) record provisional handoff choices and non-mock
behavior. Synthetic replay is not held-out evidence; evaluation metrics remain
null. Coin, Replay, Honesty and Method browser pages remain placeholders.
Next Aveek milestone: F2 Radar/Markets UI.

## Ownership and file handoffs

| Owner | Paths | Next handoff |
| --- | --- | --- |
| Hannah | `src/pumpradar/events.py`, `download.py`, `features.py`; `api/engine/` | Event table, archive bars, shared `compute_features`, REST ingestor and real scorer |
| Kaashvi | `src/pumpradar/splits.py`, `metrics.py`, `exp_a.py`, `exp_b.py`; `models/`, `results/` | Grouped evaluation, model dictionary, threshold and ordered features |
| Aveek | `api/main.py`, `api/schemas.py`, `api/routes/`, `web/`, `deploy/` | Final API contract, frontend routes and deployment |

`data/raw/` and `data/processed/` are excluded from Git. `replay/` awaits Hannah's held-out JSON files; `paper/` and `notebooks/` are ready for team work. Do not commit raw archives, Parquet, SQLite state or frozen model binaries.

The Pydantic shapes are in `api/schemas.py`; `api/main.py` exposes both B1 and the retained demo. After contract changes, run `python -m api.export_openapi` and `cd web && npm run typegen` to refresh `api/openapi.json` and `web/src/api/types.ts`. Confirm the provisional choices in `api/CONTRACT.md` with Hannah and Kaashvi before real-engine integration. The React Radar consumes both the mock REST/SSE contract and the original demo ranking.

## Existing demo, retained for integration

- `src/pumpradar/engine.py` scores a coin after five earlier closed bars using relative BTC volume and taker-buy share. A score of zero is common and is **not** a 0% pump probability.
- `src/pumpradar/api.py` implements `/bars`, `/batches`, `/radar`, `/alerts`, `/events`, `/replay` and `/health`; `api/main.py` is the guide-compatible entry point. The small static dashboard at port 8000 remains available while React is built.
- `src/pumpradar/live.py` is the earlier public Binance **WebSocket kline** feeder. Run `python -m pumpradar.live --symbols ETHBTC,BNBBTC` for a small demo or `--all-btc --verify-minutes 3` for strict minute coverage. The compressed guide assigns Hannah a **REST polling** ingestor in `api/engine/ingest.py`; do not treat the demo feeder as that deliverable.
- SQLite alert records persist in `alerts.sqlite3` (or `PUMPRADAR_DB`); scores and bar history remain in one process's memory. Replay receives bars in the request and stays separate from live state until `replay/index.json` and event files arrive.

The fixed demo threshold of 0.8 has no measured false-alert guarantee. Do not label any current score a calibrated probability or paper result. The final scorer must call the same `pumpradar.features.compute_features` function used offline, load Kaashvi's frozen model and threshold, and report model provenance.

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
python -m uv run --locked --extra dev python -m pytest -q
python -m uv run --locked --extra dev python -m ruff check .
python -m uv run --locked --extra dev python -m api.export_openapi
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
