# Experimental Comparison of EV Charging Station Ranking Algorithms

## Abstract

This report evaluates the implemented station-selection algorithms in the EV Charge Optimizer. It does not evaluate business-entity matching: the inspected project has no S1/S2/S3 entity datasets or labeled duplicate pairs. Instead, the repository's existing paired simulation compares 10 station rankers and reservation-aware selection across three synthetic demand levels. The current weighted ranker is competitive at low demand, while generalized cost ranks better by mean realized total time at medium and high demand in this simulation. Reservation-aware selection has substantially lower simulated waits, but it is a different system mode that adds reservation coordination. All results are model-generated and should not be interpreted as field measurements.

## 1. Introduction and Objective

The objective is to compare the project's current recommendation model with implemented ranking alternatives using the same station snapshots, generated drivers, candidate filter, and simulated outcome model. Since this repository is an EV charging application, entity-match precision, recall, F1/F0.5, false positives/negatives, and blocking recall are not applicable and are not fabricated.

## 2. Existing and Proposed Systems

The application loads a validated station CSV into typed `Station` records. Connector names are normalized before compatibility filtering; unavailable stations are removed; candidates are restricted to a 10-km origin radius. Route distances/times use the study road graph or straight-line estimate, except when verified coordinates enable configured routing. Features include expected travel, wait, battery-aware charge duration, cost, availability, reliability, and rating. The current model uses weighted scoring and bounded top-k selection; it is not a learned classifier and has no training stage.

Candidate-generation algorithms are shared by the evaluated rankers: connector/status filtering plus origin-radius filtering using a precomputed route table. This experiment measures candidate counts and time for that common stage. It does not compare entity-resolution blocking methods.

The current system (Mode A) is `new_ranker (after)`. Comparators include the retained `legacy_ranker (before)`, TOPSIS, generalized cost, rated-power total-time, nearest, max availability, fastest rated charger, cheapest tariff, and deterministic random selection. `new_ranker + holds (implemented)` is reported separately because it adds stateful reservation/queue coordination rather than changing only the scoring rule.

## 3. Dataset and Experimental Configuration

The sole dataset is `coimbatore_ev_stations_replica_demo_synthetic.csv`: 47 station records and 44 CSV fields. It is explicitly synthetic demonstration state and uses approximate coordinates. No entity labels or train/validation/test splits exist. Phone/contact values and individual records are not reproduced in this report.

**Table 1. Dataset and experimental configuration.**

| Item | Value |
|---|---|
| Station records | 47 |
| CSV fields | 44 |
| Labeled entity-match pairs | None; matching metrics not applicable |
| Train/validation/test split | None; no supervised labels |
| Demand scenarios | low, medium, high |
| Trials per scenario | 300 |
| Drivers per trial | 12 |
| Random seed | 7 |
| Machine | Intel(R) Core(TM) i5-10210U CPU @ 1.60GHz; 8 logical CPUs; 7253.9 MB RAM (Linux-7.0.0-27-generic-x86_64-with-glibc2.43) |
| Software | Python 3.11.16; FastAPI 0.116.1; Pydantic 2.11.7; Uvicorn 0.35.0 |

## 4. Methodology

Each trial generates one station-state snapshot and a fixed set of drivers; every algorithm sees that paired input. The outcome simulator applies noisy arrival times, FIFO queues, generated background traffic, and battery-aware service durations. The ranking code does not know those random outcomes. Seeds are derived deterministically from the configured seed, demand level, and trial index. The simulation's service-time model shares the battery-aware charge estimator used by the current ranker, a known modeling asymmetry against rated-kW baselines.

Shared preprocessing time covers station loading and route-table construction. Candidate generation is timed around the actual connector/status/radius stage, excluding that route-table precomputation. Picker time is measured around each algorithm's selection call, including its in-call feature preparation; feature extraction is not separately isolated. Wall time covers the complete simulation for one demand level. Peak RSS is the process high-water mark, not an isolated per-algorithm measurement. No runtime significance test was conducted. Training time is not applicable.

## 5. Candidate Generation

**Table 2. Shared candidate-generation performance.**

| Demand | Requests | Candidate instances | Reduction | Time (s) | Mean (ms/request) | Recall |
|---|---|---|---|---|---|---|
| low | 39600 | 1037432 | 44.3% | 4.78 | 0.12 | N/A (no labeled pairs) |
| medium | 39600 | 1040259 | 44.1% | 6.48 | 0.16 | N/A (no labeled pairs) |
| high | 39600 | 1044923 | 43.9% | 17.30 | 0.44 | N/A (no labeled pairs) |

Reduction is relative to evaluating every station for every algorithm-driver request: $1 - candidates / (requests × stations)$. Candidate recall cannot be computed without ground-truth eligible stations or labeled pairs; the radius/connector rules may intentionally exclude valid choices.

