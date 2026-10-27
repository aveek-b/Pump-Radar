# Scoring handoff

Hannah owns `ingest.py`, `score.py` and `prices.py`. These files are placeholders for the compressed guide's B2–B3 work. The existing working demo lives in `src/pumpradar/live.py` and `src/pumpradar/engine.py`; it uses WebSocket klines and a five-bar heuristic, so it must not be presented as the research model. Import `pumpradar.features.compute_features` in the final scorer and keep the same feature calculation for offline evaluation and live use.
