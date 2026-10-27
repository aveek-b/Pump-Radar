"""Shared evaluation metrics for PumpRadar research experiments.

Implementations follow the build guide's definitions (Section 07 / K10)
literally, so a reviewer can check each formula against the guide directly
rather than trusting a re-derivation.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, confusion_matrix


def average_precision(y_true, y_score) -> float:
    """AP via sklearn.average_precision_score.

    Labelled AP deliberately, not "PR-AUC" -- the guide warns against
    silently mixing this with trapezoidal PR-AUC, which is a different
    number.
    """
    return float(average_precision_score(y_true, y_score))


def classification_metrics(y_true, y_pred) -> dict:
    """accuracy, precision, recall, F1 and confusion-matrix counts.

    Returns None (not 0.0 or NaN) for any metric whose denominator is zero,
    so an undefined value can never be mistaken for a measured one.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    accuracy = (tp + tn) / len(y_true) if len(y_true) else None
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )

    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
        "prevalence": float(y_true.mean()) if len(y_true) else None,
        "n": len(y_true),
    }


def inflation(ap_p0: float, ap_honest: float) -> float:
    """Score under the random (P0) split minus score under the honest (P2)
    split. Positive means P0 looked better than the honest evaluation --
    i.e. the random split inflated the apparent result.
    """
    return ap_p0 - ap_honest


def threshold_at_budget(neg_scores, alerts_per_hour: float, n_coins: int) -> float:
    """Initial quantile approximation of the score threshold targeting a
    given false-alert budget across n_coins monitored coin-minutes.

    The build guide (K11) is explicit that this quantile formula is only a
    starting approximation -- cooldown, correlation and universe-size changes
    require actual stream simulation before this is trusted as a real
    operating threshold.
    """
    if n_coins <= 0:
        raise ValueError(f"n_coins must be positive, got {n_coins}")
    alpha = alerts_per_hour / (60 * n_coins)
    return float(np.quantile(neg_scores, 1 - alpha))


def hit_at_k(df: pd.DataFrame, group_key: str, score_col: str, true_col: str, k: int) -> dict:
    """Within each group (one cross-sectional snapshot), rank rows by score
    descending and check whether the true positive lands in the top k.

    A group with zero or more than one positive is excluded, not silently
    counted as a hit or a miss. Returns {"hit_rate", "n_eligible", "n_excluded"}.
    """
    hits = 0
    eligible = 0
    excluded = 0

    for _, group in df.groupby(group_key):
        if group[true_col].sum() != 1:
            excluded += 1
            continue
        ranked = group.sort_values(score_col, ascending=False, kind="stable")
        true_rank = int(np.argmax(ranked[true_col].to_numpy())) + 1  # 1-indexed
        eligible += 1
        if true_rank <= k:
            hits += 1

    hit_rate = hits / eligible if eligible else None
    return {"hit_rate": hit_rate, "n_eligible": eligible, "n_excluded": excluded}


def event_bootstrap(
    df: pd.DataFrame,
    group_col: str,
    metric_fn: Callable[[pd.DataFrame], float | None],
    n_repeats: int = 1000,
    seed: int = 42,
) -> dict:
    """Event-level bootstrap: resample whole groups (events) with
    replacement, n_repeats times, recomputing metric_fn on each resample.

    metric_fn receives a DataFrame (the resampled rows, with a group's rows
    included once per time it was drawn) and must return a float, or None if
    undefined on that resample (e.g. no positives). Undefined resamples are
    excluded from the interval and counted separately -- never silently
    turned into a favourable score, per the guide's explicit instruction.
    """
    rng = np.random.default_rng(seed)
    grouped = {key: sub for key, sub in df.groupby(group_col)}
    unique_groups = np.array(list(grouped.keys()))

    values = []
    n_undefined = 0

    for _ in range(n_repeats):
        drawn = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        resampled = pd.concat([grouped[g] for g in drawn], ignore_index=True)
        value = metric_fn(resampled)
        if value is None or (isinstance(value, float) and np.isnan(value)):
            n_undefined += 1
        else:
            values.append(value)

    if not values:
        return {
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "n_undefined": n_undefined,
            "n_repeats": n_repeats,
            "n_eligible_groups": len(unique_groups),
        }

    arr = np.array(values)
    return {
        "mean": float(arr.mean()),
        "ci_low": float(np.quantile(arr, 0.025)),
        "ci_high": float(np.quantile(arr, 0.975)),
        "n_undefined": n_undefined,
        "n_repeats": n_repeats,
        "n_eligible_groups": len(unique_groups),
    }
