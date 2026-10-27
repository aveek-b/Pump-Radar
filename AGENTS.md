# PumpRadar repository guidance

Read `README.md`, `CODEX_START.md`, and `docs/build-guide-v2.pdf` before changing the platform contract. The PDF is the team's compressed 26 October 2026 plan; this repository is the current implementation, so inspect code and tests before editing.

Aveek owns `api/` routes and schemas, `web/`, `deploy/`, CI, and the platform README. Hannah owns `src/pumpradar/events.py`, `download.py`, `features.py`, and `api/engine/`; Kaashvi owns `splits.py`, `metrics.py`, `exp_a.py`, `exp_b.py`, `models/`, and `results/`. Coordinate interface changes through `api/schemas.py` and generated `web/src/api/types.ts`. Do not silently implement another person's research deliverables or fabricate measured results.

The existing `pumpradar.api` and `pumpradar.live` form a working demo with a five-earlier-bar volume heuristic. A score of 0 is common and is not a calibrated probability. Keep demo values and mock values plainly labeled. The compressed guide calls for a REST polling ingestor owned by Hannah; the retained WebSocket feeder is a demo path.

After API contract edits, run `python -m api.export_openapi` and `cd web && npm run typegen`. Verify Python with `python -m pytest -q` and `python -m ruff check .`; verify the frontend with `cd web && npm run build`. On Windows Git Bash use `./.venv/Scripts/python.exe` in place of `python`. Preserve the existing manual bars/replay behavior while developing the new contract. Do not commit raw market data, local SQLite state, virtual environments, or model binaries.

Work toward the user's requested task, report what was actually tested, and flag any contract decision that requires teammate agreement. No trading or order placement is in scope.
