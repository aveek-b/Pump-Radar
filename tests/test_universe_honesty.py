"""Regression checks for the consolidated React-facing API contract."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import app
from api.routes import platform
from pumpradar import api as scoring_api
from pumpradar.prices import CoinPrice, simple_moving_average


def test_display_pair_does_not_imply_a_live_research_score(monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "0")

    async def fake_universe():
        return [CoinPrice("LTC", "USDT", "LTCUSDT", 57, .5, 2000,
                          "2026-01-01T00:00:00+00:00", btc_symbol="LTCBTC")]

    monkeypatch.setattr(platform.live_universe, "get", fake_universe)
    with TestClient(app) as client:
        market = client.get("/markets").json()["markets"][0]
    assert market["symbol"] == "LTCUSDT"
    assert market["scored"] is False


def test_moving_average_waits_for_full_window():
    assert simple_moving_average([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0]


def test_real_market_uses_btc_pair_model_margin_without_implying_probability(monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "0")

    async def fake_universe():
        return [CoinPrice("LTC", "USDT", "LTCUSDT", 57, .5, 2000,
                          "2026-01-01T00:00:00+00:00", btc_symbol="LTCBTC")]

    score = SimpleNamespace(pair="LTCBTC", score=1.7, scoring_status="scored",
                            as_of="2026-01-01T00:01:00+00:00", is_alert=True)
    engine = SimpleNamespace(latest_scores={"LTCBTC": score}, history={"LTCBTC": []},
                             threshold=1.2)
    monkeypatch.setattr(platform.live_universe, "get", fake_universe)
    monkeypatch.setattr(scoring_api, "b_scoring_engine", engine)
    monkeypatch.setattr(scoring_api, "b_threshold_info", {"alerts_per_hour_target": 2})
    with TestClient(app) as client:
        market = client.get("/markets").json()["markets"][0]
        live = client.get("/scores/live").json()

    assert market["scored"] is True and market["model_score"] == 1.7
    assert market["btc_pair"] == "LTCBTC" and market["model_status"] == "scored"
    assert live["status"] == "scored" and live["coins"][0]["pair"] == "LTCBTC"
    assert live["coins"][0]["score"] == 1.7
    assert live["alert_target_per_hour"] == 2
    assert "not a probability" in live["score_type"]
