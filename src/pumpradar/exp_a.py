"""Experiment A: leakage audit using the Sapienza 25-second chunk features.

Experiment A reuses the exact chunk-level features published by
SystemsLab-Sapienza, so any P0-vs-P2 performance gap found by this
experiment cannot be blamed on different features than prior work used --
only on the split protocol (see splits.py).

Two build-guide steps live here:

- M1 (data prep): load_raw_features / prepare_experiment_a_dataset -- derive
  each pump's onset, lead_min, and per-horizon labels.
- M3 (leakage audit): run_experiment_a_sweep -- train all six models under
  both the random (P0) and honest (P2) protocols, across all six horizons
  and two feature sets, and score with average precision. Hyperparameters
  below are reasonable fixed defaults, NOT yet tuned (tuning is a later,
  deployment-selection step, not part of the leakage audit itself) -- this
  is stated explicitly rather than implied, so these AP numbers are never
  mistaken for a tuned result.
"""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier

from pumpradar import metrics
from pumpradar.splits import split_honest, split_honest_train_val_test, split_random

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_FEATURES_PATH = PROJECT_ROOT / "data" / "raw" / "sapienza" / "features_25S.csv"
PREPARED_PATH = PROJECT_ROOT / "data" / "processed" / "sapA.parquet"
METRICS_PATH = PROJECT_ROOT / "results" / "metrics_A.json"
PREDICTIONS_PATH = PROJECT_ROOT / "results" / "predictions_A.parquet"

HORIZONS_MIN = (1, 3, 5, 10, 30, 60)
MAX_LEAD_MIN = 360  # keep only the 6 hours before onset

REQUIRED_RAW_COLUMNS = {"date", "pump_index", "symbol", "gt"}

# "Prior work's full feature set" = every engineered column in the Sapienza
# file. "Clean set" drops price-level columns and time-of-day columns, per
# the build guide's instruction to test whether those drive P0 inflation.
FULL_FEATURE_COLUMNS = (
    "std_rush_order", "avg_rush_order", "std_trades", "std_volume", "avg_volume",
    "std_price", "avg_price", "avg_price_max",
    "hour_sin", "hour_cos", "minute_sin", "minute_cos",
)
CLEAN_FEATURE_COLUMNS = (
    "std_rush_order", "avg_rush_order", "std_trades", "std_volume", "avg_volume",
)

# KNN has no class_weight; linear SVM fit cost scales badly with n. Both are
# capped to all positives + this many sampled negatives, per the guide.
MAX_NEGATIVES_FOR_DISTANCE_MODELS = 20_000


def load_raw_features(path: Path = RAW_FEATURES_PATH) -> pd.DataFrame:
    """Load the real Sapienza chunk-level CSV.

    Does not assume a schema beyond the columns this module actually uses --
    raises with a clear message if they're missing, rather than silently
    proceeding against data that doesn't match expectations.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Pull labeled_features/features_25S.csv from "
            "Hannah's feat/data-events branch (Git LFS) first."
        )
    df = pd.read_csv(path, parse_dates=["date"])
    missing = REQUIRED_RAW_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Unexpected schema: missing columns {sorted(missing)}")
    return df


def prepare_experiment_a_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Add onset, lead_min and y_<horizon> labels.

    - onset per pump_index = earliest row with gt == 1 for that group.
    - lead_min = minutes from a row's timestamp to its pump's onset.
    - Rows are kept only if 0 < lead_min <= MAX_LEAD_MIN, i.e. strictly
      before onset and within the 6-hour pre-onset window. This excludes the
      onset row itself and every post-onset row from early-warning examples.
    - pump_index groups with no gt == 1 row anywhere have no defined onset
      and are dropped entirely (counts are recorded in df.attrs, not hidden).

    Returns a new DataFrame; does not mutate the input.
    """
    onset = (
        df.loc[df["gt"] == 1]
        .groupby("pump_index")["date"]
        .min()
        .rename("onset")
    )

    n_total_groups = df["pump_index"].nunique()
    n_groups_without_onset = n_total_groups - onset.shape[0]

    out = df.join(onset, on="pump_index")
    n_rows_dropped_no_onset = int(out["onset"].isna().sum())

    out["lead_min"] = (out["onset"] - out["date"]).dt.total_seconds() / 60.0
    out = out[(out["lead_min"] > 0) & (out["lead_min"] <= MAX_LEAD_MIN)].copy()

    for k in HORIZONS_MIN:
        out[f"y_{k}"] = (out["lead_min"] <= k).astype(int)

    out.attrs["n_pump_groups_total"] = n_total_groups
    out.attrs["n_pump_groups_without_onset"] = n_groups_without_onset
    out.attrs["n_rows_dropped_no_onset"] = n_rows_dropped_no_onset

    return out


