from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from pumpradar.engine import Bar
from pumpradar.features import MIN_BASELINE_OBS, feature_columns

# robust_z's longest window (60 min) + embargo (60 min) + MIN_BASELINE_OBS is
# the real minimum history before the longest-window features stop being
# NaN -- MIN_BASELINE_OBS alone (600) is not enough, by 120 minutes.
MIN_REAL_HISTORY = MIN_BASELINE_OBS + 60 + 60 + 10  # +10 margin
from pumpradar.live_scoring import (
    CrossSectionalScoringEngine,
    backfill_engine,
    fetch_backfill_bars,
    load_frozen_bundle,
)


def _bar(symbol, minute, close=1.0, volume=10.0, taker_buy=5.0, count=50):
    return Bar(symbol=symbol, close_time=minute, close=close, volume_btc=volume, taker_buy_btc=taker_buy, trade_count=count)


def _toy_model_and_features():
    """A real (tiny, untrained-on-anything-meaningful) fitted estimator,
    just to exercise the engine's plumbing -- not a claim about real
    pump-detection performance.
    """
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, len(feature_columns())))
    y = rng.integers(0, 2, size=50)
    model = LogisticRegression().fit(X, y)
    return model, feature_columns()


def test_engine_reports_insufficient_history_before_enough_bars():
    model, cols = _toy_model_and_features()
    engine = CrossSectionalScoringEngine(model, cols, threshold=0.5)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(10):  # far fewer than MIN_BASELINE_OBS
        engine.ingest_bar(_bar("ABCBTC", base + timedelta(minutes=i)))

    scores = engine.score_latest()
    assert len(scores) == 1
    assert scores[0].scoring_status == "insufficient_history"
    assert scores[0].score is None


def test_engine_scores_once_enough_real_history_exists():
    model, cols = _toy_model_and_features()
    engine = CrossSectionalScoringEngine(model, cols, threshold=1e9)  # unreachable threshold -> no alerts
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(1)

    n_minutes = MIN_REAL_HISTORY
    for pair in ("ABCBTC", "XYZBTC"):
        for i in range(n_minutes):
            volume = max(rng.normal(10, 2), 0.1)
            engine.ingest_bar(_bar(
                pair, base + timedelta(minutes=i),
                close=1.0 + rng.normal(0, 0.01), volume=volume,
                taker_buy=volume * rng.uniform(0, 1), count=int(max(rng.normal(50, 10), 1)),
            ))

    scores = engine.score_latest()
    assert len(scores) == 2
    for s in scores:
        assert s.scoring_status == "scored"
        assert s.score is not None
        assert s.is_alert is False  # threshold unreachable


def test_engine_respects_cooldown_between_alerts():
    model, cols = _toy_model_and_features()
    engine = CrossSectionalScoringEngine(model, cols, threshold=-1e9, cooldown_minutes=30)  # always crosses
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(2)

    for i in range(MIN_REAL_HISTORY):
        volume = max(rng.normal(10, 2), 0.1)
        engine.ingest_bar(_bar("ABCBTC", base + timedelta(minutes=i), volume=volume, taker_buy=volume * 0.5))
    first = engine.score_latest()
    assert first[0].is_alert is True

    engine.ingest_bar(_bar("ABCBTC", base + timedelta(minutes=MIN_REAL_HISTORY), volume=10, taker_buy=5))
    second = engine.score_latest()
    assert second[0].is_alert is False  # within cooldown window, even though threshold still crossed

    assert len(engine.alerts) == 1


def test_ingest_bar_ignores_out_of_order_duplicates():
    model, cols = _toy_model_and_features()
    engine = CrossSectionalScoringEngine(model, cols, threshold=0.5)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    engine.ingest_bar(_bar("ABCBTC", base))
    engine.ingest_bar(_bar("ABCBTC", base))  # duplicate, same minute
    engine.ingest_bar(_bar("ABCBTC", base - timedelta(minutes=1)))  # out of order
    assert len(engine.history["ABCBTC"]) == 1


def test_load_frozen_bundle_raises_clear_error_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_frozen_bundle(
            model_path=tmp_path / "nope.joblib",
            features_path=tmp_path / "nope.json",
            threshold_path=tmp_path / "nope2.json",
        )


_ALIGNED_BASE_MS = 1700000000000 - (1700000000000 % 60000)  # round down to a real minute boundary
FAKE_KLINES = [
    [_ALIGNED_BASE_MS + i * 60000, "1.0", "1.0", "1.0", "1.0", "10.0",
     _ALIGNED_BASE_MS + i * 60000 + 59999, "10.0", 5, "5.0", "5.0", "0"]
    for i in range(50)
]


@pytest.mark.anyio
async def test_fetch_backfill_bars_parses_real_shaped_klines():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FAKE_KLINES)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bars = await fetch_backfill_bars("ABCBTC", 50, client)

    assert len(bars) == 50
    assert all(isinstance(b, Bar) for b in bars)
    assert bars[0].close_time < bars[-1].close_time  # sorted ascending


@pytest.mark.anyio
async def test_backfill_engine_populates_history(monkeypatch):
    async def fake_fetch(pair, minutes, client):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        return [_bar(pair, base + timedelta(minutes=i)) for i in range(minutes)]

    monkeypatch.setattr("pumpradar.live_scoring.fetch_backfill_bars", fake_fetch)
    model, cols = _toy_model_and_features()
    engine = CrossSectionalScoringEngine(model, cols, threshold=0.5, history_minutes=100)

    counts = await backfill_engine(engine, ["ABCBTC", "XYZBTC"])
    assert counts == {"ABCBTC": 100, "XYZBTC": 100}
    assert len(engine.history["ABCBTC"]) == 100


@pytest.fixture
def anyio_backend():
    return "asyncio"