## 6. Matching Accuracy

**Table 3. Entity-matching accuracy metrics.**

| Metric | Result | Reason |
|---|---|---|
| Precision, recall, F1, F0.5 | N/A | No labeled entity pairs or match predictions |
| TP, FP, FN | N/A | No ground-truth duplicate labels |
| Blocking recall | N/A | No known true-match pairs to test against |

These are unavailable rather than zero. The project instead evaluates simulated travel, wait, and charge outcomes.

## 7. Results

**Table 4. Simulated recommendation outcome comparison.** Values are means unless labeled otherwise; total and wait are minutes, cost is INR, and station share is the maximum fraction of trial drivers assigned to one station.

| Demand | Algorithm | Mean total (min) | Median (min) | P95 (min) | Mean wait (min) | Wait >30 min | Mean cost (INR) | Max station share |
|---|---|---|---|---|---|---|---|---|
| low | random | 101.25 | 65.53 | 300.31 | 18.61 | 15.6% | 298 | 17% |
| low | nearest | 184.99 | 116.67 | 549.92 | 105.76 | 58.2% | 289 | 41% |
| low | max_availability | 169.69 | 114.50 | 487.65 | 91.42 | 56.5% | 289 | 44% |
| low | fastest_rated_kw | 98.78 | 76.13 | 240.43 | 54.78 | 52.1% | 367 | 53% |
| low | cheapest | 899.03 | 865.13 | 1835.90 | 749.31 | 91.1% | 202 | 96% |
| low | naive_total_time | 71.97 | 58.51 | 154.12 | 29.61 | 38.4% | 364 | 45% |
| low | legacy_ranker (before) | 83.62 | 70.15 | 188.80 | 36.22 | 44.8% | 353 | 46% |
| low | TOPSIS (alternative) | 75.25 | 62.75 | 165.08 | 28.77 | 37.9% | 320 | 39% |
| low | generalized_cost (alternative) | 70.31 | 56.30 | 149.98 | 24.23 | 32.6% | 315 | 37% |
| low | new_ranker (after) | 68.35 | 51.92 | 153.61 | 25.99 | 34.2% | 343 | 35% |
| low | new_ranker + holds (implemented) | 44.19 | 43.36 | 59.88 | 0.67 | 0.6% | 339 | 18% |
| medium | random | 117.66 | 75.41 | 350.31 | 33.24 | 28.5% | 303 | 18% |
| medium | nearest | 204.05 | 133.30 | 572.76 | 123.42 | 64.9% | 292 | 39% |
| medium | max_availability | 183.81 | 125.24 | 527.59 | 103.57 | 59.8% | 294 | 46% |
| medium | fastest_rated_kw | 107.25 | 82.63 | 256.77 | 63.16 | 56.2% | 372 | 53% |
| medium | cheapest | 961.11 | 929.69 | 1947.02 | 809.50 | 94.2% | 205 | 96% |
| medium | naive_total_time | 79.59 | 64.69 | 182.72 | 36.54 | 43.8% | 365 | 50% |
| medium | legacy_ranker (before) | 110.16 | 84.73 | 264.69 | 57.13 | 53.8% | 343 | 51% |
| medium | TOPSIS (alternative) | 85.81 | 72.67 | 190.02 | 37.46 | 44.7% | 327 | 42% |
| medium | generalized_cost (alternative) | 71.41 | 56.70 | 153.80 | 24.48 | 32.8% | 320 | 38% |
| medium | new_ranker (after) | 74.83 | 56.39 | 175.74 | 31.47 | 38.3% | 347 | 39% |
| medium | new_ranker + holds (implemented) | 46.47 | 45.06 | 67.10 | 1.51 | 1.6% | 343 | 19% |
| high | random | 133.16 | 90.90 | 382.90 | 49.54 | 42.7% | 302 | 18% |
| high | nearest | 226.51 | 160.60 | 608.73 | 148.85 | 74.3% | 296 | 40% |
| high | max_availability | 262.66 | 169.16 | 865.34 | 178.18 | 71.1% | 295 | 59% |
| high | fastest_rated_kw | 114.45 | 91.65 | 258.38 | 70.29 | 64.5% | 370 | 52% |
| high | cheapest | 995.63 | 952.73 | 1964.04 | 844.29 | 96.6% | 204 | 96% |
| high | naive_total_time | 91.30 | 73.84 | 210.99 | 47.08 | 50.1% | 361 | 58% |
| high | legacy_ranker (before) | 190.19 | 132.08 | 543.32 | 123.50 | 66.8% | 320 | 62% |
| high | TOPSIS (alternative) | 130.65 | 102.01 | 324.85 | 75.71 | 58.6% | 322 | 57% |
| high | generalized_cost (alternative) | 76.12 | 60.16 | 168.73 | 27.95 | 31.2% | 321 | 44% |
| high | new_ranker (after) | 86.27 | 65.44 | 212.67 | 40.92 | 42.1% | 344 | 47% |
| high | new_ranker + holds (implemented) | 50.56 | 48.41 | 76.59 | 3.96 | 3.7% | 342 | 22% |

