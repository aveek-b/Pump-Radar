from fastapi.testclient import TestClient

from pumpradar import prices
from pumpradar.api import app, universe_cache
from pumpradar.prices import Candle, CoinPrice


def _fake_coins():
    return [
        CoinPrice("BTC", "USDT", "BTCUSDT", 65000.0, 1.2, 1_000_000, "2026-01-01T00:00:00+00:00", btc_symbol=None),
        CoinPrice("ETH", "BTC", "ETHBTC", 0.05, -0.5, 100, "2026-01-01T00:00:00+00:00", btc_symbol="ETHBTC"),
        CoinPrice("DOGE", "USDT", "DOGEUSDT", 0.1, 3.0, 5000, "2026-01-01T00:00:00+00:00", btc_symbol=None),
        # Regression case for a real bug caught by an end-to-end smoke test: a coin
        # that DISPLAYS its USDT price but still has a separate live BTC pair must
        # remain scorable -- eligibility must not be lost to display preference.
        CoinPrice("LTC", "USDT", "LTCUSDT", 57.0, 0.5, 2000, "2026-01-01T00:00:00+00:00", btc_symbol="LTCBTC"),
    ]


def test_universe_separates_price_from_scoring(monkeypatch):
    async def fake_fetch(client=None):
        return _fake_coins()

    monkeypatch.setattr(prices, "fetch_live_universe", fake_fetch)
    universe_cache._coins = []
    universe_cache._fetched_at = 0.0

    client = TestClient(app)
    response = client.get("/universe")
    assert response.status_code == 200
    body = response.json()

    assert body["n_coins"] == 4
    by_base = {c["base_asset"]: c for c in body["coins"]}

    # DOGE has no BTC pair at all -> genuinely unavailable, real price still shown.
    assert by_base["DOGE"]["scoring_status"] == "unavailable"
    assert by_base["DOGE"]["score"] is None
    assert by_base["DOGE"]["price"] == 0.1

    # ETH is displayed as a BTC pair, no bars ingested yet -> warming_up, not a fake score.
    assert by_base["ETH"]["scoring_status"] == "warming_up"
    assert by_base["ETH"]["score"] is None

    # LTC displays its USDT price but still has a live BTC pair -> must still be
    # warming_up (eligible), not unavailable. This is the exact bug a mocked-only
    # test suite missed and an end-to-end run against the real API caught.
    assert by_base["LTC"]["scoring_status"] == "warming_up"
    assert by_base["LTC"]["quote_asset"] == "USDT"

    # Every coin still gets a real price regardless of scoring coverage.
    assert all(c["price"] > 0 for c in body["coins"])


def test_universe_reflects_a_real_radar_score(monkeypatch):
    # Seed the radar engine directly with a BTC-pair score, then check /universe reflects it.
    from datetime import UTC, datetime

    from pumpradar.api import radar
    from pumpradar.engine import Bar

    for i in range(6):
        radar.ingest(Bar(
            symbol="ETHBTC", close_time=datetime(2026, 1, 1, tzinfo=UTC).replace(minute=i),
            close=1.0, volume_btc=100.0 if i == 5 else 1.0,
            taker_buy_btc=90.0 if i == 5 else 0.9, trade_count=10,
        ))

    async def fake_fetch_eth(client=None):
        return [CoinPrice("ETH", "BTC", "ETHBTC", 0.05, -0.5, 100, "2026-01-01T00:00:00+00:00", btc_symbol="ETHBTC")]

    monkeypatch.setattr(prices, "fetch_live_universe", fake_fetch_eth)
    universe_cache._coins = []
    universe_cache._fetched_at = 0.0

    client = TestClient(app)
    body = client.get("/universe").json()
    eth_row = body["coins"][0]
    assert eth_row["scoring_status"] == "scored"
    assert eth_row["score"] is not None
    assert eth_row["model_version"] is not None


def test_honesty_returns_real_results_with_no_placeholders():
    client = TestClient(app)
    response = client.get("/honesty")
    assert response.status_code == 200
    body = response.json()

    assert body["dataset"]["n_events"] == 317
    assert body["calibration"] == "not_yet_run"
    assert body["alert_threshold"] == "not_yet_chosen"
    assert "lightgbm" in body["experiment_a_h10_full_feature_ap_by_model"]
    assert 0.0 < body["experiment_a_h10_full_feature_ap_by_model"]["lightgbm"] < 1.0
    assert len(body["known_limitations"]) > 0
    assert body["live_coin_universe_check"]["btc_quoted_pairs"] > 0

    exp_b = body["experiment_b"]
    assert "random_forest" in exp_b["test_ap_h10_by_model"]
    assert 0.0 <= exp_b["test_ap_h10_by_model"]["random_forest"] <= 1.0
    assert "random_forest" in exp_b["hit_at_1_h10_by_model"]
    assert "random_forest" in exp_b["hit_at_5_h10_by_model"]
    assert exp_b["deployment_candidate"]["deployment_candidate"] in exp_b["test_ap_h10_by_model"]


