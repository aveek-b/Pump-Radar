"""Experiment B: cross-sectional "which coin, how early" scoring.

Unlike Experiment A (single-coin chunk features, audits a split protocol),
Experiment B asks the deployment question directly: at a given minute,
ranked against every other live coin, does the model put the pumped coin
near the top? Uses the real cross-sectional dataset built by
features.build_xsec_sample (data/processed/xsec.parquet): one row per
(event_id, pair, minute), with lead_min populated only for the event's own
pumped pair.

Train-era/test-era split (build guide B): events before 2020-01-01 are
train-era, 2020+ is test-era, assigned by Hannah's prepare_events.py and
carried in xsec.parquet's own `era` column. Verified empirically (not
assumed) that zero (pair, minute) keys are shared between eras -- see
assert_no_pair_minute_leak. Within train-era, the latest 20% of events
(chronologically) are reserved for validation/threshold tuning, using the
same event-grouped, embargo-purged logic as Experiment A's split_honest.
"""
from __future__ import annotations

import itertools
import time

import pandas as pd

from pumpradar import metrics
from pumpradar.exp_a import HYPERPARAM_GRIDS, _cap_for_distance_models, _get_scores, build_models
from pumpradar.splits import assert_no_group_leak, split_honest

XSEC_PATH = "data/processed/xsec.parquet"
HORIZONS_MIN = (1, 3, 5, 10, 30, 60)

METADATA_COLUMNS = {"event_id", "pair", "minute", "era", "lead_min"}

# Unlike Experiment A, the build guide explicitly permits sampling TRAINING
# negatives for Experiment B ("use all eligible test coins at each minute,
# even if training negatives are sampled"). The cross-sectional row count
# (84 coins x 120 minutes/event) makes training every model on the full set
# impractically slow (Random Forest alone: ~130s/fit on 588K rows) for a
# gain a capped sample already captures. The test set is never sampled --
# every eligible coin at every test-era minute is scored, unchanged.
MAX_TRAIN_NEGATIVES = 20_000


def load_xsec(path: str = XSEC_PATH) -> pd.DataFrame:
    df = pd.read_parquet(path)
    required = METADATA_COLUMNS
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"xsec data is missing required columns: {sorted(missing)}")
    return df


def feature_columns_in(xsec: pd.DataFrame) -> list[str]:
    """Every column that isn't metadata/label is a model feature -- kept
    dynamic rather than hardcoded so this module doesn't silently drift
    from whatever features.feature_columns() actually produces.
    """
    return [c for c in xsec.columns if c not in METADATA_COLUMNS]


def add_horizon_labels(xsec: pd.DataFrame, horizons=HORIZONS_MIN) -> pd.DataFrame:
    """y_k = 1 only for the event's own pumped pair, within k minutes of its
    onset; 0 for every other row (other coins at that minute, and the
    pumped pair itself outside the k-minute window). Does not mutate input.
    """
    out = xsec.copy()
    for k in horizons:
        out[f"y_{k}"] = (out["lead_min"].notna() & (out["lead_min"] <= k)).astype(int)
    return out


def assert_no_pair_minute_leak(xsec: pd.DataFrame, train_idx: pd.Index, test_idx: pd.Index) -> None:
    """The guide's cross-sectional-specific leakage check: the same
    (pair, minute) key must never appear on both sides, even via two
    different event_ids' overlapping windows. Checked empirically, not
    assumed -- see the module docstring for the real result on this dataset.
    """
    train_keys = set(zip(xsec.loc[train_idx, "pair"], xsec.loc[train_idx, "minute"]))
    test_keys = set(zip(xsec.loc[test_idx, "pair"], xsec.loc[test_idx, "minute"]))
    overlap = train_keys & test_keys
    if overlap:
        sample = sorted(overlap)[:5]
        raise AssertionError(
            f"{len(overlap)} (pair, minute) key(s) leaked across train/test "
            f"(e.g. {sample}) -- connected-component grouping of overlapping "
            f"event windows is required before this split can be trusted"
        )


