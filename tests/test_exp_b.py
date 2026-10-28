import numpy as np
import pandas as pd
import pytest

from pumpradar.exp_a import HYPERPARAM_GRIDS
from pumpradar.exp_b import (
    add_horizon_labels,
    assert_no_pair_minute_leak,
    feature_columns_in,
    hit_at_k_snapshot,
    load_xsec,
    run_experiment_b_sweep,
    select_deployment_candidate,
    split_b,
    tune_hyperparameters_b,
)


def _synthetic_xsec(n_events=20, n_pairs=6, window=120, seed=0) -> pd.DataFrame:
    """Synthetic cross-sectional dataset shaped like features.build_xsec_sample's
    real output: one row per (event_id, pair, minute), lead_min populated only
    for the event's own pumped pair. Not real market data -- real Experiment B
    results come from the actual data/processed/xsec.parquet.
    """
    rng = np.random.default_rng(seed)
    base = pd.Timestamp("2018-06-01", tz="UTC")
    rows = []
    for e in range(n_events):
        onset = base + pd.Timedelta(days=e * 20)
        era = "train" if e < int(n_events * 0.7) else "test"
        pumped_pair = f"PAIR{e % n_pairs}"
        for m in range(1, window + 1):
            minute = onset - pd.Timedelta(minutes=m)
            for p in range(n_pairs):
                pair = f"PAIR{p}"
                is_pumped = pair == pumped_pair
                rows.append({
                    "event_id": f"event_{e:04d}",
                    "pair": pair,
                    "minute": minute,
                    "era": era,
                    "lead_min": float(m) if is_pumped else np.nan,
                    "feat_a": rng.normal(2.0 if is_pumped and m <= 10 else 0.0, 1.0),
                    "feat_b": rng.normal(0.0, 1.0),
                })
    return pd.DataFrame(rows)


def test_feature_columns_in_excludes_metadata():
    xsec = _synthetic_xsec(n_events=2)
    cols = feature_columns_in(xsec)
    assert set(cols) == {"feat_a", "feat_b"}


def test_add_horizon_labels_only_flags_the_pumped_pair_within_window():
    xsec = _synthetic_xsec(n_events=2)
    labeled = add_horizon_labels(xsec, horizons=(5, 10))
    for k in (5, 10):
        y = labeled[f"y_{k}"]
        expected = labeled["lead_min"].notna() & (labeled["lead_min"] <= k)
        assert (y == expected.astype(int)).all()
    # non-pumped rows are never positive
    assert labeled.loc[labeled["lead_min"].isna(), "y_5"].eq(0).all()


def test_split_b_respects_era_and_has_no_leaks():
    xsec = _synthetic_xsec(n_events=20)
    train_idx, val_idx, test_idx = split_b(xsec, val_frac_of_train=0.2, purge="0h")

    assert set(xsec.loc[test_idx, "era"]) <= {"test"}
    assert set(xsec.loc[train_idx, "era"]) <= {"train"}
    assert set(xsec.loc[val_idx, "era"]) <= {"train"}

    all_idx = set(train_idx) | set(val_idx) | set(test_idx)
    assert all_idx <= set(xsec.index)

    train_events = set(xsec.loc[train_idx, "event_id"])
    val_events = set(xsec.loc[val_idx, "event_id"])
    test_events = set(xsec.loc[test_idx, "event_id"])
    assert not (train_events & val_events)
    assert not (train_events & test_events)
    assert not (val_events & test_events)


def test_assert_no_pair_minute_leak_catches_a_real_leak():
    xsec = _synthetic_xsec(n_events=2)
    bad_train = xsec.index[:50]
    bad_test = xsec.index[:50]  # identical rows on both sides -- a deliberate leak
    with pytest.raises(AssertionError):
        assert_no_pair_minute_leak(xsec, bad_train, bad_test)


def test_load_xsec_rejects_missing_columns(tmp_path):
    bad = pd.DataFrame({"event_id": [1], "pair": ["A"]})
    path = tmp_path / "bad.parquet"
    bad.to_parquet(path)
    with pytest.raises(ValueError):
        load_xsec(str(path))


def test_run_experiment_b_sweep_produces_ap_for_every_model_and_horizon():
    xsec = _synthetic_xsec(n_events=30, n_pairs=5)
    records, predictions = run_experiment_b_sweep(xsec, horizons=(5, 10), seed=0, purge="0h")

    model_names = {"logreg", "knn", "decision_tree", "random_forest", "linear_svm", "lightgbm"}
    seen = {(r["horizon_min"], r["model"]) for r in records}
    for horizon in (5, 10):
        for model in model_names:
            assert (horizon, model) in seen

    for r in records:
        if r["model"] is not None:
            assert 0.0 <= r["ap"] <= 1.0

    assert set(predictions["model"].unique()) == model_names
    assert "lead_min" in predictions.columns


def test_hit_at_k_snapshot_finds_the_true_pump_at_the_right_minute():
    xsec = _synthetic_xsec(n_events=30, n_pairs=5)
    _records, predictions = run_experiment_b_sweep(xsec, horizons=(10,), seed=0, purge="0h")

    result = hit_at_k_snapshot(predictions, horizon=10, k=1, model="random_forest")
    assert result["n_eligible"] > 0
    assert 0.0 <= result["hit_rate"] <= 1.0
    assert result["k"] == 1
    assert result["horizon_min"] == 10


def test_hit_at_k_snapshot_excludes_events_with_no_matching_minute():
    predictions = pd.DataFrame({
        "run_id": ["r"] * 3, "model": ["m"] * 3, "horizon_min": [10, 10, 10],
        "event_id": ["e1", "e1", "e2"], "pair": ["A", "B", "C"],
        "minute": pd.to_datetime(["2020-01-01", "2020-01-01", "2020-01-01"], utc=True),
        "lead_min": [np.nan, np.nan, np.nan],  # no row anywhere matches lead_min==10
        "y_true": [0, 0, 0], "score": [0.5, 0.3, 0.1],
    })
    result = hit_at_k_snapshot(predictions, horizon=10, k=1, model="m")
    assert result["hit_rate"] is None
    assert result["n_eligible"] == 0
    assert result["n_excluded"] == 2


def test_tune_hyperparameters_b_picks_a_combo_from_each_grid():
    xsec = _synthetic_xsec(n_events=40, n_pairs=5)
    result = tune_hyperparameters_b(xsec, horizon=10, seed=0, purge="0h")

    for model_name, grid in HYPERPARAM_GRIDS.items():
        n_combos = 1
        for values in grid.values():
            n_combos *= len(values)
        assert len(result["trials"][model_name]) == n_combos
        for param, values in grid.items():
            assert result["chosen"][model_name][param] in values

    assert result["horizon_min"] == 10
    assert result["n_train_events"] > 0
    assert result["n_val_events"] > 0


def test_select_deployment_candidate_uses_validation_not_test():
    xsec = _synthetic_xsec(n_events=40, n_pairs=5)
    result = select_deployment_candidate(xsec, model_overrides=None, horizon=10, seed=0, purge="0h")

    assert result["deployment_candidate"] in result["val_ap_by_model"]
    assert len(result["val_ap_by_model"]) == 6
    best_ap = result["val_ap_by_model"][result["deployment_candidate"]]
    assert best_ap == max(result["val_ap_by_model"].values())
