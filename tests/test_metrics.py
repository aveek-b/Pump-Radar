import numpy as np
import pandas as pd
import pytest

from pumpradar.metrics import (
    average_precision,
    classification_metrics,
    event_bootstrap,
    hit_at_k,
    inflation,
    threshold_at_budget,
)


def test_average_precision_perfect_ranking_is_one():
    y_true = [0, 0, 1, 1]
    y_score = [0.1, 0.2, 0.8, 0.9]
    assert average_precision(y_true, y_score) == pytest.approx(1.0)


def test_classification_metrics_basic_counts():
    y_true = [0, 0, 1, 1]
    y_pred = [0, 1, 1, 1]
    m = classification_metrics(y_true, y_pred)
    assert m["tp"] == 2 and m["fp"] == 1 and m["fn"] == 0 and m["tn"] == 1
    assert m["accuracy"] == pytest.approx(0.75)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(1.0)


def test_classification_metrics_undefined_precision_is_none_not_zero():
    y_true = [0, 0, 1, 1]
    y_pred = [0, 0, 0, 0]  # no predicted positives -> precision undefined
    m = classification_metrics(y_true, y_pred)
    assert m["precision"] is None
    assert m["recall"] == pytest.approx(0.0)


def test_inflation_is_p0_minus_p2():
    assert inflation(ap_p0=0.8, ap_honest=0.5) == pytest.approx(0.3)
    assert inflation(ap_p0=0.5, ap_honest=0.5) == pytest.approx(0.0)


def test_threshold_at_budget_rejects_nonpositive_n_coins():
    with pytest.raises(ValueError):
        threshold_at_budget([0.1, 0.2, 0.3], alerts_per_hour=2, n_coins=0)


def test_threshold_at_budget_is_a_quantile_of_negatives():
    neg_scores = np.arange(1000) / 1000.0
    threshold = threshold_at_budget(neg_scores, alerts_per_hour=60, n_coins=10)
    # alpha = 60 / (60*10) = 0.1 -> threshold should be ~90th percentile
    assert threshold == pytest.approx(0.9, abs=0.01)


def test_hit_at_k_counts_correct_rank():
    df = pd.DataFrame(
        {
            "event": ["e1", "e1", "e1", "e2", "e2"],
            "score": [0.9, 0.5, 0.1, 0.2, 0.8],
            "is_true": [1, 0, 0, 1, 0],
        }
    )
    # e1: true positive ranks 1st (hit@1). e2: true positive ranks 2nd (miss@1, hit@2).
    result_k1 = hit_at_k(df, group_key="event", score_col="score", true_col="is_true", k=1)
    assert result_k1["n_eligible"] == 2
    assert result_k1["hit_rate"] == pytest.approx(0.5)

    result_k2 = hit_at_k(df, group_key="event", score_col="score", true_col="is_true", k=2)
    assert result_k2["hit_rate"] == pytest.approx(1.0)


def test_hit_at_k_excludes_groups_without_exactly_one_positive():
    df = pd.DataFrame(
        {
            "event": ["e1", "e1", "e2", "e2"],
            "score": [0.9, 0.5, 0.2, 0.8],
            "is_true": [0, 0, 1, 1],  # e1 has zero positives, e2 has two
        }
    )
    result = hit_at_k(df, group_key="event", score_col="score", true_col="is_true", k=1)
    assert result["n_eligible"] == 0
    assert result["n_excluded"] == 2
    assert result["hit_rate"] is None


def test_event_bootstrap_returns_undefined_when_every_resample_lacks_positives():
    df = pd.DataFrame({"event": [1, 2, 3], "y": [0, 0, 0]})

    def metric_fn(resampled):
        if resampled["y"].sum() == 0:
            return None
        return float(resampled["y"].mean())

    result = event_bootstrap(df, group_col="event", metric_fn=metric_fn, n_repeats=50, seed=1)
    assert result["mean"] is None
    assert result["n_undefined"] == 50


def test_event_bootstrap_produces_a_reasonable_interval():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "event": np.repeat(np.arange(20), 10),
            "y": rng.integers(0, 2, size=200),
        }
    )

    def metric_fn(resampled):
        return float(resampled["y"].mean())

    result = event_bootstrap(df, group_col="event", metric_fn=metric_fn, n_repeats=200, seed=1)
    assert result["ci_low"] <= result["mean"] <= result["ci_high"]
    assert result["n_eligible_groups"] == 20
