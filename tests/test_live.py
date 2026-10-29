import asyncio
import json
from datetime import UTC, datetime, timedelta

from pumpradar import live
from pumpradar.live import MinuteBatcher, parse_closed_kline


def message(symbol="FOOBTC", closed=True):
    return {
        "stream": f"{symbol.lower()}@kline_1m",
        "data": {
            "e": "kline", "s": symbol,
            "k": {
                "t": 1577836800000, "T": 1577836859999, "i": "1m", "x": closed,
                "c": "0.001", "q": "12.5", "Q": "8.25", "n": 17,
            },
        },
    }


def test_only_closed_kline_and_quote_volume_are_scored():
    assert parse_closed_kline(message(closed=False)) is None
    bar = parse_closed_kline(message())
    assert bar.close_time == datetime(2020, 1, 1, 0, 1, tzinfo=UTC)
    assert (bar.volume_btc, bar.taker_buy_btc, bar.trade_count) == (12.5, 8.25, 17)


def test_batch_waits_for_peers_or_timeout_and_keeps_unacknowledged_data():
    batcher = MinuteBatcher({"FOOBTC", "BARBTC"})
    first = parse_closed_kline(message())
    assert batcher.add(first, now=0)
    assert batcher.ready(now=2.9) is None
    pending = batcher.ready(now=3)
    assert pending == (first.close_time, [first])
    assert batcher.missing(pending[1]) == ["BARBTC"]
    # A failed post leaves the same minute available for retry.
    assert batcher.ready(now=4) == pending
    batcher.acknowledge(first.close_time)
    assert not batcher.add(first, now=5)
    second = parse_closed_kline(message("BARBTC"))
    later = type(second)(
        second.symbol, second.close_time + timedelta(minutes=1), second.close,
        second.volume_btc, second.taker_buy_btc, second.trade_count,
    )
    assert batcher.add(later, now=5)
    assert batcher.ready(now=6) is None


def test_verification_requires_api_ack_for_every_pair(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"minute": "2020-01-01T00:01:00Z", "coins": [
                {"symbol": "BARBTC"}, {"symbol": "FOOBTC"}
            ]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    class WebSocket:
        def __init__(self):
            self.messages = [json.dumps(message("FOOBTC")), json.dumps(message("BARBTC"))]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def recv(self):
            return self.messages.pop(0)

    monkeypatch.setattr(live.httpx, "AsyncClient", Client)
    monkeypatch.setattr(live, "connect", lambda *args, **kwargs: WebSocket())
    assert asyncio.run(live.run(
        ["BARBTC", "FOOBTC"], "http://127.0.0.1:8000", do_warmup=False,
        verify_minutes=1, verify_timeout=10,
    )) is True
