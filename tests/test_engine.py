from datetime import UTC, datetime, timedelta

import pytest

from pumpradar.engine import Bar, Radar

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def bar(minute: int, volume: float = 1, symbol: str = "FOOBTC") -> Bar:
    return Bar(symbol, T0 + timedelta(minutes=minute), 1, volume, volume * 0.9, 10)


def test_alert_uses_only_history_available_at_decision_time():
    normal = Radar()
    for minute in range(5):
        assert normal.ingest(bar(minute))["score"] is None
    result = normal.ingest(bar(5, 100))
    assert result["score"] == 0.9
    assert result["relative_volume"] == 100
    assert result["buy_share"] == 0.9
    assert len(normal.alerts) == 1

    # Appending future data cannot change an earlier decision.
    normal.ingest(bar(6, 100000))
    assert normal.alerts[0] == result


def test_rejects_duplicate_or_out_of_order_bars():
    radar = Radar()
    radar.ingest(bar(0))
    with pytest.raises(ValueError, match="increasing"):
        radar.ingest(bar(0))


def test_replay_is_deterministic_and_separate():
    sequence = [bar(i) for i in range(5)] + [bar(5, 100)]
    a, b = Radar(), Radar()
    assert [a.ingest(row) for row in sequence] == [b.ingest(row) for row in sequence]
    assert len(a.alerts) == len(b.alerts) == 1


def test_ranking_excludes_stale_coin_minutes():
    radar = Radar()
    radar.ingest(bar(0, symbol="FOOBTC"))
    radar.ingest(bar(1, symbol="BARBTC"))
    assert [row["symbol"] for row in radar.ranking()] == ["BARBTC"]


def test_ordinary_volume_yields_zero_demo_score():
    radar = Radar()
    for minute in range(5):
        radar.ingest(bar(minute))
    assert radar.ingest(bar(5, 1))["score"] == 0