def summarize(df: pd.DataFrame) -> dict:
    """Real, measured counts from the prepared DataFrame -- never hardcoded."""
    return {
        "n_rows": len(df),
        "n_pump_groups_used": int(df["pump_index"].nunique()),
        "n_pump_groups_total": df.attrs.get("n_pump_groups_total"),
        "n_pump_groups_without_onset_excluded": df.attrs.get("n_pump_groups_without_onset"),
        "n_symbols": int(df["symbol"].nunique()),
        "positives_per_horizon": {f"y_{k}": int(df[f"y_{k}"].sum()) for k in HORIZONS_MIN},
    }


# Small hyperparameter grids, per the build guide's K7 ("proposed small
# grids, not claims about optimal settings"). Each value is the single kwarg
# that varies; everything else stays at the fixed default in build_models.
HYPERPARAM_GRIDS = {
    "logreg": {"C": [0.1, 1.0, 10.0]},
    "knn": {"n_neighbors": [5, 15]},
    "decision_tree": {"max_depth": [3, 6]},
    "random_forest": {"max_depth": [6, 10]},
    "linear_svm": {"C": [0.1, 1.0, 10.0]},
    "lightgbm": {"num_leaves": [15, 31], "max_depth": [6, 8]},
}


def build_models(seed: int = 42, overrides: dict | None = None) -> dict:
    """Fresh instances of the six build-guide models.

    `overrides` is {model_name: {param: value}} -- only the params in
    HYPERPARAM_GRIDS are expected to be overridden; everything else is a
    fixed, documented default. With overrides=None, every model uses its
    default config (NOT a tuned grid -- see module docstring); pass the
    output of tune_hyperparameters to use validation-selected configs
    instead.
    """
    overrides = overrides or {}
    logreg_C = overrides.get("logreg", {}).get("C", 1.0)
    knn_k = overrides.get("knn", {}).get("n_neighbors", 15)
    dt_depth = overrides.get("decision_tree", {}).get("max_depth", 6)
    rf_depth = overrides.get("random_forest", {}).get("max_depth", 8)
    svm_C = overrides.get("linear_svm", {}).get("C", 1.0)
    lgb_leaves = overrides.get("lightgbm", {}).get("num_leaves", 15)
    lgb_depth = overrides.get("lightgbm", {}).get("max_depth", 6)

    return {
        "logreg": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(C=logreg_C, class_weight="balanced", max_iter=1000, random_state=seed),
        ),
        "knn": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            KNeighborsClassifier(n_neighbors=knn_k),
        ),
        "decision_tree": DecisionTreeClassifier(
            max_depth=dt_depth, class_weight="balanced", random_state=seed
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200, max_depth=rf_depth, class_weight="balanced", random_state=seed, n_jobs=-1
        ),
        "linear_svm": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LinearSVC(C=svm_C, class_weight="balanced", random_state=seed, max_iter=5000),
        ),
        "lightgbm": lgb.LGBMClassifier(
            n_estimators=200, num_leaves=lgb_leaves, max_depth=lgb_depth, class_weight="balanced",
            random_state=seed, verbosity=-1,
        ),
    }


def _get_scores(fitted_model, X) -> np.ndarray:
    """predict_proba when available; otherwise decision_function (linear SVM).

    Decision-function values are ranking scores, not calibrated
    probabilities -- fine for AP, which only depends on the ranking.
    """
    if hasattr(fitted_model, "predict_proba"):
        return fitted_model.predict_proba(X)[:, 1]
    if hasattr(fitted_model, "decision_function"):
        return fitted_model.decision_function(X)
    raise TypeError(f"{fitted_model} has neither predict_proba nor decision_function")


