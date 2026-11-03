# Results

Test days are held out whole (Mar 4 and Mar 9), and each model is scored on them once. Error is the mean absolute error (MAE) of the predicted arrival time, in seconds. Predicting `delay_s` is the same as correcting TransLoc's ETA, so "TransLoc as-is" is simply a prediction of zero delay.

**Best model** means the tuned model with the lowest test MAE on that dataset: HistGradientBoostingRegressor for `bus`, ExtraTreesRegressor for `route`, XGBRegressor for `combined`. It is picked on the test days, so its score is slightly optimistic. Percentages are computed from the rounded numbers shown. Next steps are in the [README, section 10](../README.md#10-next-steps).

## 1. Best model vs TransLoc, and where the gain comes from

**L, the lookup table,** is a correction built for this study, not something TransLoc provides. It looks only at TransLoc's ETA. The training rows are sorted by ETA and cut into 10 ranges with the same number of rows each, and each range stores the average delay seen in training. To predict, find the range the ETA falls in and add that range's average delay. For example, on `route` one range is 6.1–8.1 min with an average delay of +7.9 min, so when TransLoc says 7 min, L predicts 14.9 min. The best model (**M**) adds the rest of the gain using the other features.

|  | `bus` | `route` | `combined` |
| --- | --- | --- | --- |
| Best model | HistGradientBoostingRegressor | ExtraTreesRegressor | XGBRegressor |
| **T** TransLoc as-is | 279 s | 290 s | 256 s |
| **L** Lookup table on TransLoc's ETA | 183 s | 173 s | 178 s |
| **M** Best model | 127 s | 136 s | 143 s |
| **Error reduction** (T − M) / T | **(279 − 127) / 279 = 54%** | **(290 − 136) / 290 = 53%** | **(256 − 143) / 256 = 44%** |
| … from the lookup table (T − L) / T | (279 − 183) / 279 = 34% | (290 − 173) / 290 = 40% | (256 − 178) / 256 = 30% |
| … added by the model (L − M) / T | (183 − 127) / 279 = 20% | (173 − 136) / 290 = 13% | (178 − 143) / 256 = 14% |

Two more baselines (the training mean delay, and a straight line in the ETA) are in section 6.

## 2. Error by how far away TransLoc says the bus is

| Dataset (best model) | TransLoc's ETA | Rows | TransLoc error | Model error | Reduction (TransLoc − model) / TransLoc |
| --- | --- | --- | --- | --- | --- |
| `bus` (HistGradientBoostingRegressor) | under 2 min | 1,377 | 99 s | 83 s | (99 − 83) / 99 = 16% |
|  | 2–5 min | 1,722 | 208 s | 103 s | (208 − 103) / 208 = 50% |
|  | 5–10 min | 2,350 | 308 s | 134 s | (308 − 134) / 308 = 56% |
|  | 10–20 min | 2,087 | 423 s | 169 s | (423 − 169) / 423 = 60% |
|  | **all** | 7,536 | 279 s | 127 s | (279 − 127) / 279 = 54% |
| `route` (ExtraTreesRegressor) | under 2 min | 3,085 | 103 s | 66 s | (103 − 66) / 103 = 36% |
|  | 2–5 min | 3,927 | 203 s | 106 s | (203 − 106) / 203 = 48% |
|  | 5–10 min | 5,597 | 340 s | 144 s | (340 − 144) / 340 = 58% |
|  | 10–20 min | 4,389 | 438 s | 201 s | (438 − 201) / 438 = 54% |
|  | **all** | 16,998 | 290 s | 136 s | (290 − 136) / 290 = 53% |
| `combined` (XGBRegressor) | under 2 min | 8,646 | 88 s | 74 s | (88 − 74) / 88 = 16% |
|  | 2–5 min | 5,184 | 178 s | 92 s | (178 − 92) / 178 = 48% |
|  | 5–10 min | 6,901 | 316 s | 154 s | (316 − 154) / 316 = 51% |
|  | 10–20 min | 6,868 | 418 s | 214 s | (418 − 214) / 418 = 49% |
|  | 20+ min | 1,542 | 463 s | 328 s | (463 − 328) / 463 = 29% |
|  | **all** | 29,141 | 256 s | 143 s | (256 − 143) / 256 = 44% |

**The models help most from 2 to 20 minutes out**, which is likely when riders decide whether to head to the stop (an assumption; there is no rider data here). In that range the error falls by 48–60% and the share of predictions within 2 minutes of the actual arrival rises by 23–34 points (section 3). Under 2 minutes TransLoc is already fairly close (16–36% cut), and beyond 20 minutes (`combined` only) the cut is 29%.

TransLoc's error is almost all lateness. On average the bus arrives 1.4 to 1.7 min later than TransLoc says when it is under 2 min away, and 6.7 to 7.3 min later when it is 10–20 min away. That steady, growing optimism is what the lookup table in section 1 corrects.

## 3. How often the prediction is within 2 minutes of the actual arrival

| Dataset (best model) | TransLoc's ETA | TransLoc | Model | Gain |
| --- | --- | --- | --- | --- |
| `bus` (HistGradientBoostingRegressor) | under 2 min | 70% | 79% | 79 − 70 = +9 pts |
|  | 2–5 min | 39% | 66% | 66 − 39 = +27 pts |
|  | 5–10 min | 23% | 52% | 52 − 23 = +29 pts |
|  | 10–20 min | 9% | 43% | 43 − 9 = +34 pts |
|  | **all** | 31% | 58% | 58 − 31 = +27 pts |
| `route` (ExtraTreesRegressor) | under 2 min | 71% | 81% | 81 − 71 = +10 pts |
|  | 2–5 min | 39% | 64% | 64 − 39 = +25 pts |
|  | 5–10 min | 17% | 51% | 51 − 17 = +34 pts |
|  | 10–20 min | 8% | 31% | 31 − 8 = +23 pts |
|  | **all** | 29% | 55% | 55 − 29 = +26 pts |
| `combined` (XGBRegressor) | under 2 min | 82% | 88% | 88 − 82 = +6 pts |
|  | 2–5 min | 46% | 75% | 75 − 46 = +29 pts |
|  | 5–10 min | 20% | 48% | 48 − 20 = +28 pts |
|  | 10–20 min | 13% | 44% | 44 − 13 = +31 pts |
|  | 20+ min | 11% | 26% | 26 − 11 = +15 pts |
|  | **all** | 41% | 63% | 63 − 41 = +22 pts |

## 4. The worst predictions

Average error hides the misses riders remember. "Bus earlier than predicted" counts predictions where the bus arrived more than 5 minutes before the predicted time, so a rider who trusted it would miss it.

| Dataset | Prediction | Median error | 95th percentile | 99th percentile | Off by > 5 min | Off by > 10 min | Bus > 5 min earlier than predicted |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bus` | TransLoc as-is | 239 s | 711 s | 854 s | 41.3% | 9.7% | 0.0% |
|  | Lookup table | 155 s | 472 s | 599 s | 17.8% | 1.0% | 15.4% |
|  | Best model (HistGradientBoostingRegressor) | 102 s | 323 s | 496 s | 6.8% | 0.2% | 5.5% |
| `route` | TransLoc as-is | 244 s | 758 s | 923 s | 41.9% | 11.5% | 0.0% |
|  | Lookup table | 139 s | 437 s | 583 s | 16.0% | 0.7% | 9.6% |
|  | Best model (ExtraTreesRegressor) | 106 s | 375 s | 505 s | 9.9% | 0.2% | 7.6% |
| `combined` | TransLoc as-is | 181 s | 787 s | 1102 s | 34.1% | 11.0% | 0.2% |
|  | Lookup table | 115 s | 531 s | 765 s | 18.7% | 3.2% | 10.0% |
|  | Best model (XGBRegressor) | 77 s | 522 s | 882 s | 12.9% | 3.3% | 3.8% |

- **On `bus` and `route` the best model also shrinks the tails.** Compared with TransLoc, predictions off by more than 10 minutes drop from 9.7% to 0.2% on `bus` and from 11.5% to 0.2% on `route`. On `combined` its worst 1% are worse than the lookup table's: a 99th-percentile error of 882 s against 765 s (TransLoc: 1102 s).
- **Correcting TransLoc's optimism moves some errors to the costly side.** The bus arrives more than 5 minutes earlier than predicted on 0.0–0.2% of TransLoc's predictions, 9.6–15.4% of the lookup table's and 3.8–7.6% of the best models'. TransLoc's errors mostly make riders wait. The corrections' big misses more often make them miss the bus, and the lookup table, which adds the average delay even when a bus is running on time, is the worst on this measure.

## 5. By route, and pooled vs single-route models

- **The gain is uneven by route.** On the `combined` test days, the best model's error by route is Gold 298 → 228 s (23%), Green 290 → 126 s (57%), Red 84 → 80 s (5%). Red's feed only gives next-stop ETAs, so TransLoc is already close there.
- **Pooling routes helped, even for a single bus.** On identical test rows, the `combined` model beat the models trained on one route or one bus: on Green's test day 126 s vs 136 s for the best `route` model, and on bus #3's rows 114 s vs 127 s for the best `bus` model. `combined` has five training days instead of one or two. This rests on one test day, so treat it as a first sign.

## 6. All models and baselines

15 tuned models (5 per dataset) and 4 baselines per dataset, sorted by test MAE, so each dataset's first row is its best model. Tuning MAE and every number here are also in `summary.csv`.

| Dataset | Family | Model | Test R² | Test MAE (s) | Test RMSE (s) | n_test |
|---|---|---|---|---|---|---|
| bus | lazy | HistGradientBoostingRegressor | 0.504 | 127.4 | 163.5 | 7,536 |
| bus | lazy | ExtraTreesRegressor | 0.386 | 138.7 | 181.9 | 7,536 |
| bus | lazy | LinearSVR | 0.332 | 141.6 | 189.8 | 7,536 |
| bus | xgboost | XGBRegressor | 0.380 | 143.1 | 182.9 | 7,536 |
| bus | nn | MLP | -0.584 | 226.5 | 292.2 | 7,536 |
| bus | baseline | Lookup table (ETA deciles) | 0.021 | 183.4 | 229.7 | 7,536 |
| bus | baseline | Straight line in ETA | 0.002 | 188.5 | 232.0 | 7,536 |
| bus | baseline | Train mean | -0.226 | 218.0 | 257.1 | 7,536 |
| bus | baseline | TransLoc as-is (delay=0) | -1.343 | 278.7 | 355.4 | 7,536 |
| route | lazy | ExtraTreesRegressor | 0.457 | 135.6 | 179.3 | 16,998 |
| route | xgboost | XGBRegressor | 0.449 | 139.2 | 180.6 | 16,998 |
| route | lazy | LGBMRegressor | 0.505 | 139.9 | 171.1 | 16,998 |
| route | lazy | AdaBoostRegressor | 0.360 | 157.7 | 194.7 | 16,998 |
| route | nn | MLP | 0.365 | 158.0 | 193.8 | 16,998 |
| route | baseline | Lookup table (ETA deciles) | 0.206 | 173.0 | 216.8 | 16,998 |
| route | baseline | Straight line in ETA | 0.194 | 176.0 | 218.3 | 16,998 |
| route | baseline | Train mean | -0.087 | 212.2 | 253.6 | 16,998 |
| route | baseline | TransLoc as-is (delay=0) | -1.335 | 290.4 | 371.7 | 16,998 |
| combined | xgboost | XGBRegressor | 0.302 | 142.5 | 232.8 | 29,141 |
| combined | lazy | GradientBoostingRegressor | 0.244 | 156.6 | 242.2 | 29,141 |
| combined | nn | MLP | 0.181 | 176.1 | 252.2 | 29,141 |
| combined | lazy | OrthogonalMatchingPursuit | 0.089 | 191.3 | 265.9 | 29,141 |
| combined | lazy | ElasticNet | 0.136 | 200.7 | 259.0 | 29,141 |
| combined | baseline | Lookup table (ETA deciles) | 0.181 | 178.4 | 252.2 | 29,141 |
| combined | baseline | Straight line in ETA | 0.143 | 193.7 | 258.0 | 29,141 |
| combined | baseline | Train mean | -0.084 | 240.0 | 290.1 | 29,141 |
| combined | baseline | TransLoc as-is (delay=0) | -0.724 | 255.5 | 365.9 | 29,141 |
