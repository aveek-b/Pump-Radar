"""Deterministic UI fixtures, independent of Hannah's research/scoring engine."""

import math
import random
import time
from datetime import UTC, datetime, timedelta

from api.schemas import (
    Candle,
    CoinResponse,
    CoinRisk,
    Driver,
    Market,
    PricesEvent,
    RadarTick,
    ReplayDetailResponse,
    ReplayEvent,
    RiskAlert,
    RiskPoint,
)

START = datetime(2026, 10, 26, tzinfo=UTC)
HORIZONS = ("1", "3", "5", "10", "30", "60")
PAIRS = tuple(f"MOCK{i:03}BTC" for i in range(1, 61))
NOTICE = "MOCK DATA: synthetic fixtures, not trained predictions or measured results."
PROVENANCE = {"scorer": "mock", "mock": True, "notice": NOTICE}


class MockData:
    def __init__(self):
        self.started = time.monotonic()

    def price_sequence(self) -> int:
        return max(0, int((time.monotonic() - self.started) // 2))

    def score_sequence(self) -> int:
        return self.price_sequence() // 5

    def markets(self, sequence: int) -> list[Market]:
        rng = random.Random(42 + sequence)
        return [Market(
            symbol=pair, price=round((i + 1) * 0.00001 * (1 + rng.uniform(-.01, .01)), 10),
            change_24h_pct=round(rng.uniform(-8, 8), 2),
            volume_24h_quote=round(10 + rng.random() * 100, 2),
            quote_asset="BTC" if i < 60 else "USDT", scored=i < 60,
        ) for i, pair in enumerate((*PAIRS, "MOCK061USDT"))]

    def prices(self, sequence: int) -> PricesEvent:
        return PricesEvent(**PROVENANCE, sequence=sequence,
                           as_of=START + timedelta(seconds=sequence * 2),
                           markets=self.markets(sequence))

    def tick(self, sequence: int) -> RadarTick:
        rng = random.Random(42 + sequence)
        timestamp = START + timedelta(seconds=sequence * 10)
        rows = []
        alerts = []
        for i, pair in enumerate(PAIRS):
            # One visibly synthetic alert per frame exercises the transport, not B3 policy.
            base = .9 if i == sequence % len(PAIRS) else rng.uniform(.02, .7)
            risks = {h: round(min(.99, base * (.6 + j * .1)), 4)
                     for j, h in enumerate(HORIZONS)}
            alert = None
            if risks["10"] >= .8:
                alert = RiskAlert(id=f"mock-{sequence}-{pair}", pair=pair, time=timestamp,
                                  horizon="10", risk=risks["10"], mock=True,
                                  reasons=["Synthetic alert fixture; no model inference."])
                alerts.append(alert)
            rows.append(CoinRisk(
                pair=pair, tier=("low", "medium", "high")[i % 3], risk=risks,
                level="Alert" if alert else "Watch" if risks["10"] >= .4 else "Normal",
                alert=alert, sparkline=[round(rng.uniform(.02, .7), 4) for _ in range(12)],
            ))
        rows.sort(key=lambda row: (-row.risk["10"], row.pair))
        return RadarTick(**PROVENANCE, sequence=sequence, as_of=timestamp,
                         rows=rows, newAlerts=alerts)

    def candles(self, pair: str, sequence: int) -> list[Candle]:
        index = PAIRS.index(pair)
        price = (index + 1) * .00001
        end = (START + timedelta(seconds=sequence * 10)).replace(second=0)
        bars = []
        for i in range(360):
            minute = end - timedelta(minutes=359 - i)
            phase = (minute - START).total_seconds() / 60
            opening = price * (1 + .02 * math.sin((phase - 1) / 12))
            close = price * (1 + .02 * math.sin(phase / 12))
            bars.append(Candle(time=minute, open=opening,
                               high=max(opening, close) * 1.003,
                               low=min(opening, close) * .997, close=close,
                               volume_quote=10 + i % 7))
        return bars

    def coin(self, pair: str, sequence: int, price_sequence: int) -> CoinResponse:
        tick = self.tick(sequence)
        row = next(row for row in tick.rows if row.pair == pair)
        history = []
        for i in range(359, 0, -1):
            timestamp = tick.as_of.replace(second=0) - timedelta(minutes=i)
            rng = random.Random(42 + PAIRS.index(pair) + int(timestamp.timestamp()))
            base = rng.uniform(.02, .7)
            history.append(RiskPoint(time=timestamp, risk={
                h: round(min(.99, base * (.6 + j * .1)), 4)
                for j, h in enumerate(HORIZONS)
            }))
        history.append(RiskPoint(time=tick.as_of, risk=row.risk))
        return CoinResponse(
            **PROVENANCE, pair=pair,
            market=next(m for m in self.markets(price_sequence) if m.symbol == pair),
            current=row, bars=self.candles(pair, sequence),
            risk_series=history,
            alerts=[row.alert] if row.alert else [],
            drivers=[Driver(label=f"Mock driver {i + 1} (synthetic, not a feature)",
                            value=round(.5 - i * .08, 2)) for i in range(5)],
        )

    def replay_event(self) -> ReplayEvent:
        return ReplayEvent(event_id="mock-example", pair=PAIRS[0],
                           t_onset=START + timedelta(minutes=1), t_telegram=None,
                           era="mock", first_alert_lead_minutes=None, rank_at_onset=None)

    def replay(self) -> ReplayDetailResponse:
        return ReplayDetailResponse(**PROVENANCE, event=self.replay_event(),
                                    frames=[self.tick(i) for i in range(12)],
                                    bars=self.candles(PAIRS[0], 11))


mock_data = MockData()