**Table 5. Runtime and resource comparison.** Preprocessing is shared startup time; feature extraction is included in picker time and not isolated. Wall time and peak RSS are shared across algorithms for each scenario and repeated for traceability.

| Demand | Algorithm | Preprocess shared (s) | Picker total (s) | Mean picker (µs) | Calls/s | Scenario wall (s) | Peak RSS (MB) |
|---|---|---|---|---|---|---|---|
| low | random | 0.0214 | 0.0226 | 6.3 | 159215 | 14.03 | 80.34 |
| low | nearest | 0.0214 | 0.0228 | 6.3 | 157979 | 14.03 | 80.34 |
| low | max_availability | 0.0214 | 0.0467 | 13.0 | 77093 | 14.03 | 80.34 |
| low | fastest_rated_kw | 0.0214 | 0.0245 | 6.8 | 146795 | 14.03 | 80.34 |
| low | cheapest | 0.0214 | 0.0240 | 6.7 | 149825 | 14.03 | 80.34 |
| low | naive_total_time | 0.0214 | 0.0313 | 8.7 | 115077 | 14.03 | 80.34 |
| low | legacy_ranker (before) | 0.0214 | 0.6645 | 184.6 | 5417 | 14.03 | 80.34 |
| low | TOPSIS (alternative) | 0.0214 | 2.7575 | 766.0 | 1306 | 14.03 | 80.34 |
| low | generalized_cost (alternative) | 0.0214 | 0.2788 | 77.5 | 12910 | 14.03 | 80.34 |
| low | new_ranker (after) | 0.0214 | 0.8755 | 243.2 | 4112 | 14.03 | 80.34 |
| low | new_ranker + holds (implemented) | 0.0214 | 0.9439 | 262.2 | 3814 | 14.03 | 80.34 |
| medium | random | 0.0214 | 0.0294 | 8.2 | 122635 | 18.27 | 80.34 |
| medium | nearest | 0.0214 | 0.0317 | 8.8 | 113490 | 18.27 | 80.34 |
| medium | max_availability | 0.0214 | 0.0650 | 18.1 | 55375 | 18.27 | 80.34 |
| medium | fastest_rated_kw | 0.0214 | 0.0344 | 9.6 | 104521 | 18.27 | 80.34 |
| medium | cheapest | 0.0214 | 0.0331 | 9.2 | 108663 | 18.27 | 80.34 |
| medium | naive_total_time | 0.0214 | 0.0445 | 12.4 | 80884 | 18.27 | 80.34 |
| medium | legacy_ranker (before) | 0.0214 | 0.8678 | 241.1 | 4148 | 18.27 | 80.34 |
| medium | TOPSIS (alternative) | 0.0214 | 3.4610 | 961.4 | 1040 | 18.27 | 80.34 |
| medium | generalized_cost (alternative) | 0.0214 | 0.3707 | 103.0 | 9711 | 18.27 | 80.34 |
| medium | new_ranker (after) | 0.0214 | 1.1359 | 315.5 | 3169 | 18.27 | 80.34 |
| medium | new_ranker + holds (implemented) | 0.0214 | 1.1702 | 325.0 | 3076 | 18.27 | 80.34 |
| high | random | 0.0214 | 0.0804 | 22.3 | 44778 | 48.53 | 84.00 |
| high | nearest | 0.0214 | 0.0887 | 24.6 | 40604 | 48.53 | 84.00 |
| high | max_availability | 0.0214 | 0.1739 | 48.3 | 20698 | 48.53 | 84.00 |
| high | fastest_rated_kw | 0.0214 | 0.0976 | 27.1 | 36881 | 48.53 | 84.00 |
| high | cheapest | 0.0214 | 0.0965 | 26.8 | 37288 | 48.53 | 84.00 |
| high | naive_total_time | 0.0214 | 0.1204 | 33.4 | 29905 | 48.53 | 84.00 |
| high | legacy_ranker (before) | 0.0214 | 2.2771 | 632.5 | 1581 | 48.53 | 84.00 |
| high | TOPSIS (alternative) | 0.0214 | 9.1891 | 2552.5 | 392 | 48.53 | 84.00 |
| high | generalized_cost (alternative) | 0.0214 | 0.9800 | 272.2 | 3673 | 48.53 | 84.00 |
| high | new_ranker (after) | 0.0214 | 2.9911 | 830.9 | 1204 | 48.53 | 84.00 |
| high | new_ranker + holds (implemented) | 0.0214 | 3.0749 | 854.1 | 1171 | 48.53 | 84.00 |

