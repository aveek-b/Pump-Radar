"""Verify research artifacts are displayed as a historical audit, never live scores."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import HTTPError

from api.main import app
from api.routes import platform
from pumpradar.prices import CoinPrice

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
