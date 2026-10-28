import numpy as np
import pandas as pd

from pumpradar.exp_a import (
    CLEAN_FEATURE_COLUMNS,
    FULL_FEATURE_COLUMNS,
    HORIZONS_MIN,
    HYPERPARAM_GRIDS,
    _cap_for_distance_models,
    build_models,
    coin_identity_canary,
    prepare_experiment_a_dataset,
    run_experiment_a_sweep,
    tune_hyperparameters,
)


def _toy_raw() -> pd.DataFrame:
    """Synthetic chunk rows (not real Binance/Sapienza data) used only to
    test the label-construction logic in isolation. Real dataset counts are
    computed separately, directly from data/raw/sapienza/features_25S.csv.
    """
    base = pd.Timestamp("2020-01-01 00:00:00")
    rows = []

    # pump_index 1: onset at base + 10min. Three pre-onset rows at lead
    # 15, 8 and 2 minutes; the onset row itself; one post-onset row.
    for minutes_before_onset in (15, 8, 2):
        rows.append(
            {
                "pump_index": 1,
                "symbol": "AAABTC",
                "date": base + pd.Timedelta(minutes=10 - minutes_before_onset),
                "gt": 0,
            }
        )
    rows.append({"pump_index": 1, "symbol": "AAABTC", "date": base + pd.Timedelta(minutes=10), "gt": 1})
    rows.append({"pump_index": 1, "symbol": "AAABTC", "date": base + pd.Timedelta(minutes=12), "gt": 0})

    # pump_index 2: never has gt == 1 -- no onset can be determined, so the
    # whole group should be dropped rather than guessed at.
    rows.append({"pump_index": 2, "symbol": "BBBBTC", "date": base, "gt": 0})

    return pd.DataFrame(rows)


def test_drops_groups_with_no_onset():
    out = prepare_experiment_a_dataset(_toy_raw())
    assert 2 not in set(out["pump_index"])
    assert out.attrs["n_pump_groups_without_onset"] == 1
    assert out.attrs["n_rows_dropped_no_onset"] == 1


def test_keeps_only_strictly_pre_onset_rows_within_window():
    out = prepare_experiment_a_dataset(_toy_raw())
    # The onset row (lead_min == 0) and the post-onset row (lead_min < 0)
    # must both be excluded; only the three pre-onset rows remain.
    assert (out["lead_min"] > 0).all()
    assert len(out) == 3


def test_horizon_labels_match_lead_min():
    out = prepare_experiment_a_dataset(_toy_raw())
    for k in HORIZONS_MIN:
        expected = (out["lead_min"] <= k).astype(int)
        assert (out[f"y_{k}"] == expected).all()


def test_does_not_mutate_input():
    raw = _toy_raw()
    raw_copy = raw.copy(deep=True)
    prepare_experiment_a_dataset(raw)
    pd.testing.assert_frame_equal(raw, raw_copy)


def _synthetic_prepared(n_events=10, rows_per_event=30, seed=0) -> pd.DataFrame:
    """Small synthetic dataset shaped like prepare_experiment_a_dataset's
    output (pump_index, symbol, date, feature columns, y_<horizon> labels),
    used only to exercise the training pipeline quickly. Not real market or
    pump data -- real results come from run_experiment_a_sweep against the
    actual sapA.parquet, built from the verified Sapienza CSV.
    """
    rng = np.random.default_rng(seed)
    base = pd.Timestamp("2020-01-01")
    rows = []
    for event in range(n_events):
        event_start = base + pd.Timedelta(days=event * 5)
        for i in range(rows_per_event):
            rows.append(
                {
                    "pump_index": event,
                    "symbol": f"SYM{event % 4}",
                    "date": event_start + pd.Timedelta(minutes=i),
                    **{col: float(rng.normal()) for col in FULL_FEATURE_COLUMNS},
                }
            )
    df = pd.DataFrame(rows)
    df["lead_min"] = rows_per_event - df.groupby("pump_index").cumcount()
    for k in HORIZONS_MIN:
        df[f"y_{k}"] = (df["lead_min"] <= k).astype(int)
    return df


