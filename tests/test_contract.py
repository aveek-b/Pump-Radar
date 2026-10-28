import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.mock import MockData, mock_data
from api.routes import platform
from api.schemas import PricesEvent, RadarTick


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "1")
    monkeypatch.setattr(mock_data, "price_sequence", lambda: 0)
    with TestClient(app) as client:
        yield client


def test_mock_contract_has_repeatable_ranked_coins_and_separate_markets(client):
    radar = client.get("/radar").json()
    assert radar == client.get("/radar").json()
    assert radar["mock"] and radar["scorer"] == "mock"
    assert radar["coins"] == []  # Never pass synthetic risk off as the old demo heuristic.
    assert len(radar["rows"]) == 60
    risks = [r["risk"]["10"] for r in radar["rows"]]
    assert risks == sorted(risks, reverse=True)
    assert all(set(r["risk"]) == {"1", "3", "5", "10", "30", "60"} for r in radar["rows"])
    markets = client.get("/markets").json()
    assert len(markets["markets"]) == 61
    assert sum(m["scored"] for m in markets["markets"]) == 60
    coin = client.get("/coin/MOCK001BTC").json()
    assert coin["current"] == radar["rows"][0]
    assert len(coin["bars"]) == 360 and len(coin["drivers"]) == 5
    assert len(coin["risk_series"]) == 360
    assert coin["risk_series"][-1]["risk"] == coin["current"]["risk"]
    assert all(b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"]
               for b in coin["bars"])
    assert coin["market"] == markets["markets"][0]
    assert client.get("/coin/UNKNOWNBTC").status_code == 404
    assert client.get("/alerts").json()["alerts"] == [coin["current"]["alert"]]
    health = client.get("/health").json()
    assert not health["model_loaded"] and health["score_interval_seconds"] == 10


def test_fixture_sequence_reproduces_across_instances():
    a, b = MockData(), MockData()
    assert a.tick(17) == b.tick(17)
    assert a.prices(85) == b.prices(85)
    assert a.tick(17) != a.tick(18)
    assert a.prices(85) != a.prices(86)


def test_replay_and_honesty_do_not_claim_measured_results(client):
    before = client.get("/radar").json()
    events = client.get("/replay/events").json()["events"]
    assert events[0]["era"] == "mock"
    assert events[0]["first_alert_lead_minutes"] is None
    replay = client.get(f"/replay/{events[0]['event_id']}")
    assert replay.status_code == 200 and len(replay.json()["frames"]) == 12
    assert client.get("/replay/not-found").status_code == 404
    assert client.get("/radar").json() == before
    honesty = client.get("/honesty").json()
    assert honesty["status"] == "unavailable"
    for field in ("precision", "recall", "hit_at_5", "median_lead_minutes",
                  "false_alerts_per_hour", "alert_budget_per_hour"):
        assert honesty[field] is None


def test_non_mock_routes_report_pending_integration(client, monkeypatch):
    monkeypatch.setenv("PUMPRADAR_MOCK", "0")
    assert client.get("/radar").json()["scorer"] == "demo_stub"
    assert client.get("/markets").json()["markets"] == []
    assert client.get("/replay/events").json()["events"] == []
    assert client.get("/replay/mock-example").status_code == 404
    assert client.get("/coin/MOCK001BTC").status_code == 503
    assert not client.get("/health").json()["mock"]
    assert not client.get("/honesty").json()["mock"]


def test_stream_cadence_payloads_and_disconnect(client, monkeypatch):
    elapsed = 0

    class Request:
        async def is_disconnected(self):
            return elapsed >= 12

    async def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    monkeypatch.setattr(platform.asyncio, "sleep", sleep)
    monkeypatch.setattr(mock_data, "price_sequence", lambda: int(elapsed // 2))

    async def collect():
        before = asyncio.all_tasks()
        response = await platform.stream(Request())
        assert response.media_type == "text/event-stream"
        assert response.headers["x-accel-buffering"] == "no"
        events = [chunk async for chunk in response.body_iterator]
        assert asyncio.all_tasks() == before
        return events

    frames = asyncio.run(collect())
    prices = [PricesEvent.model_validate_json(f.split("data: ", 1)[1])
              for f in frames if f.startswith("event: prices")]
    ticks = [RadarTick.model_validate_json(f.split("data: ", 1)[1])
             for f in frames if f.startswith("event: tick")]
    assert [p.sequence for p in prices] == list(range(6))
    assert [t.sequence for t in ticks] == [0, 1]
    assert (prices[1].as_of - prices[0].as_of).total_seconds() == 2
    assert (ticks[1].as_of - ticks[0].as_of).total_seconds() == 10


def test_stream_cancellation_and_reconnect_leave_no_producers(client, monkeypatch):
    class Request:
        async def is_disconnected(self):
            return False

    async def check():
        before = asyncio.all_tasks()
        generator = platform.stream_events(Request())
        await anext(generator)  # comment
        await anext(generator)  # prices
        await anext(generator)  # tick
        sleeping = asyncio.Event()

        async def sleep(seconds):
            sleeping.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(platform.asyncio, "sleep", sleep)
        task = asyncio.create_task(anext(generator))
        await sleeping.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await generator.aclose()
        assert asyncio.all_tasks() == before
        reconnect = platform.stream_events(Request())
        await anext(reconnect)
        frame = await anext(reconnect)
        assert json.loads(frame.split("data: ", 1)[1])["sequence"] == 0
        await reconnect.aclose()
        assert asyncio.all_tasks() == before

    asyncio.run(check())


def test_openapi_describes_sse_and_all_b1_routes(client):
    schema = client.get("/openapi.json").json()
    for path in ("/markets", "/radar", "/coin/{pair}", "/alerts", "/stream",
                 "/replay/events", "/replay/{event_id}", "/honesty", "/health"):
        assert "get" in schema["paths"][path]
    response = schema["paths"]["/stream"]["get"]["responses"]["200"]
    assert "text/event-stream" in response["content"]
    for name in ("PricesEvent", "RadarTick"):
        assert name in schema["components"]["schemas"]
    assert "post" in schema["paths"]["/replay"]
