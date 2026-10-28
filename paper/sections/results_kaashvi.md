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

## 6.7 Robustness: is the full-feature gap a training-size or boundary artifact?

Three checks, none of which were in the original audit pass:

- **Split-boundary sensitivity.** Re-running the honest split at train_frac in
  {0.60, 0.65, 0.70, 0.75, 0.80} (LightGBM, h=10) gives AP(P2) in [0.098,
  0.109] for clean features and [0.514, 0.556] for full features -- stable
  across every boundary tried. The reported 70/30 split is not a cherry-picked
  outlier.
- **Random-split seed sensitivity.** Five seeds of split_random (same model,
  horizon) give AP(P0) in [0.099, 0.112] for clean and [0.629, 0.659] for
  full -- also stable. The P0 estimate is not noise from one unlucky shuffle.
- **Training-size isolation.** Holding the protocol fixed (P0) and varying
  only the train fraction (0.5 vs 0.7, i.e. 27,570 vs 38,598 training rows)
  changes AP(P0) by only 0.007 for full features (0.637 to 0.629) and by
  0.010 for clean. Since P0 and P2 already use matched 70/30 ratios (Section
  6.2), and varying P0's own training size by this much barely moves its AP,
  training-set size cannot explain more than a small fraction of the ~0.09
  full-feature P0-P2 gap. The gap is attributable to the split *protocol*
  (random vs. chronological/grouped), not to how much data each side has.

## 6.8 Interpretability: what is the full-feature model actually using?

Permutation importance (LightGBM, honest test set, h=10, 30 repeats,
`sklearn.inspection.permutation_importance` scored on AP) revised our working
hypothesis. We had suspected price-level columns (`avg_price`, `std_price`,
`avg_price_max`) were driving the full-feature inflation, by acting as a
coin-identity fingerprint. **The data does not support that**: permuting
those three columns changes AP by between -0.002 and +0.001 -- effectively
zero importance.

Instead, the dominant features by a wide margin are the **time-of-day**
encodings: `minute_cos` (+0.381), `minute_sin` (+0.300), and `hour_sin`
(+0.186) -- together far larger than every volume/trade feature combined
(`avg_volume` +0.049 is the next largest). On the clean feature set (no
time-of-day available), importance is spread more evenly across
`avg_volume` (+0.042), `avg_rush_order` (+0.034) and `std_trades` (+0.033).

This changes the interpretation in Section 6.7's earlier draft, which
speculated about price-level. We now have a mechanistic lead -- time-of-day
-- but **two explanations remain open and this audit cannot distinguish
them**: (a) pump organizers genuinely favor certain times of day, a real,
legitimate predictive signal; or (b) with only 317 events, a small number of
recurring hour/minute values in the training set let the model partially
memorize "this time slot correlates with training-era pumps" in a way that
still partly transfers to the chronologically later test events (since
honest-split AP is still high, 0.544, this would have to be partial
memorization that generalizes somewhat, not pure overfitting). Distinguishing
these requires either more events spanning more distinct times of day, or a
dedicated ablation (e.g. shuffling time-of-day values across events while
holding everything else fixed) that has not been run.

## 6.9 Interpretation

Taken together: **the random-split protocol used by prior work does not
meaningfully inflate performance when only rush-order/volume/trade-count
features are used, and the clean-feature result is robust to split boundary
and seed choice. With the full feature set, there is a real, protocol-driven
(not training-size-driven) inflation gap, and permutation importance
identifies time-of-day encoding -- not price level, contrary to our initial
hypothesis -- as the feature group responsible for most of the full-feature
model's performance.** Whether that time-of-day signal is genuine or a
small-sample artifact is not resolved by this audit.

## 6.10 Full comparison across all six horizons (honest split, tuned models)

Average precision, honest (P2) split, tuned hyperparameters:

**Clean feature set:**

| Model | h=1 | h=3 | h=5 | h=10 | h=30 | h=60 |
|---|---|---|---|---|---|---|
| Random Forest | 0.142 | 0.094 | 0.096 | 0.121 | 0.217 | 0.326 |
| LightGBM | 0.143 | 0.083 | 0.082 | 0.102 | 0.202 | 0.310 |
| Logistic Regression | 0.107 | 0.077 | 0.079 | 0.108 | 0.202 | 0.314 |
| Linear SVM | 0.099 | 0.076 | 0.078 | 0.107 | 0.202 | 0.314 |
| KNN | 0.112 | 0.066 | 0.064 | 0.099 | 0.181 | 0.298 |
| Decision Tree | 0.091 | 0.064 | 0.074 | 0.102 | 0.197 | 0.315 |
| *base rate* | *0.006* | *0.019* | *0.031* | *0.057* | *0.146* | *0.262* |

**Full feature set:**

| Model | h=1 | h=3 | h=5 | h=10 | h=30 | h=60 |
|---|---|---|---|---|---|---|
| Random Forest | 0.356 | 0.524 | 0.567 | 0.574 | 0.547 | 0.544 |
| LightGBM | 0.344 | 0.462 | 0.507 | 0.544 | 0.563 | 0.557 |
| Decision Tree | 0.150 | 0.351 | 0.475 | 0.470 | 0.510 | 0.530 |
| Linear SVM | 0.187 | 0.215 | 0.263 | 0.398 | 0.531 | 0.540 |
| Logistic Regression | 0.188 | 0.207 | 0.253 | 0.391 | 0.531 | 0.540 |
| KNN | 0.200 | 0.238 | 0.349 | 0.413 | 0.459 | 0.490 |

Random Forest and LightGBM are consistently the top two models at every
horizon on the full feature set; Random Forest leads at short horizons
(1-10 min), LightGBM edges ahead at longer ones (30-60 min). Expressed as a
multiple of the base rate, the best model's lift ranges from about **57x at
h=1** down to **2.1x at h=60** -- early warning is relatively much stronger
than near-onset detection in rank terms, even though absolute AP is lower at
short horizons (because the base rate itself is far smaller there).

## 6.11 Live deployment feasibility: the BTC-pair universe has shrunk

A live check against Binance's public `exchangeInfo` endpoint (checked
2026-10-28T13:54:59Z, no API key required) found **38 actively trading
BTC-quoted spot pairs** on Binance right now, against 519 USDT-quoted pairs
and 520 distinct base assets across all quote currencies combined. The
Sapienza training data's 85 BTC-paired coins already exceeds today's live
BTC universe by more than 2x.

This confirms, with live data rather than assumption, the build guide's own
warning: **the trained model (BTC-quote features) can produce real scores
for at most 38 of today's live coins.** Reaching the platform's 130+-coin
display target necessarily means showing live prices for many coins this
model was never trained to score -- those must be marked "unavailable" for
scoring, not silently extrapolated. Training a model on an expanded
(BTC+USDT) quote-volume universe to score more of the live 130+ coins is
additional, unscoped work -- it is not a configuration change, since
quote-volume units differ and cross-sectional ranks cannot mix them without
a defined conversion. This is relevant to the platform, not just the model,
and should be confirmed with Aveek and Hannah before any UI commits to
showing scores for all displayed coins.

## 6.12 What is not yet included in this section

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
| Boundary/seed/training-size sensitivity | `results/sensitivity_checks.json` |
| Permutation importance | `results/permutation_importance.json` |
| Full across-horizon comparison tables | `results/metrics_A_tuned.json` (`records`, all `horizon_min`, `protocol=="honest_P2"`) |
