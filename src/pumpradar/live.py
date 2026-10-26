"""Binance public market-data feeder. Run separately from the API process."""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime, timedelta

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from pumpradar.engine import Bar

LOG = logging.getLogger(__name__)
MARKET_API = "https://data-api.binance.vision/api/v3"
MARKET_STREAM = "wss://data-stream.binance.vision:443/stream?streams="


def parse_closed_kline(message: dict) -> Bar | None:
    """Map a closed UTC 1m Binance kline to the exact API bar contract."""
    data = message.get("data", message)
    if data.get("e") != "kline" or not isinstance(data.get("k"), dict):
        return None
    k = data["k"]
    if k.get("i") != "1m" or k.get("x") is not True:
        return None
    start = datetime.fromtimestamp(int(k["t"]) / 1000, UTC)
    if start.second or start.microsecond:
        raise ValueError("non-minute Binance kline start")
    return Bar(
        symbol=str(data["s"]).upper(),
        close_time=start + timedelta(minutes=1),
        close=float(k["c"]),
        volume_btc=float(k["q"]),
        taker_buy_btc=float(k["Q"]),
        trade_count=int(k["n"]),
    )


def bar_payload(bar: Bar) -> dict:
    return {
        "symbol": bar.symbol,
        "close_time": bar.close_time.isoformat(),
        "close": bar.close,
        "volume_btc": bar.volume_btc,
        "taker_buy_btc": bar.taker_buy_btc,
        "trade_count": bar.trade_count,
    }


class MinuteBatcher:
    """One minute at a time; late or duplicate data cannot rewrite a published batch."""

    def __init__(self, symbols: set[str]) -> None:
        self.symbols = symbols
        self.pending: dict[datetime, dict[str, Bar]] = {}
        self.first_seen: dict[datetime, float] = {}
        self.last_flushed: datetime | None = None

    def add(self, bar: Bar, now: float) -> bool:
        if bar.symbol not in self.symbols or (
            self.last_flushed is not None and bar.close_time <= self.last_flushed
        ):
            return False
        self.pending.setdefault(bar.close_time, {})[bar.symbol] = bar
        self.first_seen.setdefault(bar.close_time, now)
        return True

    def ready(self, now: float, delay_seconds: float = 3.0) -> tuple[datetime, list[Bar]] | None:
        for minute in sorted(self.pending):
            if len(self.pending[minute]) < len(self.symbols) and now - self.first_seen[minute] < delay_seconds:
                return None
            batch = [self.pending[minute][s] for s in sorted(self.pending[minute])]
            return minute, batch
        return None

    def acknowledge(self, minute: datetime) -> None:
        """Remove only after the API confirms success."""
        del self.pending[minute]
        del self.first_seen[minute]
        self.last_flushed = minute

    def missing(self, bars: list[Bar]) -> list[str]:
        return sorted(self.symbols - {bar.symbol for bar in bars})


async def discover_symbols(client: httpx.AsyncClient) -> list[str]:
    response = await client.get(f"{MARKET_API}/exchangeInfo", timeout=20)
    response.raise_for_status()
    return sorted(
        row["symbol"] for row in response.json()["symbols"]
        if row.get("quoteAsset") == "BTC" and row.get("status") == "TRADING"
        and row.get("isSpotTradingAllowed", True)
    )


async def post_batch(client: httpx.AsyncClient, api_url: str, bars: list[Bar]) -> None:
    response = await client.post(
        f"{api_url.rstrip('/')}/batches", json={"bars": [bar_payload(b) for b in bars]}, timeout=20
    )
    response.raise_for_status()
    returned = response.json()
    if returned["minute"] != bars[0].close_time.isoformat() or (
        {row["symbol"] for row in returned["coins"]} != {bar.symbol for bar in bars}
    ):
        raise ValueError("API did not acknowledge every submitted coin")
    LOG.info("scored %d bars through %s", len(bars), response.json()["minute"])


