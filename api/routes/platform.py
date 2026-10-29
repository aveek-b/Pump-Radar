"""Platform read contract, research artifacts, and live model ranking."""

import asyncio
import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from httpx import HTTPError
from pydantic.json_schema import models_json_schema

from api.mock import PAIRS, PROVENANCE, mock_data
from api.schemas import (
    CoinResponse,
    ExperimentAResponse,
    ExperimentBResponse,
    HonestyResponse,
    LiveModelScoresResponse,
    MarketsResponse,
    PricesEvent,
    RadarTick,
    ReplayDetailResponse,
    ReplayEventsResponse,
)
from pumpradar.prices import LiveUniverseCache, fetch_candles

router = APIRouter()
live_universe = LiveUniverseCache()
RESULTS = Path(__file__).resolve().parents[2] / "results"
REPLAY_DIR = Path(__file__).resolve().parents[2] / "data" / "replay"
DEMO = {"scorer": "research_ranker", "mock": False,
        "notice": "Live model margins are raw rankings; deployment evaluation remains unavailable."}


def mock_enabled() -> bool:
    return os.getenv("PUMPRADAR_MOCK", "0") == "1"


def model_status(btc_pair: str | None, scores: dict, model_loaded: bool) -> str:
    """Explain model coverage without implying an unscored market has a zero risk."""
    if btc_pair is None:
        return "no_btc_pair"
    if not model_loaded:
        return "model_unavailable"
    row = scores.get(btc_pair)
    return "scored" if row is not None and row.score is not None else "warming_up"