def split_b(
    xsec: pd.DataFrame,
    val_frac_of_train: float = 0.2,
    purge: str = "24h",
) -> tuple[pd.Index, pd.Index, pd.Index]:
    """Train / validation / test split for Experiment B.

    Test = xsec's own era == "test" (2020+, untouched). Train-era rows are
    split again, event-grouped and chronologically embargoed (same
    machinery as Experiment A's split_honest), into train (earliest ~80%
    of train-era events) and validation (latest ~20%) -- validation exists
    so hyperparameter/threshold selection never touches the real test set.
    """
    test_idx = xsec.index[xsec["era"] == "test"]
    train_era = xsec.loc[xsec["era"] == "train"]
    train_idx, val_idx = split_honest(
        train_era, key="event_id", date_col="minute", train_frac=1 - val_frac_of_train, purge=purge
    )

    assert_no_group_leak(xsec, "event_id", train_idx, val_idx)
    assert_no_group_leak(xsec, "event_id", train_idx, test_idx)
    assert_no_group_leak(xsec, "event_id", val_idx, test_idx)
    assert_no_pair_minute_leak(xsec, train_idx, test_idx)
    assert_no_pair_minute_leak(xsec, train_idx, val_idx)
    assert_no_pair_minute_leak(xsec, val_idx, test_idx)

    return train_idx, val_idx, test_idx


def tune_hyperparameters_b(
    xsec: pd.DataFrame,
    horizon: int = 10,
    seed: int = 42,
    val_frac_of_train: float = 0.2,
    purge: str = "24h",
    max_train_negatives: int = MAX_TRAIN_NEGATIVES,
) -> dict:
    """Select one hyperparameter config per model via joint (Cartesian)
    grid search on validation AP at a single horizon (default h=10, per the
    guide's priority ordering) -- train fits, validation selects, the real
    test set is never touched. Same approach as Experiment A's
    tune_hyperparameters, reusing exp_a's HYPERPARAM_GRIDS since the models
    (not the feature set) define the grids.

    Returns {"chosen": {model: {param: value}}, "trials": {model: {combo: val_ap}},
    "horizon_min", "n_train_events", "n_val_events"}.
    """
    feature_cols = feature_columns_in(xsec)
    labeled = add_horizon_labels(xsec, horizons=(horizon,))
    train_idx, val_idx, _test_idx = split_b(labeled, val_frac_of_train=val_frac_of_train, purge=purge)

    train_df, val_df = labeled.loc[train_idx], labeled.loc[val_idx]
    y_col = f"y_{horizon}"
    X_train, y_train = train_df[feature_cols], train_df[y_col]
    X_val, y_val = val_df[feature_cols], val_df[y_col]

    if y_train.sum() == 0 or y_val.sum() == 0:
        raise ValueError(
            f"horizon {horizon}: no positives in train ({y_train.sum()}) "
            f"or validation ({y_val.sum()}) -- cannot tune on this split"
        )

    fit_X, fit_y, _ = _cap_for_distance_models(X_train, y_train, max_negatives=max_train_negatives, seed=seed)

    chosen: dict = {}
    trials: dict = {}
    for model_name, grid in HYPERPARAM_GRIDS.items():
        params = list(grid.keys())
        value_lists = [grid[p] for p in params]
        combo_results: dict[tuple, float] = {}

        for combo in itertools.product(*value_lists):
            overrides = {model_name: dict(zip(params, combo))}
            model = build_models(seed=seed, overrides=overrides)[model_name]
            model.fit(fit_X, fit_y)
            scores = _get_scores(model, X_val)
            combo_results[combo] = metrics.average_precision(y_val, scores)

        best_combo = max(combo_results, key=combo_results.get)
        chosen[model_name] = dict(zip(params, best_combo))
        trials[model_name] = {
            ", ".join(f"{p}={v}" for p, v in zip(params, combo)): ap
            for combo, ap in combo_results.items()
        }

    return {
        "chosen": chosen, "trials": trials, "horizon_min": horizon,
        "n_train_events": train_df["event_id"].nunique(),
        "n_val_events": val_df["event_id"].nunique(),
    }


