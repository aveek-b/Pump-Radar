"""Verify research artifacts are displayed as a historical audit, never live scores."""

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import AsyncClient, HTTPError, MockTransport, Response

from api.main import app
from api.routes import platform
from pumpradar.prices import Candle, CoinPrice, fetch_candles

RESULTS = Path(__file__).resolve().parents[1] / "results"


def test_experiment_a_matches_committed_artifacts_and_is_separate_from_honesty():
    with TestClient(app) as client:
        audit = client.get("/research/experiment-a").json()
        honesty = client.get("/honesty").json()
        figure = client.get("/research/experiment-a/figures/inflation_by_horizon.png")
        unknown = client.get("/research/experiment-a/figures/missing.png")
    source = json.loads((RESULTS / "metrics_A_tuned.json").read_text(encoding="utf-8"))
    original = next(r for r in source["records"] if r["horizon_min"] == 10
                    and r["feature_set"] == "full" and r["model"] == "lightgbm"
                    and r["protocol"] == "honest_P2")
    point = next(p for p in audit["points"] if p["horizon_min"] == 10
                 and p["feature_set"] == "full" and p["model"] == "lightgbm")
    assert audit["status"] == "historical_experiment_a"
    assert audit["source_commit"] == "a434e86"
    assert len(audit["points"]) == 72
    assert point["honest_ap"] == original["ap"]
    assert point["honest_prevalence"] == original["prevalence"]
    assert point["honest_ci_low"] is not None
    assert point["inflation_ap"] == point["random_ap"] - point["honest_ap"]
    importance_source = json.loads((RESULTS / "permutation_importance.json").read_text(encoding="utf-8"))
    assert audit["importance_by_feature_set"]["full"][0] == importance_source["full"][0]
    assert honesty["status"] == "unavailable" and honesty["precision"] is None
    assert figure.status_code == 200 and figure.content.startswith(b"\x89PNG")
    assert unknown.status_code == 404


def test_live_market_prices_are_real_snapshot_and_all_scores_remain_unavailable(monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "0")

    async def fake_universe():
        return [CoinPrice("LTC", "USDT", "LTCUSDT", 57, .5, 2000,
                          "2026-10-28T13:54:59+00:00", btc_symbol="LTCBTC")]

    monkeypatch.setattr(platform.live_universe, "get", fake_universe)
    with TestClient(app) as client:
        result = client.get("/markets")
    assert result.status_code == 200
    body = result.json()
    assert body["mock"] is False and body["model_version"] is None
    assert body["markets"] == [{"symbol": "LTCUSDT", "price": 57.0,
                                 "change_24h_pct": .5, "volume_24h_quote": 2000.0,
                                 "quote_asset": "USDT", "scored": False}]
    assert body["as_of"] == "2026-10-28T13:54:59Z"


def test_live_market_failure_is_explicit(monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "0")

    async def failed_universe():
        raise HTTPError("feed down")

    monkeypatch.setattr(platform.live_universe, "get", failed_universe)
    with TestClient(app) as client:
        response = client.get("/markets")
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_experiment_b_matches_committed_held_out_artifacts():
    with TestClient(app) as client:
        result = client.get("/research/experiment-b")
        honesty = client.get("/honesty").json()
    assert result.status_code == 200
    body = result.json()
    source = json.loads((RESULTS / "metrics_B_tuned.json").read_text(encoding="utf-8"))
    candidate = json.loads((RESULTS / "deployment_candidate_B.json").read_text(encoding="utf-8"))
    measured = next(r for r in source["records"] if r["horizon_min"] == 10
                    and r["model"] == candidate["deployment_candidate"])
    point = next(p for p in body["points"] if p["horizon_min"] == 10
                 and p["model"] == candidate["deployment_candidate"])
    assert body["status"] == "historical_experiment_b"
    assert body["selected_model"] == candidate["deployment_candidate"]
    assert len(body["points"]) == 36
    assert point["test_ap"] == measured["ap"]
    assert point["hit_at_5"] is not None
    assert honesty["hit_at_5"] is None


def test_real_coin_returns_public_candles_without_model_scores(monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "0")

    async def fake_universe():
        return [CoinPrice("LTC", "USDT", "LTCUSDT", 57, .5, 2000,
                          "2026-10-28T13:54:59+00:00", btc_symbol="LTCBTC")]

    async def fake_candles(symbol, range_key):
        assert symbol == "LTCUSDT" and range_key == "month"
        return [Candle("2026-10-28T13:00:00+00:00", 56, 58, 55, 57, 100, 5700)]

    monkeypatch.setattr(platform.live_universe, "get", fake_universe)
    monkeypatch.setattr(platform, "fetch_candles", fake_candles)
    with TestClient(app) as client:
        result = client.get("/coin/LTCUSDT?range=month")
        missing = client.get("/coin/UNKNOWN")
        invalid = client.get("/coin/LTCUSDT?range=decade")
    assert result.status_code == 200
    body = result.json()
    assert body["market"]["scored"] is False
    assert body["bars"][0]["close"] == 57
    assert body["bars"][0]["volume_quote"] == 5700
    assert body["current"] is None and body["risk_series"] == []
    assert missing.status_code == 404 and invalid.status_code == 422


def test_binance_candle_adapter_uses_exact_quote_volume():
    def respond(request):
        assert request.url.params["interval"] == "4h"
        return Response(200, json=[[0, "56", "58", "55", "57", "100", 0, "6123.45"]])

    async def load():
        async with AsyncClient(transport=MockTransport(respond)) as client:
            return await fetch_candles("LTCUSDT", "month", client)

    candles = asyncio.run(load())
    assert candles[0].volume == 100
    assert candles[0].quote_volume == 6123.45
