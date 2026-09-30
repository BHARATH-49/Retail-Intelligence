# Demand forecasting V1 checklist

**Updated: 28 September 2026.** This tracks the forecasting part of the
[frozen V1 scope](v1-scope.md). A checked box means the work has been implemented
and exercised on the Favorita data, or that a saved result has been checked.
An unchecked box means work remains. The provisional data assumptions are in
[`decisions.md`](decisions.md).

## 1. Favorita data and preparation

- [x] Acquire and inspect the Favorita sales data: 125,497,040 recorded rows,
  54 stores, 4,036 products, and 174,685 store-product pairs.
- [x] Prepare a reusable sales CSV while preserving raw files. The completed
  run filled missing promotions, clipped negative sales to zero, and kept
  flags showing which values changed.
- [x] Regenerate the two-store working slice with promotion values and their
  missingness flags. The completed run wrote 5,549,993 recorded rows.
- [x] Define provisional product-history eligibility: at least 180 recorded
  rows and 365 inclusive calendar days, calculated before each forecast date.
- [x] State the assumption for missing daily sales: zero *recorded sales* in
  the model period. This does not confirm product availability or demand.

## 2. Feature engineering

- [x] Use the previous four matching weekdays' sales as lag inputs.
- [x] Calculate their average and median as simple forecast methods.
- [x] Add seven-day and 28-day trailing sales averages ending at least seven
  days before each target day for the first LightGBM comparison.
- [ ] Add explicit calendar inputs such as day of week, week, and month. Dates
  currently select matching weekdays but are not model inputs themselves.
- [ ] Use promotion information in a model. Promotions have been cleaned and
  flagged in the prepared data but are not forecasting inputs yet.
- [ ] Add holidays/events that can be mapped to the store and were knowable
  before the forecast. Test whether they improve results.
Product/store metadata and weather are conditional additions, only if reliable
inputs and a clear comparison question justify the extra work.

## 3. Model comparison

- [x] Compare with always predicting zero.
- [x] Test the four-week matching-weekday average and median. The single
  previous weekday (*seasonal naive*) is still a separate unchecked method.
- [ ] Test seasonal naive: predict the value from exactly seven days earlier.
- [x] Train and compare shared linear regression with an intercept and without
  an intercept. The zero-start version predicts zero when all four inputs are
  zero.
- [x] Try a two-step sale/amount model. It was evaluated but did not win the
  April/May development comparison.
- [x] Train **LightGBM A** with historical sales and rolling features on the
  same April/May chronological windows as the simple methods. Its combined
  MAE was 2.212 versus 2.488 for the four-week average over 78,834 targets.
  These are development results, not final selection.
- [ ] Compare **LightGBM B** after adding calendar features, **C** after adding
  promotions, and **D** after adding mapped holidays/events. Keep the
  evaluation protocol fixed so each addition can be judged.
- [ ] Decide whether another meaningfully different forecasting approach would
  add useful evidence at a practical cost, and record the reasoning. XGBoost,
  statistical methods, TFT, PatchTST, and a foundation model are possible
  experiments, not required implementations.

## 4. Chronological testing and metrics

- [x] Use earlier sales for training and later seven-day weeks for testing.
  Historical eligibility is recalculated before each test week.
- [x] Use April and May 2017 in Stores 1 and 2 to choose among current
  methods, then evaluate that choice on July 12–18. The saved result files
  passed an internal consistency check; the large run was not repeated here.
- [x] Calculate **MAE** (average absolute error in units sold), including
  separate results for recorded and assumed-zero test dates.
- [x] Define and calculate **WAPE** for the LightGBM development comparison;
  report it as undefined when a group's total actual sales is zero.
- [x] Define and calculate **MASE** using the seven-day seasonal-naive scale
  computed only from each group's training examples; report it as undefined
  when the scale is zero.
**RMSE** is an optional additional metric when large misses need separate
attention.
- [ ] Reserve at least one test period that has not been used to adjust the
  new models. July has now been inspected and should not be reused as a fresh
  final test.
- [ ] Check performance beyond two stores and a few weeks before making a
  broad claim about Favorita forecasting quality.
- [ ] Compare accuracy, variation across historical windows, and training
  cost before finalizing the forecasting approach.

## 5. V1 result

- [x] Produce seven-day historical forecasts and saved comparison files.
- [x] Establish reference results: zero-start linear regression had April/May
  combined MAE 2.368 and scored 2.281 versus 2.373 for the four-week average
  on the previously inspected July check. Sales-only LightGBM scored 2.212
  versus 2.488 for that average on April/May development windows. It has not
  had a fresh later evaluation.
- [ ] Select and document a validated V1 approach after the planned LightGBM,
  metric, and multi-window comparisons. The current leader is provisional.
- [ ] Build a repeatable future seven-day demand forecast from the selected
  method. Current saved forecasts are historical tests.

Forecast uncertainty is outside V1. Inventory, opportunity identification,
purchase comparison, and the application are V1 work tracked in the
[scope document](v1-scope.md), after the forecasting approach is sufficiently
validated.
