"""B1 read contract and stream. Real engine integration remains a separate handoff."""

import asyncio
import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from httpx import HTTPError
from pydantic.json_schema import models_json_schema

from api.mock import PAIRS, PROVENANCE, mock_data
from api.schemas import (
    CoinResponse,
    ExperimentAResponse,
    HonestyResponse,
    MarketsResponse,
    PricesEvent,
    RadarTick,
    ReplayDetailResponse,
    ReplayEventsResponse,
)
from pumpradar.prices import LiveUniverseCache

router = APIRouter()
live_universe = LiveUniverseCache()
RESULTS = Path(__file__).resolve().parents[2] / "results"
DEMO = {"scorer": "demo_stub", "mock": False,
        "notice": "Real market/model integration is pending; retained demo is available separately."}


def mock_enabled() -> bool:
    return os.getenv("PUMPRADAR_MOCK", "0") == "1"


@router.get("/markets", response_model=MarketsResponse)
async def markets():
    if mock_enabled():
        prices = mock_data.prices(mock_data.price_sequence())
        return MarketsResponse(**PROVENANCE, as_of=prices.as_of, markets=prices.markets)
    try:
        coins = await live_universe.get()
    except (HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Public market prices are unavailable; retry later.") from exc
    return MarketsResponse(
        scorer="demo_stub", mock=False, model_version=None,
        notice="Live public market prices. No research model is loaded; none is scored.",
        as_of=datetime.fromisoformat(coins[0].price_as_of) if coins else None,
        markets=[{
            "symbol": coin.symbol, "price": coin.price,
            "change_24h_pct": coin.change_24h_pct,
            "volume_24h_quote": coin.quote_volume_24h,
            "quote_asset": coin.quote_asset, "scored": False,
        } for coin in coins],
    )


@lru_cache(maxsize=1)
def experiment_a_data() -> ExperimentAResponse:
    """Read Kaashvi's committed audit outputs without interpreting them as live scores."""
    try:
        records = json.loads((RESULTS / "metrics_A_tuned.json").read_text(encoding="utf-8"))["records"]
        intervals = json.loads((RESULTS / "bootstrap_A_h10.json").read_text(encoding="utf-8"))
        importance = json.loads((RESULTS / "permutation_importance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Experiment A artifacts are unavailable.") from exc
    by_key = {(r["horizon_min"], r["feature_set"], r["model"], r["protocol"]): r
              for r in records if r.get("model") is not None}
    ci = {(r["feature_set"], r["model"]): r for r in intervals
          if r["protocol"] == "honest_P2"}
    points = []
    for horizon, feature_set, model in sorted({key[:3] for key in by_key}):
        random = by_key.get((horizon, feature_set, model, "random_P0"))
        honest = by_key.get((horizon, feature_set, model, "honest_P2"))
        if not random or not honest:
            continue
        random_ap, honest_ap = random.get("ap"), honest.get("ap")
        interval = ci.get((feature_set, model)) if horizon == 10 else None
        points.append({
            "horizon_min": horizon, "feature_set": feature_set, "model": model,
            "random_ap": random_ap, "honest_ap": honest_ap,
            "inflation_ap": random_ap - honest_ap if random_ap is not None and honest_ap is not None else None,
            "honest_ci_low": interval["ci_low"] if interval else None,
            "honest_ci_high": interval["ci_high"] if interval else None,
            "honest_prevalence": honest.get("prevalence"),
        })
    return ExperimentAResponse(
        source_commit="a434e86",
        source_artifacts=["results/metrics_A_tuned.json", "results/bootstrap_A_h10.json",
                          "results/permutation_importance.json"],
        notice="Historical Sapienza Experiment A: average precision (AP), not calibrated risk. This is a leakage audit, not the cross-sectional deployed model.",
        points=points,
        importance_by_feature_set=importance,
        limitations=[
            "Experiment B, Hit@5, alert-budget threshold and calibration have not been delivered.",
            "The 25-second Sapienza feature set is not the live minute-bar feature contract.",
            "Full-feature results depend strongly on time-of-day encoding; its generality is unresolved.",
        ],
    )


@router.get("/research/experiment-a", response_model=ExperimentAResponse)
def experiment_a():
    return experiment_a_data()


@router.get("/research/experiment-a/figures/{name}", response_class=FileResponse,
            responses={404: {"description": "Unknown figure"}})
def experiment_a_figure(name: str):
    if name not in {"inflation_by_horizon.png", "prevalence_by_horizon.png"}:
        raise HTTPException(404, "Unknown figure")
    path = RESULTS / "figures" / name
    if not path.is_file():
        raise HTTPException(404, "Figure unavailable")
    return FileResponse(path, media_type="image/png")


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
                           limitations=["No frozen cross-sectional model or deployment evaluation is loaded. Historical Experiment A is reported separately.",
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