@router.get("/markets", response_model=MarketsResponse)
async def markets():
    if mock_enabled():
        prices = mock_data.prices(mock_data.price_sequence())
        return MarketsResponse(**PROVENANCE, as_of=prices.as_of, markets=prices.markets)
    try:
        coins = await live_universe.get()
    except (HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Public market prices are unavailable; retry later.") from exc
    from pumpradar.api import b_scoring_engine

    live_scores = b_scoring_engine.latest_scores if b_scoring_engine else {}
    return MarketsResponse(
        scorer="research_ranker" if b_scoring_engine else "demo_stub", mock=False,
        model_version="exp_b_linear_svm_h10_v1" if b_scoring_engine else None,
        notice="Live public prices. Model scores, when present, are raw SVM ranking margins, not probabilities; the alert threshold is provisional.",
        as_of=datetime.fromisoformat(coins[0].price_as_of) if coins else None,
        markets=[{
            "symbol": coin.symbol, "price": coin.price,
            "change_24h_pct": coin.change_24h_pct,
            "volume_24h_quote": coin.quote_volume_24h,
            "quote_asset": coin.quote_asset,
            "scored": coin.btc_symbol in live_scores and live_scores[coin.btc_symbol].score is not None,
            "model_score": live_scores[coin.btc_symbol].score if coin.btc_symbol in live_scores else None,
            "btc_pair": coin.btc_symbol,
            "model_status": model_status(coin.btc_symbol, live_scores, b_scoring_engine is not None),
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
            "Experiment B is reported separately; no live alert-budget threshold or calibration has been delivered.",
            "The 25-second Sapienza feature set is not the live minute-bar feature contract.",
            "Full-feature results depend strongly on time-of-day encoding; its generality is unresolved.",
        ],
    )


@router.get("/research/experiment-a", response_model=ExperimentAResponse)
def experiment_a():
    return experiment_a_data()


@lru_cache(maxsize=1)
def experiment_b_data() -> ExperimentBResponse:
    """Expose committed held-out research measurements, separate from live scoring."""
    try:
        records = json.loads((RESULTS / "metrics_B_tuned.json").read_text(encoding="utf-8"))["records"]
        hits = json.loads((RESULTS / "hit_at_k_B.json").read_text(encoding="utf-8"))
        candidate = json.loads((RESULTS / "deployment_candidate_B.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Experiment B artifacts are unavailable.") from exc
    hit_by_key = {(r["horizon_min"], r["model"]): r for r in hits if r["k"] == 5}
    points = []
    for row in records:
        if row["split"] != "test" or row["protocol"] != "era_honest":
            continue
        hit = hit_by_key.get((row["horizon_min"], row["model"]))
        points.append({
            "horizon_min": row["horizon_min"], "model": row["model"],
            "test_ap": row.get("ap"), "test_prevalence": row.get("prevalence"),
            "hit_at_5": hit.get("hit_rate") if hit else None,
            "n_test_events": row["n_events"],
        })
    return ExperimentBResponse(
        source_commit="389fe61",
        source_artifacts=["results/metrics_B_tuned.json", "results/hit_at_k_B.json",
                          "results/deployment_candidate_B.json", "results/tuning_B_h10.json"],
        notice="Historical, era-held-out cross-sectional Experiment B. AP and Hit@5 evaluate research ranking; they are not live dashboard risk scores.",
        selected_model=candidate["deployment_candidate"],
        selection_horizon_min=candidate["horizon_min"],
        points=points,
        limitations=[
            "The frozen research candidate produces raw live ranking margins when model dependencies and minute-bar history are available.",
            "Hit@5 is an event ranking measure, not the current dashboard's alert catch rate.",
            "No calibrated live alert threshold, false-alert budget, or measured live latency is available.",
        ],
    )


@router.get("/research/experiment-b", response_model=ExperimentBResponse)
def experiment_b():
    return experiment_b_data()


@router.get("/scores/live", response_model=LiveModelScoresResponse)
def live_scores():
    """Frozen Experiment B SVM margins, separate from mock risk percentages."""
    from pumpradar.api import b_scoring_engine, b_threshold_info, model_load_error

    if mock_enabled():
        return LiveModelScoresResponse(
            status="unavailable", model_version=None, score_type="SVM decision margin",
            threshold=None, threshold_status=None, n_tracked_pairs=0, coins=[],
            notice="Synthetic preview mode; real model scores are hidden.",
        )
    if b_scoring_engine is None:
        return LiveModelScoresResponse(
            status="unavailable", model_version=None, score_type="SVM decision margin",
            threshold=None, threshold_status=None, n_tracked_pairs=0, coins=[],
            notice=model_load_error,
        )
    coins = list(b_scoring_engine.latest_scores.values())
    return LiveModelScoresResponse(
        status="scored" if any(coin.score is not None for coin in coins) else "warming_up",
        model_version="exp_b_linear_svm_h10_v1",
        score_type="10-minute linear SVM decision margin; larger is higher-ranked, not a probability",
        threshold=b_scoring_engine.threshold,
        threshold_status=b_threshold_info.get("status") if b_threshold_info else None,
        alert_target_per_hour=b_threshold_info.get("alerts_per_hour_target") if b_threshold_info else None,
        n_tracked_pairs=len(b_scoring_engine.history),
        coins=[{
            "pair": coin.pair, "score": coin.score,
            "scoring_status": coin.scoring_status, "as_of": coin.as_of,
            "is_alert": coin.is_alert,
        } for coin in coins],
        notice="Real Binance minute bars and frozen Experiment B model. The threshold is provisional; its live false-alert rate is unvalidated.",
    )


@router.post("/scores/backfill")
async def backfill_scores():
    """Operator-triggered real history warmup; never fetch on app startup."""
    if mock_enabled() or os.getenv("PUMPRADAR_ALLOW_BACKFILL") != "1":
        raise HTTPException(403, "Set PUMPRADAR_ALLOW_BACKFILL=1 on the local API to permit backfill.")
    from pumpradar.api import b_scoring_engine

    if b_scoring_engine is None:
        raise HTTPException(503, "Research model runtime is unavailable.")
    from pumpradar.live import discover_symbols
    from pumpradar.live_scoring import backfill_engine

    async with httpx.AsyncClient() as client:
        pairs = await discover_symbols(client)
    counts = await backfill_engine(b_scoring_engine, pairs)
    await run_in_threadpool(b_scoring_engine.score_latest)
    return {
        "n_pairs_requested": len(pairs), "n_bars_loaded": counts,
        "n_pairs_with_full_history": sum(
            1 for n in counts.values() if n >= b_scoring_engine.history_minutes * 0.9
        ),
    }


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
async def coin(pair: str, range: str = "week"):
    if not mock_enabled():
        if range not in {"week", "month", "year"}:
            raise HTTPException(422, "Range must be week, month, or year.")
        try:
            coins = await live_universe.get()
            market = next((coin for coin in coins if coin.symbol == pair), None)
            if market is None:
                raise HTTPException(404, "Unknown live pair")
            candles = await fetch_candles(pair, range)
        except (HTTPError, ValueError, KeyError) as exc:
            raise HTTPException(503, "Public coin history is unavailable; retry later.") from exc
        from pumpradar.api import b_scoring_engine

        score_row = b_scoring_engine.latest_scores.get(market.btc_symbol) if b_scoring_engine and market.btc_symbol else None
        return CoinResponse(
            scorer="research_ranker" if b_scoring_engine else "demo_stub", mock=False,
            model_version="exp_b_linear_svm_h10_v1" if b_scoring_engine else None,
            notice="Public Binance price history. Any raw SVM margin shown is a ranking score, not a calibrated probability.",
            pair=pair,
            market={"symbol": market.symbol, "price": market.price,
                    "change_24h_pct": market.change_24h_pct,
                    "volume_24h_quote": market.quote_volume_24h,
                    "quote_asset": market.quote_asset,
                    "scored": score_row is not None and score_row.score is not None,
                    "model_score": score_row.score if score_row else None,
                    "btc_pair": market.btc_symbol,
                    "model_status": model_status(
                        market.btc_symbol,
                        b_scoring_engine.latest_scores if b_scoring_engine else {},
                        b_scoring_engine is not None,
                    )},
            current=None,
            bars=[{"time": candle.open_time, "open": candle.open, "high": candle.high,
                   "low": candle.low, "close": candle.close,
                   "volume_quote": candle.quote_volume} for candle in candles],
            risk_series=[], alerts=[], drivers=[],
        )
    if pair not in PAIRS:
        raise HTTPException(404, "Unknown scored pair")
    price_sequence = mock_data.price_sequence()
    return mock_data.coin(pair, price_sequence // 5, price_sequence)


@router.get("/replay/events", response_model=ReplayEventsResponse)
def replay_events():
    if mock_enabled():
        return ReplayEventsResponse(**PROVENANCE, events=[mock_data.replay_event()])
    try:
        records = json.loads((REPLAY_DIR / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "Historical replay index is unavailable.") from exc
    events = [{
        "event_id": row["event_id"], "pair": row["pair"],
        "t_onset": row["onset"], "t_telegram": None, "era": "test",
        "first_alert_lead_minutes": None, "rank_at_onset": None,
        "max_gain_pct": row.get("max_gain_pct"),
    } for row in records if row.get("era") == "test" and row.get("available") is True]
    return ReplayEventsResponse(
        scorer="demo_stub", mock=False, model_version=None,
        notice="Historical test-era prices, onset markers, and measured price gains. Model alert lead and ranks have not been evaluated.",
        events=events,
    )


@router.get("/replay/{event_id}", response_model=ReplayDetailResponse,
            responses={404: {"description": "Unknown or unavailable event"}})
def replay_event(event_id: str):
    if mock_enabled():
        if event_id != "mock-example":
            raise HTTPException(404, "Unknown synthetic replay event")
        return mock_data.replay()
    listed = next((row for row in replay_events().events if row.event_id == event_id), None)
    if listed is None:
        raise HTTPException(404, "Unknown or unavailable test-era event")
    try:
        payload = json.loads((REPLAY_DIR / f"{event_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "Historical replay file is unavailable.") from exc
    if payload.get("event_id") != event_id or payload.get("pair") != listed.pair:
        raise HTTPException(503, "Historical replay file does not match its index.")
    return ReplayDetailResponse(
        scorer="demo_stub", mock=False, model_version=None,
        notice="Historical test-era Binance OHLC with measured price gain and decline. No model alert frames or evaluated warning lead are available.",
        event=listed, frames=[],
        decline_from_peak_pct=payload.get("decline_from_peak_pct"),
        peak_time=payload.get("peak_time"),
        bars=[{
            "time": row["time"], "open": row["open"], "high": row["high"],
            "low": row["low"], "close": row["close"], "volume_quote": None,
        } for row in payload["candles"]],
    )


@router.get("/honesty", response_model=HonestyResponse)
def honesty():
    from pumpradar.api import b_scoring_engine

    provenance = PROVENANCE if mock_enabled() else {
        **DEMO, "scorer": "research_ranker" if b_scoring_engine else "demo_stub",
        "model_version": "exp_b_linear_svm_h10_v1" if b_scoring_engine else None,
    }
    return HonestyResponse(**provenance, status="unavailable",
                           limitations=["Live deployment precision, recall, warning lead, and false-alert rate have not been measured. Historical Experiments A and B are reported separately.",
                                        "Mock values and demo heuristics are not probabilities.",
                                        "The live threshold is provisional; held-out replay and false-alert budgets are unmeasured."])


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
