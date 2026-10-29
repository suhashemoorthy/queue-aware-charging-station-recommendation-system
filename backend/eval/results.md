# Ranker comparison (simulation)

300 trials per demand level, 12 drivers choosing at once, seed 7. See the docstring in `eval/compare_rankers.py` for the assumptions.


### Demand level: low

| algorithm | mean total (min) | median | p95 | mean wait | wait > 30 min | mean cost (INR) | max drivers on one station |
|---|---|---|---|---|---|---|---|
| random | 101.3 | 65.5 | 300.3 | 18.6 | 15.6% | 298 | 17% |
| nearest | 185.0 | 116.7 | 549.9 | 105.8 | 58.2% | 289 | 41% |
| max_availability | 169.7 | 114.5 | 487.7 | 91.4 | 56.5% | 289 | 44% |
| fastest_rated_kw | 98.8 | 76.1 | 240.4 | 54.8 | 52.1% | 367 | 53% |
| cheapest | 899.0 | 865.1 | 1835.9 | 749.3 | 91.1% | 202 | 96% |
| naive_total_time | 72.0 | 58.5 | 154.1 | 29.6 | 38.4% | 364 | 45% |
| legacy_ranker (before) | 83.6 | 70.1 | 188.8 | 36.2 | 44.8% | 353 | 46% |
| TOPSIS (alternative) | 75.2 | 62.8 | 165.1 | 28.8 | 37.9% | 320 | 39% |
| generalized_cost (alternative) | 70.3 | 56.3 | 150.0 | 24.2 | 32.6% | 315 | 37% |
| new_ranker (after) | 68.4 | 51.9 | 153.6 | 26.0 | 34.2% | 343 | 35% |
| new_ranker + holds (implemented) | 44.2 | 43.4 | 59.9 | 0.7 | 0.6% | 339 | 18% |

Paired difference in mean total time versus `new_ranker (after)` (positive = that algorithm is slower), 95% CI over trials:

| algorithm | mean diff (min) | 95% CI | trials where reference was faster |
|---|---|---|---|
| random | +32.9 | [+28.7, +37.0] | 85% |
| nearest | +116.6 | [+108.2, +125.1] | 98% |
| max_availability | +101.3 | [+93.1, +109.6] | 98% |
| fastest_rated_kw | +30.4 | [+28.3, +32.6] | 98% |
| cheapest | +830.7 | [+805.4, +855.9] | 100% |
| naive_total_time | +3.6 | [+1.8, +5.5] | 66% |
| legacy_ranker (before) | +15.3 | [+12.6, +17.9] | 81% |
| TOPSIS (alternative) | +6.9 | [+5.7, +8.1] | 82% |
| generalized_cost (alternative) | +2.0 | [+0.7, +3.2] | 65% |
| new_ranker + holds (implemented) | -24.2 | [-25.8, -22.6] | 0% |

### Demand level: medium

| algorithm | mean total (min) | median | p95 | mean wait | wait > 30 min | mean cost (INR) | max drivers on one station |
|---|---|---|---|---|---|---|---|
| random | 117.7 | 75.4 | 350.3 | 33.2 | 28.5% | 303 | 18% |
| nearest | 204.1 | 133.3 | 572.8 | 123.4 | 64.9% | 292 | 39% |
| max_availability | 183.8 | 125.2 | 527.6 | 103.6 | 59.8% | 294 | 46% |
| fastest_rated_kw | 107.2 | 82.6 | 256.8 | 63.2 | 56.2% | 372 | 53% |
| cheapest | 961.1 | 929.7 | 1947.0 | 809.5 | 94.2% | 205 | 96% |
| naive_total_time | 79.6 | 64.7 | 182.7 | 36.5 | 43.8% | 365 | 50% |
| legacy_ranker (before) | 110.2 | 84.7 | 264.7 | 57.1 | 53.8% | 343 | 51% |
| TOPSIS (alternative) | 85.8 | 72.7 | 190.0 | 37.5 | 44.7% | 327 | 42% |
| generalized_cost (alternative) | 71.4 | 56.7 | 153.8 | 24.5 | 32.8% | 320 | 38% |
| new_ranker (after) | 74.8 | 56.4 | 175.7 | 31.5 | 38.3% | 347 | 39% |
| new_ranker + holds (implemented) | 46.5 | 45.1 | 67.1 | 1.5 | 1.6% | 343 | 19% |

