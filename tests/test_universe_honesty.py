"""Regression checks for the consolidated React-facing API contract."""

from fastapi.testclient import TestClient

from api.main import app
from api.routes import platform
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
