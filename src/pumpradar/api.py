"""Single-process scoring API. Live feeder and replay share Radar.ingest."""

import asyncio
import json
import os
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse

from api.mock import NOTICE, mock_data
from api.routes.platform import mock_enabled, register_platform
from api.schemas import (
    AlertsResponse,
    BarInput,
    BatchInput,
    BatchResponse,
    DemoScore,
    HealthResponse,
    RadarResponse,
    ReplayInput,
    ReplayResponse,
)
from pumpradar.engine import Bar, Radar
from pumpradar.storage import AlertStore

app = FastAPI(title="PumpRadar platform starter", version="0.4.0")
radar = Radar()
store = AlertStore(os.getenv("PUMPRADAR_DB", "alerts.sqlite3"))
subscribers: set[asyncio.Queue] = set()

# The dashboard and its mock preview also run with the small platform-only
# dependency set. Real research scoring is enabled when the model extra and
# frozen bundle are present; its raw SVM margin is never a probability.
b_scoring_engine = None
b_threshold_info = None
model_load_error = "Install the model extra and restart the API."
if all(find_spec(name) is not None for name in ("pandas", "joblib", "lightgbm", "sklearn")):
    try:
        from pumpradar.live_scoring import CrossSectionalScoringEngine, load_frozen_bundle

        b_model, b_features, b_threshold_info = load_frozen_bundle()
        b_scoring_engine = CrossSectionalScoringEngine(
            b_model, b_features, threshold=b_threshold_info["threshold"],
            cooldown_minutes=b_threshold_info.get("cooldown_minutes", 30),
        )
        model_load_error = ""
    except (ImportError, FileNotFoundError, OSError, ValueError, KeyError) as exc:
        model_load_error = f"Research model could not load: {exc}"


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "web" / "index.html")


def score_and_publish(bar: Bar) -> dict:
    result = radar.ingest(bar)
    if result["score"] is not None and result["score"] >= radar.threshold and store.add(result):
        for queue in tuple(subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(result)
    return result


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    if mock_enabled():
        return {"status": "ok", "scorer": "mock", "mock": True, "market_feed": "mock",
                "score_interval_seconds": 10}
    return {"status": "ok", "scorer": "research_ranker" if b_scoring_engine else "demo_stub",
            "model_loaded": b_scoring_engine is not None,
            "score_interval_seconds": 60 if b_scoring_engine else None}


@app.post("/bars", response_model=DemoScore)
async def ingest_bar(payload: BarInput) -> dict:
    try:
        return score_and_publish(payload.as_bar())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/batches", response_model=BatchResponse)
async def ingest_batch(payload: BatchInput) -> dict:
    """Publish one minute of closed bars as an exchange-wide scoring frame."""
    try:
        bars = [item.as_bar() for item in payload.bars]
        minute = bars[0].close_time
        if any(b.close_time != minute for b in bars) or len({b.symbol for b in bars}) != len(bars):
            raise ValueError("batch needs one minute and each symbol at most once")
        duplicates = [bool(radar.history[b.symbol]) and radar.history[b.symbol][-1] == b for b in bars]
        if all(duplicates):
            # A client can safely retry when it missed the HTTP acknowledgement.
            scores = [radar.latest[b.symbol] for b in bars]
            return {"minute": minute.isoformat(), "coins": sorted(
                scores, key=lambda row: (row["score"] is None, -(row["score"] or 0), row["symbol"])
            )}
        # Validate the entire frame before modifying state.
        if any(radar.history[b.symbol] and b.close_time <= radar.history[b.symbol][-1].close_time for b in bars):
            raise ValueError("bars for each symbol must arrive in increasing time order")
        scores = [score_and_publish(bar) for bar in sorted(bars, key=lambda b: b.symbol)]
        if b_scoring_engine is not None:
            b_scoring_engine.ingest_batch(bars)  # idempotent: ingest_bar drops out-of-order/duplicate bars
            await run_in_threadpool(b_scoring_engine.score_latest)
        return {"minute": minute.isoformat(), "coins": sorted(
            scores, key=lambda row: (row["score"] is None, -(row["score"] or 0), row["symbol"])
        )}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/radar", response_model=RadarResponse)
def get_radar() -> dict:
    if mock_enabled():
        tick = mock_data.tick(mock_data.score_sequence())
        return {"scorer": "mock", "mock": True, "minute": tick.as_of,
                "coins": [], "rows": tick.rows, "notice": NOTICE, "sequence": tick.sequence}
    coins = radar.ranking()
    return {"scorer": "demo_stub", "minute": coins[0]["close_time"] if coins else None, "coins": coins}


@app.get("/alerts", response_model=AlertsResponse)
def get_alerts() -> dict:
    if mock_enabled():
        return {"scorer": "mock", "mock": True, "notice": NOTICE,
                "alerts": mock_data.tick(mock_data.score_sequence()).newAlerts}
    return {"scorer": "demo_stub", "alerts": store.recent()}


@app.get("/events")
async def alert_events() -> StreamingResponse:
    """SSE alert feed. New subscribers receive future alerts; /alerts supplies history."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    async def stream():
        subscribers.add(queue)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    alert = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: alert\ndata: {json.dumps(alert)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            subscribers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/replay", response_model=ReplayResponse)
def replay(payload: ReplayInput) -> dict:
    """Replay closed bars in a fresh state; never mix replay with live state."""
    engine = Radar(threshold=payload.threshold)
    try:
        bars = [item.as_bar() for item in payload.bars]
        if payload.onset_time is not None and payload.onset_time.tzinfo is None:
            raise ValueError("onset_time must include a UTC offset")
        frames = [engine.ingest(bar) for bar in sorted(bars, key=lambda b: (b.close_time, b.symbol))]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    first = None
    if payload.onset_time is not None:
        first = next(
            (a for a in engine.alerts if datetime.fromisoformat(a["close_time"]) < payload.onset_time),
            None,
        )
    return {
        "scorer": "demo_stub",
        "frames": frames,
        "alerts": engine.alerts,
        "first_pre_onset_alert": first,
        "lead_minutes": (
            (payload.onset_time - datetime.fromisoformat(first["close_time"])).total_seconds() / 60
            if first is not None else None
        ),
    }


register_platform(app)