def _cap_for_distance_models(X, y, max_negatives=MAX_NEGATIVES_FOR_DISTANCE_MODELS, seed=42):
    """All positives + up to max_negatives sampled negatives. Returns the
    capped (X, y) plus a dict recording the real counts used, so the cap is
    transparent in the saved results rather than hidden.
    """
    rng = np.random.default_rng(seed)
    y_arr = y.to_numpy()
    pos_idx = np.flatnonzero(y_arr == 1)
    neg_idx = np.flatnonzero(y_arr == 0)
    n_negatives_total = len(neg_idx)
    if n_negatives_total > max_negatives:
        neg_idx = rng.choice(neg_idx, size=max_negatives, replace=False)
    keep = np.concatenate([pos_idx, neg_idx])
    rng.shuffle(keep)
    sample_info = {
        "n_positives": len(pos_idx),
        "n_negatives_sampled": len(neg_idx),
        "n_negatives_total": int(n_negatives_total),
    }
    return X.iloc[keep], y.iloc[keep], sample_info


def tune_hyperparameters(
    prepared: pd.DataFrame,
    feature_cols,
    horizon: int = 10,
    seed: int = 42,
    outer_train_frac: float = 0.7,
    val_frac_of_train: float = 0.2,
    purge: str = "24h",
) -> dict:
    """Select one hyperparameter config per model via validation AP at a
    single horizon (default h=10, per the guide's K8 priority ordering),
    using the honest three-way split -- train fits, validation selects,
    test is never touched here.

    For each model, every combination in the Cartesian product of
    HYPERPARAM_GRIDS's values is tried (not a coordinate search that holds
    other params at their default while varying one -- that misses
    parameter interactions, e.g. LightGBM's num_leaves and max_depth, which
    only a joint search can find). The combination with the highest
    validation AP is kept; ties keep the first (smallest-index) combination
    tried. Grids are still small ("proposed small grids, not claims about
    optimal settings," per the build guide) and the validation set is only
    44 events, so more exhaustive tuning than this would risk overfitting
    the validation set itself rather than finding a genuinely better model.

    Returns {model_name: {param: chosen_value}}, plus a parallel
    {model_name: "combo -> val_ap"} trail under "trials" so the selection is
    auditable rather than a black box.
    """
    feature_cols = list(feature_cols)
    y_col = f"y_{horizon}"
    train_idx, val_idx, _test_idx = split_honest_train_val_test(
        prepared,
        key="pump_index",
        date_col="date",
        outer_train_frac=outer_train_frac,
        val_frac_of_train=val_frac_of_train,
        purge=purge,
    )
    train_df, val_df = prepared.loc[train_idx], prepared.loc[val_idx]
    X_train, y_train = train_df[feature_cols], train_df[y_col]
    X_val, y_val = val_df[feature_cols], val_df[y_col]

    if y_train.sum() == 0 or y_val.sum() == 0:
        raise ValueError(
            f"horizon {horizon}: no positives in train ({y_train.sum()}) "
            f"or validation ({y_val.sum()}) -- cannot tune on this split"
        )

    chosen: dict = {}
    trials: dict = {}

    fit_X, fit_y = X_train, y_train
    capped_fit_X, capped_fit_y, _ = _cap_for_distance_models(X_train, y_train, seed=seed)

    for model_name, grid in HYPERPARAM_GRIDS.items():
        params = list(grid.keys())
        value_lists = [grid[p] for p in params]
        combo_results: dict[tuple, float] = {}

        fit_X_use, fit_y_use = (
            (capped_fit_X, capped_fit_y) if model_name in ("knn", "linear_svm") else (fit_X, fit_y)
        )

        for combo in itertools.product(*value_lists):
            overrides = {model_name: dict(zip(params, combo))}
            model = build_models(seed=seed, overrides=overrides)[model_name]
            model.fit(fit_X_use, fit_y_use)
            scores = _get_scores(model, X_val)
            combo_results[combo] = metrics.average_precision(y_val, scores)

        best_combo = max(combo_results, key=combo_results.get)
        chosen[model_name] = dict(zip(params, best_combo))
        trials[model_name] = {
            ", ".join(f"{p}={v}" for p, v in zip(params, combo)): ap
            for combo, ap in combo_results.items()
        }

    return {"chosen": chosen, "trials": trials, "horizon_min": horizon,
            "n_train_events": train_df["pump_index"].nunique(),
            "n_val_events": val_df["pump_index"].nunique()}


