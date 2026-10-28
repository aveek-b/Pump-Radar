"""Single-process scoring API. Live feeder and replay share Radar.ingest."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from pumpradar.engine import Bar, Radar
from pumpradar.prices import LiveUniverseCache
from pumpradar.storage import AlertStore

app = FastAPI(title="PumpRadar platform starter", version="0.3.0")
radar = Radar()
store = AlertStore(os.getenv("PUMPRADAR_DB", "alerts.sqlite3"))
subscribers: set[asyncio.Queue] = set()
universe_cache = LiveUniverseCache()
RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
MODEL_VERSION = "exp_a_leakage_audit_v1"  # Experiment A only; no deployed/frozen bundle yet


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


@app.get("/universe")
async def get_universe() -> dict:
    """Every currently live Binance coin's real price, deduplicated across
    quote pairs, merged with this process's BTC-pair scoring coverage.

    Separates price coverage from model eligibility per the build guide:
    every coin gets a real, live price; only BTC pairs this process has
    received bars for get a real score. Nothing here is fabricated --
    scoring_status is "unavailable" rather than a guessed or zero score for
    every coin the current model cannot cover.
    """
    coins = await universe_cache.get()
    scored_count = 0
    rows = []
    for coin in coins:
        # Eligibility depends on whether a live BTC pair exists for this base
        # asset at all -- never on which quote is being displayed. A coin
        # can show its (preferred, more liquid) USDT price while still being
        # scorable through its separate BTC pair.
        score_row = radar.latest.get(coin.btc_symbol) if coin.btc_symbol else None

        if score_row is not None:
            scoring_status = "warming_up" if score_row["score"] is None else "scored"
            score = score_row["score"]
            score_as_of = score_row["close_time"]
            if scoring_status == "scored":
                scored_count += 1
        elif coin.btc_symbol is not None:
            scoring_status = "warming_up"  # BTC pair exists but no bars ingested yet
            score, score_as_of = None, None
        else:
            scoring_status = "unavailable"  # no BTC pair exists for this coin at all
            score, score_as_of = None, None

        rows.append({
            "base_asset": coin.base_asset,
            "quote_asset": coin.quote_asset,
            "symbol": coin.symbol,
            "price": coin.price,
            "change_24h_pct": coin.change_24h_pct,
            "price_as_of": coin.price_as_of,
            "score": score,
            "score_as_of": score_as_of,
            "scoring_status": scoring_status,
            "model_version": MODEL_VERSION if scoring_status != "unavailable" else None,
        })

    return {
        "data_mode": "live",
        "price_as_of": coins[0].price_as_of if coins else None,
        "n_coins": len(rows),
        "n_scored": scored_count,
        "coins": rows,
    }


@app.get("/honesty")
def get_honesty() -> dict:
    """Real Experiment A leakage-audit results, read from results/*.json.
    Everything returned here is a generated artifact with a known source
    file -- fields the audit has not yet produced (calibration, a chosen
    alert threshold, Hit@k, Experiment B) are returned as null/"not_yet_run"
    rather than a plausible-looking placeholder number.
    """
    try:
        with open(RESULTS_DIR / "metrics_A_tuned.json") as f:
            metrics_a = json.load(f)
        with open(RESULTS_DIR / "bootstrap_A_h10.json") as f:
            bootstrap = json.load(f)
        with open(RESULTS_DIR / "live_binance_universe_check.json") as f:
            live_check = json.load(f)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"results artifact missing: {exc.filename}") from exc

    records = [r for r in metrics_a["records"] if r["model"] is not None]
    honest_h10_full = {
        r["model"]: r["ap"] for r in records
        if r["horizon_min"] == 10 and r["feature_set"] == "full" and r["protocol"] == "honest_P2"
    }

    return {
        "status": "Experiment A (leakage audit) only -- Experiment B (deployed cross-sectional "
                  "model) has not run; no calibration or alert threshold has been chosen",
        "model_version": MODEL_VERSION,
        "dataset": {"source": "SystemsLab-Sapienza 2018-2021 (research archive, not live)",
                    "n_events": 317, "n_symbols": 85},
        "h10_full_feature_ap_by_model": honest_h10_full,
        "bootstrap_ci_h10": bootstrap,
        "live_coin_universe_check": live_check,
        "calibration": "not_yet_run",
        "alert_threshold": "not_yet_chosen",
        "known_limitations": [
            "Scores are not calibrated probabilities.",
            ("Model trained and evaluated only on BTC-paired historical data; "
             f"only {live_check['btc_quoted_pairs']} BTC pairs are live-tradeable right now."),
            ("Full-feature-set AP is driven mainly by time-of-day encoding (permutation "
             "importance), not price level as initially hypothesized; whether this is a "
             "genuine signal or a small-sample artifact is not resolved."),
            "No false-alert-rate validation against ordinary market periods has been run.",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }

