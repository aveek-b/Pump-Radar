from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from pumpradar.api import app


def test_replay_reports_lead_without_mutating_live_radar():
    client = TestClient(app)
    before = client.get("/radar").json()
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    bars = [
        {
            "symbol": "REPLAYBTC",
            "close_time": (t0 + timedelta(minutes=i)).isoformat(),
            "close": 1,
            "volume_btc": 100 if i == 5 else 1,
            "taker_buy_btc": 90 if i == 5 else 0.9,
            "trade_count": 10,
        }
        for i in range(6)
    ]
    response = client.post(
        "/replay", json={"bars": bars, "onset_time": (t0 + timedelta(minutes=10)).isoformat()}
    )
    assert response.status_code == 200
    assert response.json()["lead_minutes"] == 5
    assert response.json()["scorer"] == "demo_stub"
    assert client.get("/radar").json() == before


def test_batch_rejects_mixed_minute_without_partial_ingestion():
    client = TestClient(app)
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    rows = [
        {
            "symbol": symbol, "close_time": (t0 + timedelta(minutes=i)).isoformat(),
            "close": 1, "volume_btc": 1, "taker_buy_btc": 0.5, "trade_count": 1,
        }
        for i, symbol in enumerate(("MIXABTC", "MIXBBTC"))
    ]
    response = client.post("/batches", json={"bars": rows})
    assert response.status_code == 422
    assert not any(row["symbol"] == "MIXABTC" for row in client.get("/radar").json()["coins"])


def test_batch_scores_same_minute_for_multiple_symbols():
    client = TestClient(app)
    t0 = datetime(2021, 2, 1, tzinfo=UTC)
    rows = [
        {
            "symbol": symbol, "close_time": t0.isoformat(), "close": 1,
            "volume_btc": 1, "taker_buy_btc": 0.5, "trade_count": 1,
        }
        for symbol in ("BATCHABTC", "BATCHBBTC")
    ]
    response = client.post("/batches", json={"bars": rows})
    assert response.status_code == 200
    assert len(response.json()["coins"]) == 2
    assert all(row["status"] == "warming_up" for row in response.json()["coins"])
    assert client.post("/batches", json={"bars": rows}).json() == response.json()


def test_dashboard_is_served():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Current minute ranking" in response.text
