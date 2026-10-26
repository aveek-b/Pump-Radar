"""Shared live/replay state machine. The scorer is a DEMO STUB, not a trained model."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite


@dataclass(frozen=True)
class Bar:
    symbol: str
    close_time: datetime
    close: float
    volume_btc: float
    taker_buy_btc: float
    trade_count: int

    def __post_init__(self) -> None:
        if self.close_time.tzinfo is None or self.close_time.utcoffset() != UTC.utcoffset(None):
            raise ValueError("close_time must include a UTC offset")
        if self.close_time.second or self.close_time.microsecond:
            raise ValueError("close_time must be on a minute boundary")
        if not self.symbol.endswith("BTC") or len(self.symbol) <= 3:
            raise ValueError("symbol must be a BTC spot pair")
        if not all(isfinite(v) and v >= 0 for v in (self.close, self.volume_btc, self.taker_buy_btc)):
            raise ValueError("price and volumes must be finite and nonnegative")
        if self.close == 0 or self.taker_buy_btc > self.volume_btc or self.trade_count < 0:
            raise ValueError("invalid bar values")


class Radar:
    def __init__(self, threshold: float = 0.8, history_size: int = 1440) -> None:
        if not 0 <= threshold <= 1 or history_size < 5:
            raise ValueError("invalid radar configuration")
        self.threshold = threshold
        self.history = defaultdict(lambda: deque(maxlen=history_size))
        self.latest: dict[str, dict] = {}
        self.alerts: list[dict] = []

    def ingest(self, bar: Bar) -> dict:
        prior = self.history[bar.symbol]
        if prior and bar.close_time <= prior[-1].close_time:
            raise ValueError("bars for each symbol must arrive in increasing time order")

        # This deliberately uses only CLOSED bars strictly before the decision bar.
        baseline = [b.volume_btc for b in prior if b.close_time < bar.close_time]
        relative_volume = None
        buy_share = bar.taker_buy_btc / max(bar.volume_btc, 1e-9)
        if len(baseline) < 5:
            score = None
        else:
            baseline.sort()
            median = baseline[len(baseline) // 2]
            relative_volume = bar.volume_btc / max(median, 1e-9)
            # Demo heuristic only. No probability interpretation or false-alarm guarantee.
            score = min(1.0, max(0.0, (relative_volume - 1) / 9)) * buy_share

        result = {
            "symbol": bar.symbol,
            "close_time": bar.close_time.isoformat(),
            "score": score,
            "relative_volume": relative_volume,
            "buy_share": buy_share,
            "status": "warming_up" if score is None else "demo_stub",
        }
        prior.append(bar)
        self.latest[bar.symbol] = result
        if score is not None and score >= self.threshold:
            self.alerts.append(result.copy())
        return result

    def ranking(self) -> list[dict]:
        """Current minute only; older last-known scores are stale, not peers."""
        if not self.latest:
            return []
        minute = max(row["close_time"] for row in self.latest.values())
        return sorted(
            (row for row in self.latest.values() if row["close_time"] == minute),
            key=lambda row: (row["score"] is None, -(row["score"] or 0), row["symbol"]),
        )