No preprocessing or training time is attributed to an individual ranker: candidate inputs and feature preparation are shared. The CSV includes every algorithm/scenario outcome plus N/A values for unsupported entity-matching metrics.

**Table 6. Proposed ranker versus generalized-cost alternative.** Difference is alternative minus current mean trial total time; positive means the current ranker was faster. Relative time improvement is `(current mean - alternative mean) / current mean`; positive values favor generalized cost. The 95% interval is a normal-approximation interval over paired trial means. Picker-time percentage compares current selection time with the legacy ranker's measured selection time and is descriptive only.

| Demand | Comparator | Paired difference (min) | 95% interval (min) | Trials current faster | Relative time improvement | Picker-time reduction vs legacy | Runtime inference |
|---|---|---|---|---|---|---|---|
| low | generalized_cost (alternative) | 1.96 | [0.71, 3.20] | 65.0% | -2.9% | -31.7% | Runtime difference is descriptive only; no repeated timing test. |
| medium | generalized_cost (alternative) | -3.42 | [-5.81, -1.03] | 54.7% | +4.6% | -30.9% | Runtime difference is descriptive only; no repeated timing test. |
| high | generalized_cost (alternative) | -10.15 | [-13.98, -6.32] | 40.7% | +11.8% | -31.4% | Runtime difference is descriptive only; no repeated timing test. |

## 8. Discussion

The results are scenario-specific, not universal model rankings. Compare the mean and tail outcomes together: the system with the lowest mean may not minimize high-wait risk or cost. Reservation-aware results should not be attributed to ranking alone because reservations reduce herding by informing later simulated drivers of earlier selections. Current-versus-alternative paired intervals describe simulated outcome differences; they do not establish external validity.

At low demand, **new_ranker (after)** had the lowest mean simulated total time among pure rankers (68.35 min); **random** had the lowest mean picker time (6.3 µs/call). Reservation-aware selection reduced mean wait from 25.99 to 0.67 min (97.4%) in this simulator, but adds coordination and is not a pure ranker.

At medium demand, **generalized_cost (alternative)** had the lowest mean simulated total time among pure rankers (71.41 min); **random** had the lowest mean picker time (8.2 µs/call). Reservation-aware selection reduced mean wait from 31.47 to 1.51 min (95.2%) in this simulator, but adds coordination and is not a pure ranker.

At high demand, **generalized_cost (alternative)** had the lowest mean simulated total time among pure rankers (76.12 min); **random** had the lowest mean picker time (22.3 µs/call). Reservation-aware selection reduced mean wait from 40.92 to 3.96 min (90.3%) in this simulator, but adds coordination and is not a pure ranker.

All alternatives consume the same candidate list, so candidate generation is not an algorithm-level differentiator here. The experiment does not establish whether the radius or connector filter loses true matches; it establishes only how many station candidates pass under the generated inputs. The random baseline is deterministic for reproducibility, not a learned stochastic policy.

## 9. Threats to Validity and Limitations

- The 47-row dataset contains synthetic station state and approximate coordinates, not measured live outcomes.
- Trial inputs, traffic, queue arrivals, and service durations are simulated under fixed assumptions; measured times in this report are program execution timings on one machine, while trip outcomes are simulated minutes.
- The outcome service duration uses the current battery-aware charging model, favoring methods that optimize that same estimate.
- The experiment has no entity-matching labels, no train/test split, no false-match accounting, and no language/transliteration evaluation.
- Runtime measurements are collected in a single process and are sensitive to scheduling, cache state, and Python overhead; no statistical runtime claim is made.
- Peak RSS is a process-level high-water mark and cannot be assigned fairly to individual rankers.
- Synthetic demand and five configured origins may not represent fleet behavior or geographic diversity.

## 10. Conclusion

The repository supports a reproducible comparison of implemented EV station rankers, not the requested business-entity matching experiment. The report therefore preserves the actual task and explicitly marks entity-match metrics unavailable. Among pure rankers, recommendation should be selected using the measured mean/tail-time and cost trade-offs under the intended demand conditions; reservation-aware selection is promising in this simulation but requires real occupancy/arrival validation before deployment claims.

## Reproducibility

Run from the backend directory: `python -m eval.generate_research_report`. Parameters and environment are recorded in `experiment_config.json`; per-scenario checkpoints and progress logs are stored in `reports/`. See `reproduce_experiments.md` for the full procedure.