async def warmup(client: httpx.AsyncClient, api_url: str, symbols: list[str]) -> None:
    """Use at most five completed recent candles per symbol; older history is future work."""
    async def one(symbol: str) -> None:
        try:
            response = await client.get(
                f"{MARKET_API}/klines", params={"symbol": symbol, "interval": "1m", "limit": 7},
                timeout=20,
            )
            response.raise_for_status()
            current_ms = int(datetime.now(UTC).timestamp() * 1000)
            rows = [r for r in response.json() if int(r[6]) < current_ms][-5:]
            for row in rows:
                bar = Bar(
                    symbol=symbol,
                    close_time=datetime.fromtimestamp(int(row[0]) / 1000, UTC) + timedelta(minutes=1),
                    close=float(row[4]), volume_btc=float(row[7]),
                    taker_buy_btc=float(row[10]), trade_count=int(row[8]),
                )
                response = await client.post(f"{api_url.rstrip('/')}/bars", json=bar_payload(bar), timeout=20)
                # A running API may have these bars already; duplicate is harmless here.
                if response.status_code != 422:
                    response.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            LOG.warning("warmup failed for %s: %s", symbol, exc)

    semaphore = asyncio.Semaphore(5)

    async def limited(symbol: str) -> None:
        async with semaphore:
            await one(symbol)

    await asyncio.gather(*(limited(symbol) for symbol in symbols))


async def run(
    symbols: list[str] | None, api_url: str, do_warmup: bool = True,
    verify_minutes: int = 0, verify_timeout: float = 300,
) -> bool | None:
    async with httpx.AsyncClient() as client:
        if symbols is None:
            symbols = await discover_symbols(client)
        if not symbols:
            raise ValueError("no BTC spot symbols selected")
        LOG.info("tracking %d BTC pairs", len(symbols))
        if do_warmup:
            await warmup(client, api_url, symbols)
        batcher = MinuteBatcher(set(symbols))
        streams = "/".join(f"{s.lower()}@kline_1m" for s in symbols)
        backoff = 1
        checked: list[tuple[datetime, list[str]]] = []
        deadline = asyncio.get_running_loop().time() + verify_timeout
        while True:
            if verify_minutes and asyncio.get_running_loop().time() >= deadline:
                LOG.error("verification timed out: %d/%d completed minutes", len(checked), verify_minutes)
                return False
            try:
                async with connect(MARKET_STREAM + streams, max_size=2**22) as ws:
                    LOG.info("connected to public market stream")
                    backoff = 1
                    while True:
                        if verify_minutes and asyncio.get_running_loop().time() >= deadline:
                            LOG.error("verification timed out: %d/%d completed minutes", len(checked), verify_minutes)
                            return False
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            bar = parse_closed_kline(json.loads(raw))
                            if bar:
                                batcher.add(bar, asyncio.get_running_loop().time())
                        except TimeoutError:
                            pass
                        while pending := batcher.ready(asyncio.get_running_loop().time()):
                            minute, batch = pending
                            await post_batch(client, api_url, batch)
                            missing = batcher.missing(batch)
                            LOG.info(
                                "coverage %s: %d/%d pairs; missing: %s", minute.isoformat(),
                                len(batch), len(batcher.symbols), ",".join(missing) if missing else "none",
                            )
                            batcher.acknowledge(minute)
                            if verify_minutes:
                                checked.append((minute, missing))
                                if len(checked) == verify_minutes:
                                    complete = sum(not missed for _, missed in checked)
                                    LOG.info(
                                        "verification: %d/%d minutes had every pair; %d expected pairs",
                                        complete, verify_minutes, len(symbols),
                                    )
                                    return complete == verify_minutes
            except (OSError, WebSocketException, httpx.HTTPError, ValueError) as exc:
                LOG.warning("feed interrupted: %s; reconnecting in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed closed Binance BTC-pair candles to local API")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--symbols", help="comma-separated BTC pairs, e.g. ETHBTC,BNBBTC")
    choice.add_argument("--all-btc", action="store_true", help="discover all trading BTC spot pairs")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--verify-minutes", type=int, default=0,
                        help="exit successfully only if all pairs arrive in each of N minutes")
    parser.add_argument("--verify-timeout", type=float, default=300,
                        help="maximum seconds after warmup to wait for verification")
    args = parser.parse_args()
    if args.verify_minutes < 0 or (args.verify_minutes and args.verify_timeout <= 0):
        parser.error("verification requires positive minutes and timeout")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    selected = None if args.all_btc else sorted({s.strip().upper() for s in args.symbols.split(",")})
    result = asyncio.run(run(
        selected, args.api_url, not args.no_warmup, args.verify_minutes, args.verify_timeout
    ))
    if result is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
