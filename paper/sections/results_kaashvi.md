<!--
Results section draft -- owner: Kaashvi Das.
Drafting format: Markdown, to be ported into the team's shared paper format
(LaTeX/Overleaf) once the paper skeleton (W1, owner: Hannah) exists. Content
here is restricted to what Experiment A has actually produced; Experiment B
results will be appended once Hannah's cross-sectional handoff lands.

Every number below is traceable to a generated file under results/ -- see
the claims ledger at the end. Nothing in this section is asserted from
memory, from the build guide's placeholder figures, or from an unexecuted
code path.
-->

# 6. Results and Comparison

## 6.1 Dataset

Experiment A uses the real SystemsLab-Sapienza 25-second chunk-level feature
dataset (`labeled_features/features_25S.csv`, verified via SHA-256 against
its Git LFS pointer), spanning 2018-01-02 to 2021-01-19. Of 327 labeled pump
events, 317 have a confirmed onset (a row with `gt == 1`); the remaining 10
have no such row and are excluded, since no lead time can be computed
without a defined onset. After restricting to the strict pre-onset window
(0 < lead_min <= 360 minutes), 55,141 rows across 317 events and 85 coins
remain for training and evaluation.

## 6.2 Protocol: leakage audit

We compare two evaluation protocols on identical features: **P0**, rows
shuffled at random (reproducing the cross-validation style used by prior
work), and **P2**, an honest protocol that keeps every event's rows on one
side, orders events chronologically (earliest 70% train, latest 30% test),
and purges any training row within 24 hours of the test period. Both
protocols use the same 70/30 train/test ratio, controlling for training-set
size as a confound between them. Inflation is defined as AP(P0) - AP(P2);
a positive value means the random-split protocol overstated the honestly
measured performance.

Each of six models (Logistic Regression, KNN, Decision Tree, Random Forest,
linear SVM, LightGBM) was evaluated under both protocols, across all six
early-warning horizons (1, 3, 5, 10, 30, 60 minutes), and under two feature
sets: **full** (every engineered Sapienza column, including price-level and
time-of-day) and **clean** (drops price-level and time-of-day, keeping only
rush-order/trade/volume features). Hyperparameters were selected once per
feature set via a held-out validation slice at the 10-minute horizon (the
three-way, event-grouped, chronologically embargoed split), never via the
test set; the chosen configuration was then applied unchanged across all six
horizons.

## 6.3 Headline comparison at h = 10 minutes

**Clean feature set** (average precision; base rate / prevalence = 5.7%):

| Model | Honest (P2) | Random (P0) | Inflation |
|---|---|---|---|
| LightGBM | 0.102 | 0.117 | +0.015 |
| Logistic Regression | 0.108 | 0.108 | +0.000 |
| Decision Tree | 0.101 | 0.102 | +0.000 |
| Linear SVM | 0.107 | 0.106 | -0.002 |
| Random Forest | 0.122 | 0.119 | -0.002 |
| KNN | 0.099 | 0.090 | -0.009 |

**Full feature set:**

| Model | Honest (P2) | Random (P0) | Inflation |
|---|---|---|---|
| KNN | 0.413 | 0.504 | +0.090 |
| LightGBM | 0.544 | 0.629 | +0.086 |
| Logistic Regression | 0.391 | 0.404 | +0.013 |
| Linear SVM | 0.399 | 0.411 | +0.012 |
| Decision Tree | 0.470 | 0.477 | +0.007 |
| Random Forest | 0.574 | 0.566 | -0.009 |

With clean features, inflation is small and inconsistent in sign across
models -- not distinguishable from zero at this sample size. With full
features, every model's absolute AP rises substantially (near 4-5x for
several models), and inflation is positive for five of six models, largest
for the two highest-capacity, most memorization-prone models (KNN, LightGBM)
and smallest for the simplest ones (decision tree, logistic regression).

## 6.4 Statistical significance

A 1,000-repeat event-level bootstrap (resampling whole held-out events, not
rows; 96 honest-split and comparable random-split test events) was computed
for every model/feature-set/protocol combination at h = 10. Under this
check, no combination's P0 and P2 confidence intervals are cleanly
non-overlapping -- including the full-feature KNN and LightGBM cases with
the largest point estimates (KNN: honest 95% CI [0.355, 0.494] vs. random
[0.453, 0.555]; LightGBM: honest [0.476, 0.623] vs. random [0.580, 0.684]).
The overlap in both cases is narrow and at the extreme edge of each
interval. We report this as a real, directionally consistent signal that is
not yet statistically decisive given the available number of held-out
events, rather than rounding the finding up to "leakage confirmed" or down
to "no effect."

## 6.5 Inflation across horizons

Averaged across models, clean-feature inflation is small and positive at
short horizons (1-10 minutes, +0.0003 to +0.0040) and negative at longer
horizons (30 minutes: -0.016; 60 minutes: -0.026). We report this pattern as
observed rather than selectively citing only the horizons consistent with
the expected direction; we do not have an explanation for the sign flip at
longer horizons and are not speculating one here.

## 6.6 Coin-identity canary

As a diagnostic (never a deployed feature), a one-hot coin-identity column
was added to the clean feature set for a logistic regression model at
h = 10. Identity lifted AP by +0.008 under the random split and *reduced*
AP by -0.022 under the honest split -- consistent with identity acting as a
shortcut that only helps when future coins can leak into training, and
actively hurting generalization to coins/events not seen during training
under the honest protocol.

## 6.7 Interpretation

Taken together, these results support a specific, qualified claim: **the
random-split protocol used by prior work does not meaningfully inflate
performance when only rush-order/volume/trade-count features are used, but
shows a real, capacity-correlated, directionally consistent -- though not
yet statistically conclusive -- inflation pattern once price-level and
time-of-day features are included.** We do not claim this proves price-level
features cause leakage; an alternative explanation (cheap, illiquid coins
being genuinely more pump-prone, a real tradeable signal rather than an
artifact) remains possible and is not ruled out by this audit alone.

## 6.8 What is not yet included in this section

Experiment B (cross-sectional "which coin, how early" scoring) is not yet
run; it depends on a cross-sectional feature handoff from the data
workstream that has not yet reached the shared repository. Hit@k, the
alert-budget threshold, and probability calibration are not yet computed.
This section will be revised once those results exist.

---

## Claims ledger

| Claim | Source |
|---|---|
| Dataset counts (327/317 events, 85 coins, 55,141 rows, date range) | `data/raw/sapienza/features_25S.csv` (SHA-256 verified) -> `src/pumpradar/exp_a.py::prepare_experiment_a_dataset`, printed by `exp_a.main()` |
| h=10 clean/full AP tables | `results/metrics_A_tuned.json` (`records`, filtered `horizon_min==10`) |
| Hyperparameters used | `results/tuning_h10.json` (`chosen`) |
| Bootstrap CIs | `results/bootstrap_A_h10.json` |
| Inflation-by-horizon figures | `results/figures/inflation_by_horizon.png`, `results/figures/prevalence_by_horizon.png` |
| Coin-identity canary | `results/metrics_A.json` (`canary_h10`) |
| Per-row predictions (audit trail) | `results/predictions_A_tuned.parquet` |