Paired difference in mean total time versus `new_ranker (after)` (positive = that algorithm is slower), 95% CI over trials:

| algorithm | mean diff (min) | 95% CI | trials where reference was faster |
|---|---|---|---|
| random | +42.8 | [+38.2, +47.4] | 88% |
| nearest | +129.2 | [+120.8, +137.6] | 99% |
| max_availability | +109.0 | [+99.7, +118.2] | 97% |
| fastest_rated_kw | +32.4 | [+29.4, +35.5] | 94% |
| cheapest | +886.3 | [+858.9, +913.7] | 100% |
| naive_total_time | +4.8 | [+2.1, +7.4] | 61% |
| legacy_ranker (before) | +35.3 | [+29.2, +41.4] | 88% |
| TOPSIS (alternative) | +11.0 | [+8.7, +13.3] | 78% |
| generalized_cost (alternative) | -3.4 | [-5.8, -1.0] | 55% |
| new_ranker + holds (implemented) | -28.4 | [-30.5, -26.2] | 0% |

### Demand level: high

| algorithm | mean total (min) | median | p95 | mean wait | wait > 30 min | mean cost (INR) | max drivers on one station |
|---|---|---|---|---|---|---|---|
| random | 133.2 | 90.9 | 382.9 | 49.5 | 42.7% | 302 | 18% |
| nearest | 226.5 | 160.6 | 608.7 | 148.9 | 74.3% | 296 | 40% |
| max_availability | 262.7 | 169.2 | 865.3 | 178.2 | 71.1% | 295 | 59% |
| fastest_rated_kw | 114.4 | 91.7 | 258.4 | 70.3 | 64.5% | 370 | 52% |
| cheapest | 995.6 | 952.7 | 1964.0 | 844.3 | 96.6% | 204 | 96% |
| naive_total_time | 91.3 | 73.8 | 211.0 | 47.1 | 50.1% | 361 | 58% |
| legacy_ranker (before) | 190.2 | 132.1 | 543.3 | 123.5 | 66.8% | 320 | 62% |
| TOPSIS (alternative) | 130.7 | 102.0 | 324.9 | 75.7 | 58.6% | 322 | 57% |
| generalized_cost (alternative) | 76.1 | 60.2 | 168.7 | 28.0 | 31.2% | 321 | 44% |
| new_ranker (after) | 86.3 | 65.4 | 212.7 | 40.9 | 42.1% | 344 | 47% |
| new_ranker + holds (implemented) | 50.6 | 48.4 | 76.6 | 4.0 | 3.7% | 342 | 22% |

Paired difference in mean total time versus `new_ranker (after)` (positive = that algorithm is slower), 95% CI over trials:

| algorithm | mean diff (min) | 95% CI | trials where reference was faster |
|---|---|---|---|
| random | +46.9 | [+41.1, +52.7] | 86% |
| nearest | +140.2 | [+131.5, +149.0] | 99% |
| max_availability | +176.4 | [+154.6, +198.2] | 95% |
| fastest_rated_kw | +28.2 | [+24.1, +32.2] | 82% |
| cheapest | +909.4 | [+883.4, +935.3] | 100% |
| naive_total_time | +5.0 | [+1.5, +8.6] | 58% |
| legacy_ranker (before) | +103.9 | [+88.9, +118.9] | 93% |
| TOPSIS (alternative) | +44.4 | [+39.1, +49.7] | 88% |
| generalized_cost (alternative) | -10.1 | [-14.0, -6.3] | 41% |
| new_ranker + holds (implemented) | -35.7 | [-39.1, -32.3] | 1% |