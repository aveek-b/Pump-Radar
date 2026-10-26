from pumpradar.storage import AlertStore


def test_alerts_persist_and_retries_do_not_duplicate(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    first = AlertStore(path)
    alert = {"symbol": "FOOBTC", "close_time": "2020-01-01T00:05:00+00:00", "score": 0.9}
    assert first.add(alert)
    assert not first.add(alert)
    assert AlertStore(path).recent() == [dict(alert, status="demo_stub")]