def run_experiment_a_sweep(
    prepared: pd.DataFrame,
    horizons=HORIZONS_MIN,
    feature_sets: dict | None = None,
    seed: int = 42,
    train_frac: float = 0.7,
    purge: str = "24h",
    model_overrides: dict | None = None,
) -> tuple[list[dict], pd.DataFrame]:
    """Train all six models under both P0 (random) and P2 (honest) splits,
    for each horizon and feature set, scored with average precision (AP).

    The train/test split only depends on the protocol, not on horizon or
    feature set (every horizon shares the same rows, just a different label
    column), so each protocol's split is computed once and reused.

    `model_overrides`, if given, is the {model_name: {param: value}} dict
    from tune_hyperparameters -- applied identically across every horizon,
    protocol and feature set in this sweep, rather than re-tuned per
    combination (tuning happens once at a representative horizon; the
    headline audit sweep reuses that choice, per the guide's own staging).

    Returns (records, predictions):
    - records: one dict per (feature_set, protocol, horizon[, model]) matching
      the build guide's metrics_A.json shape, plus fit/inference time and
      sample-size bookkeeping. A (feature_set, protocol, horizon) combination
      with no positives on either side is recorded once with model=None and
      ap=None rather than silently skipped.
    - predictions: one row per held-out test example per model run (run_id,
      model, horizon, protocol, feature_set, pump_index, symbol, date,
      y_true, score). No thresholded prediction yet -- the operating
      threshold is chosen later, on a validation stream (K11), not invented
      here.
    """
    if feature_sets is None:
        feature_sets = {"full": list(FULL_FEATURE_COLUMNS), "clean": list(CLEAN_FEATURE_COLUMNS)}

    run_id = f"exp_a_{pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%SZ')}"
    records: list[dict] = []
    prediction_frames: list[pd.DataFrame] = []

    honest_train_idx, honest_test_idx = split_honest(
        prepared, key="pump_index", date_col="date", train_frac=train_frac, purge=purge
    )
    random_train_idx, random_test_idx = split_random(prepared, seed=seed, frac=train_frac)
    splits_by_protocol = {
        "random_P0": (random_train_idx, random_test_idx),
        "honest_P2": (honest_train_idx, honest_test_idx),
    }

    for feature_set_name, feature_cols in feature_sets.items():
        for protocol, (train_idx, test_idx) in splits_by_protocol.items():
            train_df = prepared.loc[train_idx]
            test_df = prepared.loc[test_idx]

            for horizon in horizons:
                y_col = f"y_{horizon}"
                X_train, y_train = train_df[list(feature_cols)], train_df[y_col]
                X_test, y_test = test_df[list(feature_cols)], test_df[y_col]

                base_record = {
                    "run_id": run_id,
                    "horizon_min": horizon,
                    "protocol": protocol,
                    "feature_set": feature_set_name,
                    "split": "test",
                    "n_rows": len(test_df),
                    "n_events": int(test_df["pump_index"].nunique()),
                    "prevalence": float(y_test.mean()) if len(y_test) else None,
                    "seed": seed,
                }

                if y_train.sum() == 0 or y_test.sum() == 0:
                    records.append({
                        **base_record,
                        "model": None,
                        "ap": None,
                        "note": "undefined: no positives in train or test for this horizon/split",
                    })
                    continue

                for model_name, model in build_models(seed=seed, overrides=model_overrides).items():
                    fit_X, fit_y = X_train, y_train
                    sample_info = None
                    if model_name in ("knn", "linear_svm"):
                        fit_X, fit_y, sample_info = _cap_for_distance_models(
                            X_train, y_train, seed=seed
                        )

                    t0 = time.perf_counter()
                    model.fit(fit_X, fit_y)
                    fit_time_sec = time.perf_counter() - t0

                    t0 = time.perf_counter()
                    scores = _get_scores(model, X_test)
                    inference_time_sec = time.perf_counter() - t0

                    ap = metrics.average_precision(y_test, scores)

                    records.append({
                        **base_record,
                        "model": model_name,
                        "ap": ap,
                        "fit_time_sec": fit_time_sec,
                        "inference_time_sec": inference_time_sec,
                        "n_train_rows_used": len(fit_X),
                        "sample_info": sample_info,
                    })

                    prediction_frames.append(pd.DataFrame({
                        "run_id": run_id,
                        "model": model_name,
                        "horizon_min": horizon,
                        "protocol": protocol,
                        "feature_set": feature_set_name,
                        "pump_index": test_df["pump_index"].to_numpy(),
                        "symbol": test_df["symbol"].to_numpy(),
                        "date": test_df["date"].to_numpy(),
                        "y_true": y_test.to_numpy(),
                        "score": scores,
                    }))

    predictions = (
        pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    )
    return records, predictions


