"""B1 read contract and stream. Real engine integration remains a separate handoff."""

import asyncio
import os

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic.json_schema import models_json_schema

from api.mock import PAIRS, PROVENANCE, mock_data
from api.schemas import (
    CoinResponse,
    HonestyResponse,
    MarketsResponse,
    PricesEvent,
    RadarTick,
    ReplayDetailResponse,
    ReplayEventsResponse,
)

router = APIRouter()
DEMO = {"scorer": "demo_stub", "mock": False,
        "notice": "Real market/model integration is pending; retained demo is available separately."}


def mock_enabled() -> bool:
    return os.getenv("PUMPRADAR_MOCK", "0") == "1"


@router.get("/markets", response_model=MarketsResponse)
def markets():
    if not mock_enabled():
        return MarketsResponse(**DEMO, as_of=None, markets=[])
    prices = mock_data.prices(mock_data.price_sequence())
    return MarketsResponse(**PROVENANCE, as_of=prices.as_of, markets=prices.markets)


@router.get("/coin/{pair}", response_model=CoinResponse,
            responses={404: {"description": "Unknown pair"},
                       503: {"description": "Real engine handoff pending"}})
def coin(pair: str):
    if not mock_enabled():
        raise HTTPException(503, "Coin contract awaits the real engine; use the demo /radar.")
    if pair not in PAIRS:
        raise HTTPException(404, "Unknown scored pair")
    price_sequence = mock_data.price_sequence()
    return mock_data.coin(pair, price_sequence // 5, price_sequence)


@router.get("/replay/events", response_model=ReplayEventsResponse)
def replay_events():
    return ReplayEventsResponse(**(PROVENANCE if mock_enabled() else DEMO),
                                events=[mock_data.replay_event()] if mock_enabled() else [])


@router.get("/replay/{event_id}", response_model=ReplayDetailResponse,
            responses={404: {"description": "Unknown or unavailable event"}})
def replay_event(event_id: str):
    if not mock_enabled() or event_id != "mock-example":
        raise HTTPException(404, "Replay event unavailable; held-out files are pending.")
    return mock_data.replay()


@router.get("/honesty", response_model=HonestyResponse)
def honesty():
    return HonestyResponse(**(PROVENANCE if mock_enabled() else DEMO), status="unavailable",
                           limitations=["No frozen research model or evaluation artifacts loaded.",
                                        "Mock values and demo heuristics are not probabilities.",
                                        "Held-out replay and false-alert budgets are unmeasured."])


async def stream_events(request: Request):
    """Pull shared-clock snapshots; no producer tasks, queues, or per-client history."""
    last_price = last_score = None
    yield ": connected\n\n"
    while not await request.is_disconnected():
        if mock_enabled():
            price_sequence = mock_data.price_sequence()
            score_sequence = price_sequence // 5
            if price_sequence != last_price:
                yield f"event: prices\ndata: {mock_data.prices(price_sequence).model_dump_json()}\n\n"
                last_price = price_sequence
            if score_sequence != last_score:
                yield f"event: tick\ndata: {mock_data.tick(score_sequence).model_dump_json()}\n\n"
                last_score = score_sequence
        else:
            yield ": real engine pending; use /events for demo alerts\n\n"
        # Cancellation propagates through this await. No child task survives disconnect.
        await asyncio.sleep(2 if mock_enabled() else 15)


@router.get("/stream", response_class=StreamingResponse, responses={200: {
    "description": "SSE named events: prices (2 s), tick (10 s in mock mode). "
                   "Initial snapshots sent on connection; reconnect gets the latest snapshot. "
                   "Payload schemas are PricesEvent and RadarTick. Non-mock sends comments only.",
    "content": {"text/event-stream": {"schema": {"type": "string"}}},
    "x-event-schemas": {"prices": {"$ref": "#/components/schemas/PricesEvent"},
                        "tick": {"$ref": "#/components/schemas/RadarTick"}},
}})
async def stream(request: Request):
    return StreamingResponse(stream_events(request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def register_platform(app: FastAPI):
    app.include_router(router)
    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        _, event_schema = models_json_schema(
            [(PricesEvent, "validation"), (RadarTick, "validation")],
            ref_template="#/components/schemas/{model}",
        )
        schema["components"]["schemas"].update(event_schema["$defs"])
        return schema

    app.openapi = openapi