def select_deployment_candidate(
    xsec: pd.DataFrame,
    model_overrides: dict,
    horizon: int = 10,
    seed: int = 42,
    val_frac_of_train: float = 0.2,
    purge: str = "24h",
    max_train_negatives: int = MAX_TRAIN_NEGATIVES,
) -> dict:
    """Pick the deployment candidate by VALIDATION average precision at the
    headline horizon -- never by test performance, per the guide's explicit
    rule ("the test set cannot select the best model"). Returns each
    model's validation AP and the chosen model's name.
    """
    feature_cols = feature_columns_in(xsec)
    labeled = add_horizon_labels(xsec, horizons=(horizon,))
    train_idx, val_idx, _test_idx = split_b(labeled, val_frac_of_train=val_frac_of_train, purge=purge)

    train_df, val_df = labeled.loc[train_idx], labeled.loc[val_idx]
    y_col = f"y_{horizon}"
    X_train, y_train = train_df[feature_cols], train_df[y_col]
    X_val, y_val = val_df[feature_cols], val_df[y_col]

    fit_X, fit_y, _ = _cap_for_distance_models(X_train, y_train, max_negatives=max_train_negatives, seed=seed)

    val_ap_by_model = {}
    for model_name, model in build_models(seed=seed, overrides=model_overrides).items():
        model.fit(fit_X, fit_y)
        scores = _get_scores(model, X_val)
        val_ap_by_model[model_name] = metrics.average_precision(y_val, scores)

    best_model = max(val_ap_by_model, key=val_ap_by_model.get)
    return {"val_ap_by_model": val_ap_by_model, "deployment_candidate": best_model, "horizon_min": horizon}


def run_experiment_b_sweep(
    xsec: pd.DataFrame,
    horizons=HORIZONS_MIN,
    seed: int = 42,
    model_overrides: dict | None = None,
    val_frac_of_train: float = 0.2,
    purge: str = "24h",
) -> tuple[list[dict], pd.DataFrame]:
    """Train all six models per horizon on Experiment B's honest split,
    scored with average precision on the real (2020+) test era. The split
    is computed once (independent of horizon) and reused across horizons,
    same pattern as Experiment A.

    Returns (records, predictions) -- predictions carries event_id, pair,
    minute so Hit@k can be computed afterward without retraining.
    """
    feature_cols = feature_columns_in(xsec)
    labeled = add_horizon_labels(xsec, horizons=horizons)
    train_idx, _val_idx, test_idx = split_b(labeled, val_frac_of_train=val_frac_of_train, purge=purge)

    train_df = labeled.loc[train_idx]
    test_df = labeled.loc[test_idx]

    run_id = f"exp_b_{pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%SZ')}"
    records: list[dict] = []
    prediction_frames: list[pd.DataFrame] = []

    for horizon in horizons:
        y_col = f"y_{horizon}"
        X_train, y_train = train_df[feature_cols], train_df[y_col]
        X_test, y_test = test_df[feature_cols], test_df[y_col]

        base_record = {
            "run_id": run_id, "horizon_min": horizon, "protocol": "era_honest",
            "split": "test", "n_rows": len(test_df),
            "n_events": int(test_df["event_id"].nunique()),
            "prevalence": float(y_test.mean()) if len(y_test) else None,
            "seed": seed,
        }

        if y_train.sum() == 0 or y_test.sum() == 0:
            records.append({**base_record, "model": None, "ap": None,
                             "note": "undefined: no positives in train or test for this horizon"})
            continue

        # Training negatives sampled once per horizon (guide-permitted for B),
        # reused for every model so all six see the identical training sample.
        fit_X, fit_y, sample_info = _cap_for_distance_models(
            X_train, y_train, max_negatives=MAX_TRAIN_NEGATIVES, seed=seed
        )

        for model_name, model in build_models(seed=seed, overrides=model_overrides).items():
            t0 = time.perf_counter()
            model.fit(fit_X, fit_y)
            fit_time_sec = time.perf_counter() - t0

            t0 = time.perf_counter()
            scores = _get_scores(model, X_test)
            inference_time_sec = time.perf_counter() - t0

            ap = metrics.average_precision(y_test, scores)

            records.append({
                **base_record, "model": model_name, "ap": ap,
                "fit_time_sec": fit_time_sec, "inference_time_sec": inference_time_sec,
                "n_train_rows_used": len(fit_X), "train_sample_info": sample_info,
            })

            prediction_frames.append(pd.DataFrame({
                "run_id": run_id, "model": model_name, "horizon_min": horizon,
                "event_id": test_df["event_id"].to_numpy(),
                "pair": test_df["pair"].to_numpy(),
                "minute": test_df["minute"].to_numpy(),
                "lead_min": test_df["lead_min"].to_numpy(),
                "y_true": y_test.to_numpy(),
                "score": scores,
            }))

    predictions = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    return records, predictions


