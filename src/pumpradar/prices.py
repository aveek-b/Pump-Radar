"""Live, all-quote Binance price feed.

Deliberately separate from the scoring engine (engine.py's Bar/Radar, which
is BTC-pair-only by design and contract). The build guide is explicit:
"separate price coverage from model eligibility" -- the live coin count
(130+) and the set of coins the trained model can actually score (currently
BTC pairs only) are different numbers, and must never be conflated. This
module answers "what is trading right now and at what price"; api.py merges
it with engine.py's scores to report each coin's honest scoring_status.

Uses only the public, unauthenticated data-api.binance.vision endpoints --
no API key, matching the build guide's "Market Data Only" requirement.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

MARKET_API = "https://data-api.binance.vision/api/v3"

# Preference order for which quote pair represents a base asset when it
# trades against more than one. USDT first: it is by far the most complete
# live quote universe (hundreds of pairs vs. a few dozen BTC pairs today).
QUOTE_PREFERENCE = ("USDT", "BTC", "FDUSD", "USDC")
_QUOTE_RANK = {q: i for i, q in enumerate(QUOTE_PREFERENCE)}


@dataclass(frozen=True)
class CoinPrice:
    base_asset: str
    quote_asset: str
    symbol: str
    price: float
    change_24h_pct: float
    quote_volume_24h: float
    price_as_of: str
    btc_symbol: str | None  # this base asset's live BTC pair, if any -- independent
    # of which quote was chosen for display. Model-scoring eligibility must be
    # checked against this, never against `quote_asset`: a coin can display its
    # USDT price (more liquid, preferred) while still having a live BTC pair the
    # engine can score. Conflating the two was a real bug caught by an end-to-end
    # smoke test against the live API, not just mocked unit tests.


async def fetch_exchange_info(client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(f"{MARKET_API}/exchangeInfo", timeout=20)
    response.raise_for_status()
    return response.json()["symbols"]


async def fetch_24hr_tickers(client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(f"{MARKET_API}/ticker/24hr", timeout=20)
    response.raise_for_status()
    return response.json()


def select_display_pairs(symbols_info: list[dict]) -> dict[str, dict]:
    """One display pair per base asset -- deduplicated across quote
    currencies, e.g. a BTC pair and a USDT pair for the same coin count as
    one. Only currently TRADING, spot-enabled symbols are eligible.
    """
    eligible = (
        s for s in symbols_info
        if s.get("status") == "TRADING" and s.get("isSpotTradingAllowed", False)
    )
    by_base: dict[str, dict] = {}
    for s in eligible:
        base, quote = s["baseAsset"], s["quoteAsset"]
        existing = by_base.get(base)
        if existing is None or _QUOTE_RANK.get(quote, len(QUOTE_PREFERENCE)) < _QUOTE_RANK.get(
            existing["quoteAsset"], len(QUOTE_PREFERENCE)
        ):
            by_base[base] = s
    return by_base


def find_btc_symbols(symbols_info: list[dict]) -> dict[str, str]:
    """base_asset -> live BTC-pair symbol, independent of display preference.
    Used to determine model-scoring eligibility even when a coin's price is
    displayed via a different (e.g. USDT) quote.
    """
    return {
        s["baseAsset"]: s["symbol"]
        for s in symbols_info
        if s.get("quoteAsset") == "BTC"
        and s.get("status") == "TRADING"
        and s.get("isSpotTradingAllowed", False)
    }


async def fetch_live_universe(client: httpx.AsyncClient | None = None) -> list[CoinPrice]:
    """Real, current snapshot of the live Binance universe: one price per
    base asset. Built entirely from the public exchangeInfo + 24hr ticker
    endpoints -- never fabricated, estimated, or carried over from a stale
    cache beyond what LiveUniverseCache's TTL allows.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        symbols_info, tickers = await asyncio.gather(
            fetch_exchange_info(client), fetch_24hr_tickers(client)
        )
        display_pairs = select_display_pairs(symbols_info)
        btc_symbols = find_btc_symbols(symbols_info)
        ticker_by_symbol = {t["symbol"]: t for t in tickers}
        now = datetime.now(UTC).isoformat()

        coins = []
        for base, info in display_pairs.items():
            ticker = ticker_by_symbol.get(info["symbol"])
            if ticker is None:
                continue  # symbol exists but has no 24hr ticker row (e.g. just listed)
            coins.append(
                CoinPrice(
                    base_asset=base,
                    quote_asset=info["quoteAsset"],
                    symbol=info["symbol"],
                    price=float(ticker["lastPrice"]),
                    change_24h_pct=float(ticker["priceChangePercent"]),
                    quote_volume_24h=float(ticker["quoteVolume"]),
                    price_as_of=now,
                    btc_symbol=btc_symbols.get(base),
                )
            )
        return coins
    finally:
        if owns_client:
            await client.aclose()


class LiveUniverseCache:
    """Refreshes fetch_live_universe() at most once per ttl_seconds.

    A fresh pull touches two endpoints returning data for 1000+ symbols; the
    dashboard can poll every few seconds, so this cache exists to avoid
    hammering Binance's public API on every page refresh. It never returns
    fabricated data -- only ever the most recent real fetch, with its real
    timestamp attached to every row.
    """

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._coins: list[CoinPrice] = []
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> list[CoinPrice]:
        async with self._lock:
            if time.monotonic() - self._fetched_at > self.ttl_seconds:
                self._coins = await fetch_live_universe()
                self._fetched_at = time.monotonic()
            return self._coins


# Candle range presets: (Binance kline interval, number of candles). Chosen
# so each preset's candle count stays well under Binance's 1000-per-call
# limit (one request, no pagination) while giving a reasonable resolution
# for its span: hourly detail over a week, 4-hourly over a month, daily
# over a year.
CANDLE_RANGES = {
    "week": ("1h", 168),
    "month": ("4h", 180),
    "year": ("1d", 365),
}


@dataclass(frozen=True)
class Candle:
    open_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


async def fetch_candles(symbol: str, range_key: str, client: httpx.AsyncClient | None = None) -> list[Candle]:
    """Real historical OHLC candles for one symbol from Binance's public
    klines endpoint (no API key). range_key must be one of CANDLE_RANGES's
    keys ("week", "month", "year"). Raises ValueError for an unknown
    range_key rather than silently defaulting.
    """
    if range_key not in CANDLE_RANGES:
        raise ValueError(f"range_key must be one of {sorted(CANDLE_RANGES)}, got {range_key!r}")
    interval, limit = CANDLE_RANGES[range_key]

    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        response = await client.get(
            f"{MARKET_API}/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json()
    finally:
        if owns_client:
            await client.aclose()

    return [
        Candle(
            open_time=datetime.fromtimestamp(row[0] / 1000, UTC).isoformat(),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
    ]


def simple_moving_average(closes: list[float], window: int) -> list[float | None]:
    """SMA at each index, None where there isn't yet a full window of
    history -- never a guessed/partial average presented as the real thing.
    """
    out: list[float | None] = []
    for i in range(len(closes)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sum(closes[i + 1 - window : i + 1]) / window)
    return out