def test_cap_for_distance_models_respects_max_negatives():
    y = pd.Series([1] * 10 + [0] * 100)
    X = pd.DataFrame({"f": range(110)})
    capped_X, capped_y, info = _cap_for_distance_models(X, y, max_negatives=20, seed=0)
    assert info == {"n_positives": 10, "n_negatives_sampled": 20, "n_negatives_total": 100}
    assert len(capped_X) == len(capped_y) == 30
    assert capped_y.sum() == 10


def test_cap_for_distance_models_keeps_all_when_under_cap():
    y = pd.Series([1] * 5 + [0] * 5)
    X = pd.DataFrame({"f": range(10)})
    capped_X, _capped_y, info = _cap_for_distance_models(X, y, max_negatives=20, seed=0)
    assert info["n_negatives_sampled"] == 5
    assert len(capped_X) == 10


def test_run_experiment_a_sweep_covers_every_combination():
    df = _synthetic_prepared()
    records, predictions = run_experiment_a_sweep(df, horizons=(5, 10), seed=0)

    model_names = {"logreg", "knn", "decision_tree", "random_forest", "linear_svm", "lightgbm"}
    seen = {(r["feature_set"], r["protocol"], r["horizon_min"], r["model"]) for r in records}

    for feature_set in ("full", "clean"):
        for protocol in ("random_P0", "honest_P2"):
            for horizon in (5, 10):
                for model in model_names:
                    assert (feature_set, protocol, horizon, model) in seen

    for r in records:
        if r["model"] is not None:
            assert 0.0 <= r["ap"] <= 1.0
            assert r["fit_time_sec"] >= 0
            assert r["seed"] == 0

    assert set(predictions["model"].unique()) == model_names
    assert set(predictions["score"].apply(type)) <= {np.float64, float}


def test_run_experiment_a_sweep_feature_sets_use_the_right_columns():
    df = _synthetic_prepared()
    records, _ = run_experiment_a_sweep(
        df, horizons=(10,), feature_sets={"clean": list(CLEAN_FEATURE_COLUMNS)}, seed=0
    )
    assert all(r["feature_set"] == "clean" for r in records)


def test_build_models_applies_overrides():
    overridden = build_models(seed=0, overrides={"logreg": {"C": 10.0}, "knn": {"n_neighbors": 5}})
    assert overridden["logreg"].named_steps["logisticregression"].C == 10.0
    assert overridden["knn"].named_steps["kneighborsclassifier"].n_neighbors == 5

    default = build_models(seed=0)
    assert default["logreg"].named_steps["logisticregression"].C == 1.0


def test_tune_hyperparameters_picks_a_value_from_each_grid():
    df = _synthetic_prepared(n_events=30, rows_per_event=30, seed=1)
    result = tune_hyperparameters(df, CLEAN_FEATURE_COLUMNS, horizon=10, seed=0)

    for model_name, grid in HYPERPARAM_GRIDS.items():
        for param, values in grid.items():
            assert result["chosen"][model_name][param] in values
            assert set(result["trials"][model_name][param].keys()) == set(values)

    assert result["horizon_min"] == 10
    assert result["n_train_events"] > 0
    assert result["n_val_events"] > 0


def test_run_experiment_a_sweep_accepts_tuned_overrides():
    df = _synthetic_prepared(n_events=30, rows_per_event=30, seed=1)
    tuned = tune_hyperparameters(df, CLEAN_FEATURE_COLUMNS, horizon=10, seed=0)
    records, _ = run_experiment_a_sweep(
        df, horizons=(10,), feature_sets={"clean": list(CLEAN_FEATURE_COLUMNS)},
        seed=0, model_overrides=tuned["chosen"],
    )
    assert len(records) == 12  # 6 models x 2 protocols, single horizon/feature_set
    for r in records:
        assert r["ap"] is not None


def test_coin_identity_canary_returns_lift_for_both_protocols():
    df = _synthetic_prepared()
    result = coin_identity_canary(df, horizon=10, seed=0)
    assert "identity_lift_P0" in result
    assert "identity_lift_P2" in result
    assert result["horizon_min"] == 10
    for key in (
        "random_P0_clean", "random_P0_clean_plus_identity",
        "honest_P2_clean", "honest_P2_clean_plus_identity",
    ):
        assert 0.0 <= result[key] <= 1.0