def hit_at_k_snapshot(predictions: pd.DataFrame, horizon: int, k: int, model: str) -> dict:
    """At the single cross-sectional snapshot exactly `horizon` minutes
    before each test event's onset, rank every coin present and check
    whether the pumped coin lands in the top k. This is the guide's
    "at minute onset - h, rank all coins" Hit@k, distinct from the
    within-h-minutes AP label used for training/run_experiment_b_sweep.

    Events with no row at exactly that minute (a gap in the downloaded
    data) are excluded, counted separately rather than treated as a miss.
    """
    sub = predictions[(predictions.horizon_min == horizon) & (predictions.model == model)].copy()
    sub["is_target_at_horizon"] = (
        sub["lead_min"].notna() & (sub["lead_min"].round().astype("Int64") == k)
    )

    snapshot_rows = []
    n_no_snapshot = 0
    for event_id, group in sub.groupby("event_id"):
        target_rows = group[group["is_target_at_horizon"]]
        if target_rows.empty:
            n_no_snapshot += 1
            continue
        target_minute = target_rows.iloc[0]["minute"]
        snapshot = group[group["minute"] == target_minute]
        snapshot_rows.append(snapshot.assign(is_true_pump=snapshot.index.isin(target_rows.index)))

    if not snapshot_rows:
        return {"hit_rate": None, "n_eligible": 0, "n_excluded": n_no_snapshot, "k": k, "horizon_min": horizon}

    snapshots = pd.concat(snapshot_rows, ignore_index=True)
    result = metrics.hit_at_k(snapshots, group_key="event_id", score_col="score", true_col="is_true_pump", k=k)
    result["n_excluded"] += n_no_snapshot
    result["k"] = k
    result["horizon_min"] = horizon
    return result


def freeze_deployment_model(
    xsec: pd.DataFrame,
    model_name: str,
    model_overrides: dict,
    horizon: int = 10,
    seed: int = 42,
) -> dict:
    """Fit the final deployment artifact on ALL available labeled rows
    (train + validation + test eras combined) using the already-selected
    model and hyperparameters.

    This is standard practice ONLY because model/hyperparameter selection
    is already finalized (by validation AP, in select_deployment_candidate
    and tune_hyperparameters_b) -- no further comparison or tuning happens
    after this point. The held-out test AP/Hit@k numbers already reported
    remain the honest measure of out-of-sample performance; this function
    does not change or re-measure them, it just uses the extra data (test
    rows the evaluation already consumed its one honest look at) for the
    artifact that will actually run live, which is standard once no more
    evaluation is planned on that split.

    Returns {"model": fitted estimator, "feature_columns": [...],
    "model_name", "horizon_min", "n_rows_trained_on", "n_events_trained_on"}.
    """
    feature_cols = feature_columns_in(xsec)
    labeled = add_horizon_labels(xsec, horizons=(horizon,))
    y_col = f"y_{horizon}"

    X_all, y_all = labeled[feature_cols], labeled[y_col]
    if y_all.sum() == 0:
        raise ValueError(f"no positives anywhere in the dataset for horizon {horizon}")

    fit_X, fit_y, sample_info = _cap_for_distance_models(
        X_all, y_all, max_negatives=MAX_TRAIN_NEGATIVES, seed=seed
    )
    model = build_models(seed=seed, overrides=model_overrides)[model_name]
    model.fit(fit_X, fit_y)

    return {
        "model": model,
        "feature_columns": feature_cols,
        "model_name": model_name,
        "horizon_min": horizon,
        "n_rows_trained_on": len(fit_X),
        "n_events_trained_on": int(labeled["event_id"].nunique()),
        "train_sample_info": sample_info,
        "hyperparameters": model_overrides.get(model_name, {}),
    }