def coin_identity_canary(
    prepared: pd.DataFrame,
    horizon: int = 10,
    seed: int = 42,
    train_frac: float = 0.7,
    purge: str = "24h",
) -> dict:
    """Diagnostic only, never a deployed feature: add a one-hot coin-identity
    column to the clean feature set and compare AP with vs without it, under
    both P0 and P2. If identity lifts AP under P0 but not P2, the random
    split is rewarding coin recognition rather than genuine early-warning
    signal.
    """
    y_col = f"y_{horizon}"
    onehot_symbol = pd.get_dummies(prepared["symbol"], prefix="symbol")
    with_identity = pd.concat([prepared, onehot_symbol], axis=1)
    identity_cols = list(onehot_symbol.columns)

    honest_train_idx, honest_test_idx = split_honest(
        with_identity, key="pump_index", date_col="date", train_frac=train_frac, purge=purge
    )
    random_train_idx, random_test_idx = split_random(with_identity, seed=seed, frac=train_frac)
    splits_by_protocol = {
        "random_P0": (random_train_idx, random_test_idx),
        "honest_P2": (honest_train_idx, honest_test_idx),
    }

    results = {}
    for protocol, (train_idx, test_idx) in splits_by_protocol.items():
        train_df, test_df = with_identity.loc[train_idx], with_identity.loc[test_idx]
        for variant_name, cols in (
            ("clean", list(CLEAN_FEATURE_COLUMNS)),
            ("clean_plus_identity", list(CLEAN_FEATURE_COLUMNS) + identity_cols),
        ):
            model = build_models(seed=seed)["logreg"]
            model.fit(train_df[cols], train_df[y_col])
            scores = _get_scores(model, test_df[cols])
            results[f"{protocol}_{variant_name}"] = metrics.average_precision(test_df[y_col], scores)

    results["identity_lift_P0"] = (
        results["random_P0_clean_plus_identity"] - results["random_P0_clean"]
    )
    results["identity_lift_P2"] = (
        results["honest_P2_clean_plus_identity"] - results["honest_P2_clean"]
    )
    results["horizon_min"] = horizon
    return results


def main() -> None:
    raw = load_raw_features()
    prepared = prepare_experiment_a_dataset(raw)

    PREPARED_PATH.parent.mkdir(parents=True, exist_ok=True)
    prepared.to_parquet(PREPARED_PATH, index=False)

    summary = summarize(prepared)
    print(f"Saved {PREPARED_PATH} ({summary['n_rows']} rows)")
    print(
        f"Pump groups used: {summary['n_pump_groups_used']} / "
        f"{summary['n_pump_groups_total']} "
        f"({summary['n_pump_groups_without_onset_excluded']} excluded: no gt==1 row)"
    )
    print(f"Symbols: {summary['n_symbols']}")
    print("Positives per horizon (pre-onset rows within 6h, strictly lead_min > 0):")
    for k, v in summary["positives_per_horizon"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
