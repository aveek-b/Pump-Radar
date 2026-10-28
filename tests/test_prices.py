
import httpx
import pytest

from pumpradar.prices import (
    CoinPrice,
    LiveUniverseCache,
    fetch_live_universe,
    select_display_pairs,
)

EXCHANGE_INFO = {
    "symbols": [
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
        {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC", "status": "TRADING", "isSpotTradingAllowed": True},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
        {"symbol": "DEADBTC", "baseAsset": "DEAD", "quoteAsset": "BTC", "status": "BREAK", "isSpotTradingAllowed": True},
        {"symbol": "MARGINONLYUSDT", "baseAsset": "MARGINONLY", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": False},
    ]
}

TICKERS = [
    {"symbol": "BTCUSDT", "lastPrice": "65000.0", "priceChangePercent": "1.2", "quoteVolume": "1000000"},
    {"symbol": "ETHBTC", "lastPrice": "0.05", "priceChangePercent": "-0.5", "quoteVolume": "100"},
    {"symbol": "ETHUSDT", "lastPrice": "3200.0", "priceChangePercent": "2.1", "quoteVolume": "500000"},
]


def test_select_display_pairs_dedupes_and_prefers_usdt():
    pairs = select_display_pairs(EXCHANGE_INFO["symbols"])
    assert set(pairs.keys()) == {"BTC", "ETH"}  # DEAD excluded (not TRADING), MARGINONLY excluded (not spot)
    assert pairs["ETH"]["quoteAsset"] == "USDT"  # ETH trades BTC and USDT; USDT preferred


def _mock_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/exchangeInfo"):
            return httpx.Response(200, json=EXCHANGE_INFO)
        if request.url.path.endswith("/ticker/24hr"):
            return httpx.Response(200, json=TICKERS)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_fetch_live_universe_builds_coin_prices():
    async with _mock_client() as client:
        coins = await fetch_live_universe(client)

    by_base = {c.base_asset: c for c in coins}
    assert set(by_base) == {"BTC", "ETH"}
    assert by_base["BTC"].symbol == "BTCUSDT"
    assert by_base["BTC"].price == 65000.0
    assert by_base["ETH"].symbol == "ETHUSDT"  # dedup preferred USDT over BTC quote
    # Even though ETH displays its USDT price, it still has a live BTC pair --
    # eligibility must not be lost just because USDT was preferred for display.
    assert by_base["ETH"].btc_symbol == "ETHBTC"
    assert by_base["BTC"].btc_symbol is None  # BTCUSDT has no BTC-quoted pair (BTC/BTC doesn't exist)
    assert all(isinstance(c, CoinPrice) for c in coins)
    assert all(c.price_as_of for c in coins)


@pytest.mark.anyio
async def test_live_universe_cache_reuses_within_ttl(monkeypatch):
    calls = {"n": 0}

    async def fake_fetch(client=None):
        calls["n"] += 1
        return [CoinPrice("BTC", "USDT", "BTCUSDT", 1.0, 0.0, 0.0, "t", btc_symbol=None)]

    monkeypatch.setattr("pumpradar.prices.fetch_live_universe", fake_fetch)
    cache = LiveUniverseCache(ttl_seconds=1000)

    await cache.get()
    await cache.get()
    assert calls["n"] == 1  # second call served from cache, no new fetch


@pytest.fixture
def anyio_backend():
    return "asyncio"
