"""Single-process scoring API. Live feeder and replay share Radar.ingest."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from pumpradar.engine import Bar, Radar
from pumpradar.storage import AlertStore

app = FastAPI(title="PumpRadar platform starter", version="0.3.0")
radar = Radar()
store = AlertStore(os.getenv("PUMPRADAR_DB", "alerts.sqlite3"))
subscribers: set[asyncio.Queue] = set()


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "web" / "index.html")


class BarInput(BaseModel):
    symbol: str
    close_time: datetime
    close: float = Field(gt=0)
    volume_btc: float = Field(ge=0)
    taker_buy_btc: float = Field(ge=0)
    trade_count: int = Field(ge=0)

    def as_bar(self) -> Bar:
        return Bar(**self.model_dump())


class ReplayInput(BaseModel):
    bars: list[BarInput]
    onset_time: datetime | None = None
    threshold: float = Field(default=0.8, ge=0, le=1)


class BatchInput(BaseModel):
    bars: list[BarInput] = Field(min_length=1)


def score_and_publish(bar: Bar) -> dict:
    result = radar.ingest(bar)
    if result["score"] is not None and result["score"] >= radar.threshold and store.add(result):
        for queue in tuple(subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(result)
    return result


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "scorer": "demo_stub"}


@app.post("/bars")
async def ingest_bar(payload: BarInput) -> dict:
    try:
        return score_and_publish(payload.as_bar())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/batches")
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
        return {"minute": minute.isoformat(), "coins": sorted(
            scores, key=lambda row: (row["score"] is None, -(row["score"] or 0), row["symbol"])
        )}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/radar")
def get_radar() -> dict:
    coins = radar.ranking()
    return {"scorer": "demo_stub", "minute": coins[0]["close_time"] if coins else None, "coins": coins}


@app.get("/alerts")
def get_alerts() -> dict:
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


@app.post("/replay")
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