def _fake_candles(n=60):
    return [
        Candle(f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00", 100.0 + i, 105.0 + i, 95.0 + i, 100.0 + i, 1000.0)
        for i in range(n)
    ]


def test_coin_candles_returns_real_shaped_data(monkeypatch):
    async def fake_fetch(symbol, range_key, client=None):
        assert symbol == "BTCUSDT"
        assert range_key == "month"
        return _fake_candles()

    monkeypatch.setattr("pumpradar.api.fetch_candles", fake_fetch)
    client = TestClient(app)
    response = client.get("/coin/btcusdt/candles?range=month")
    assert response.status_code == 200
    body = response.json()

    assert body["symbol"] == "BTCUSDT"
    assert body["range"] == "month"
    assert len(body["candles"]) == 60
    assert len(body["sma_20"]) == 60
    assert body["sma_20"][:19] == [None] * 19
    assert body["sma_20"][19] is not None


def test_coin_candles_rejects_unknown_range():
    client = TestClient(app)
    response = client.get("/coin/BTCUSDT/candles?range=decade")
    assert response.status_code == 422


def test_coin_candles_404s_on_empty_result(monkeypatch):
    async def fake_fetch(symbol, range_key, client=None):
        return []

    monkeypatch.setattr("pumpradar.api.fetch_candles", fake_fetch)
    client = TestClient(app)
    response = client.get("/coin/NOPEUSDT/candles?range=week")
    assert response.status_code == 404


def test_coin_candles_502s_on_upstream_failure(monkeypatch):
    async def fake_fetch(symbol, range_key, client=None):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr("pumpradar.api.fetch_candles", fake_fetch)
    client = TestClient(app)
    response = client.get("/coin/BTCUSDT/candles?range=week")
    assert response.status_code == 502


def test_replay_events_returns_only_available_events(tmp_path, monkeypatch):
    import json as json_mod

    index = [
        {"event_id": "event_0001", "pair": "PUMPBTC", "symbol": "PUMP", "era": "train",
         "onset": "2018-01-01T00:00:00+00:00", "available": True, "n_candles": 100},
        {"event_id": "event_0002", "pair": "NOPEBTC", "symbol": "NOPE", "era": "train",
         "onset": "2018-01-02T00:00:00+00:00", "available": False, "n_candles": 0},
    ]
    with open(tmp_path / "index.json", "w") as f:
        json_mod.dump(index, f)

    monkeypatch.setattr("pumpradar.api.REPLAY_DIR", tmp_path)
    client = TestClient(app)
    response = client.get("/replay/events")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["event_id"] == "event_0001"


def test_replay_events_503s_when_index_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("pumpradar.api.REPLAY_DIR", tmp_path)
    client = TestClient(app)
    response = client.get("/replay/events")
    assert response.status_code == 503


def test_replay_event_returns_real_candles(tmp_path, monkeypatch):
    import json as json_mod

    payload = {
        "event_id": "event_0001", "pair": "PUMPBTC", "symbol": "PUMP", "era": "train",
        "onset": "2018-01-01T00:00:00+00:00",
        "candles": [{"time": "2018-01-01T00:00:00+00:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    }
    with open(tmp_path / "event_0001.json", "w") as f:
        json_mod.dump(payload, f)

    monkeypatch.setattr("pumpradar.api.REPLAY_DIR", tmp_path)
    client = TestClient(app)
    response = client.get("/replay/event_0001")
    assert response.status_code == 200
    assert response.json()["pair"] == "PUMPBTC"


def test_replay_event_404s_for_unknown_event(tmp_path, monkeypatch):
    monkeypatch.setattr("pumpradar.api.REPLAY_DIR", tmp_path)
    client = TestClient(app)
    response = client.get("/replay/event_9999")
    assert response.status_code == 404


def test_replay_event_rejects_path_traversal():
    client = TestClient(app)
    response = client.get("/replay/..%2F..%2Fsecrets")
    assert response.status_code in (404, 422)  # never 200, never reads outside REPLAY_DIR
