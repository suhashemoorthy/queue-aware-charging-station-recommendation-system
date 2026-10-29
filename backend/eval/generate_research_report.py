"""Run and report the existing EV-station ranker simulation study.

Run from the backend directory with:
    python -m eval.generate_research_report
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
from time import perf_counter

from app.repository import DATA_FILE, StationRepository
from eval import compare_rankers as study


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REFERENCE = "new_ranker (after)"
BASELINE = "legacy_ranker (before)"
LOG = REPORTS / "experiment.log"

CSV_FIELDS = [
    "experiment_id", "demand_level", "algorithm", "trials", "drivers_per_trial",
    "mean_total_min", "median_total_min", "p95_total_min", "mean_wait_min",
    "wait_over_30_min_pct", "mean_cost_inr", "mean_max_station_share_pct",
    "candidate_generation_s_shared", "candidate_generation_calls_shared",
    "candidate_instances_shared", "possible_station_evaluations_shared",
    "candidate_reduction_pct_shared", "candidate_recall",
    "picker_calls", "picker_time_s", "picker_mean_us", "picker_calls_per_s",
    "simulation_wall_s_shared", "simulation_drivers_per_s_shared",
    "process_peak_rss_mb_cumulative", "precision", "recall", "f1", "f0_5",
    "true_positives", "false_positives", "false_negatives", "training_time_s",
    "preprocessing_time_s_shared", "feature_extraction_time_s",
]


def package_version(name):
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "not installed"


def system_memory_mb():
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


def cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "not exposed by Python"


def peak_rss_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value / 1024, 2) if sys.platform != "darwin" else round(value / 1024**2, 2)


def environment_info():
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "cpu_model": cpu_model(),
        "system_memory_mb": system_memory_mb(),
        "python": platform.python_version(),
        "fastapi": package_version("fastapi"),
        "pydantic": package_version("pydantic"),
        "uvicorn": package_version("uvicorn"),
        "reportlab": package_version("reportlab"),
    }


def paired_difference(values, reference):
    differences = [value - base for value, base in zip(values, reference)]
    if not differences:
        return None
    mean = statistics.fmean(differences)
    if len(differences) < 2:
        return {"mean": mean, "low": None, "high": None, "reference_faster_pct": None}
    half = 1.96 * statistics.stdev(differences) / math.sqrt(len(differences))
    return {
        "mean": mean,
        "low": mean - half,
        "high": mean + half,
        "reference_faster_pct": 100 * sum(value > 0 for value in differences) / len(differences),
    }


def time_profiled_run(trials, users, seed, demand):
    picker_times = {}
    original_algorithms = study.ALGORITHMS.copy()
    original_pick_new = study.pick_new
    original_candidates = study.RouteTable.candidates
    candidate_profile = {"seconds": 0.0, "calls": 0, "instances": 0}

    def time_picker(name, function):
        picker_times[name] = {"seconds": 0.0, "calls": 0}

        def timed(*args, **kwargs):
            start = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                picker_times[name]["seconds"] += perf_counter() - start
                picker_times[name]["calls"] += 1

        return timed

    def timed_candidates(route_table, user, snapshot):
        start = perf_counter()
        try:
            candidates = original_candidates(route_table, user, snapshot)
        finally:
            candidate_profile["seconds"] += perf_counter() - start
            candidate_profile["calls"] += 1
        candidate_profile["instances"] += len(candidates)
        return candidates

    try:
        for name, function in original_algorithms.items():
            if name == REFERENCE:
                study.ALGORITHMS[name] = time_picker(name, original_pick_new)
            else:
                study.ALGORITHMS[name] = time_picker(name, function)
        study.pick_new = time_picker(study.HOLDS_NAME, original_pick_new)
        study.RouteTable.candidates = timed_candidates
        start = perf_counter()
        result = study.run(trials, users, seed, demand)
        wall_seconds = perf_counter() - start
    finally:
        study.ALGORITHMS.clear()
        study.ALGORITHMS.update(original_algorithms)
        study.pick_new = original_pick_new
        study.RouteTable.candidates = original_candidates

    names, per_trial, totals, waits, costs, shares = result
    summaries = {}
    for name in names:
        times = totals[name]
        wait_values = waits[name]
        stats = picker_times[name]
        summaries[name] = {
            "mean_total_min": statistics.fmean(times),
            "median_total_min": statistics.median(times),
            "p95_total_min": study.pct(times, 0.95),
            "mean_wait_min": statistics.fmean(wait_values),
            "wait_over_30_min_pct": 100 * sum(value > 30 for value in wait_values) / len(wait_values),
            "mean_cost_inr": statistics.fmean(costs[name]),
            "mean_max_station_share_pct": 100 * statistics.fmean(shares[name]),
            "picker_seconds": stats["seconds"],
            "picker_calls": stats["calls"],
            "picker_mean_us": 1e6 * stats["seconds"] / stats["calls"] if stats["calls"] else None,
            "picker_calls_per_s": stats["calls"] / stats["seconds"] if stats["seconds"] else None,
            "per_trial_mean_total_min": per_trial[name],
        }

    station_count = len(StationRepository().all())
    possible = candidate_profile["calls"] * station_count
    candidate_profile.update({
        "possible_station_evaluations": possible,
        "reduction_pct": 100 * (1 - candidate_profile["instances"] / possible) if possible else None,
    })
    profile = {
        "summaries": summaries,
        "candidate_generation": candidate_profile,
        "wall_seconds": wall_seconds,
        "simulation_drivers_per_s": trials * users * len(names) / wall_seconds,
        "process_peak_rss_mb_cumulative": peak_rss_mb(),
    }
    return profile


def checkpoint_write(path, experiment_id, completed):
    path.write_text(json.dumps({
        "experiment_id": experiment_id,
        "completed": completed,
    }, indent=2), encoding="utf-8")


def load_checkpoint(path, experiment_id):
    if not path.exists():
        return {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("experiment_id") == experiment_id:
            return saved.get("completed", {})
        logging.info("Ignoring checkpoint from a different experiment configuration.")
    except (OSError, json.JSONDecodeError):
        logging.exception("Could not read experiment checkpoint; starting fresh.")
    return {}


def write_csv(path, experiment_id, completed, trials, users, preprocessing_seconds):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for demand, profile in completed.items():
            candidate = profile["candidate_generation"]
            for algorithm, summary in profile["summaries"].items():
                writer.writerow({
                    "experiment_id": experiment_id,
                    "demand_level": demand,
                    "algorithm": algorithm,
                    "trials": trials,
                    "drivers_per_trial": users,
                    "mean_total_min": f"{summary['mean_total_min']:.4f}",
                    "median_total_min": f"{summary['median_total_min']:.4f}",
                    "p95_total_min": f"{summary['p95_total_min']:.4f}",
                    "mean_wait_min": f"{summary['mean_wait_min']:.4f}",
                    "wait_over_30_min_pct": f"{summary['wait_over_30_min_pct']:.4f}",
                    "mean_cost_inr": f"{summary['mean_cost_inr']:.4f}",
                    "mean_max_station_share_pct": f"{summary['mean_max_station_share_pct']:.4f}",
                    "candidate_generation_s_shared": f"{candidate['seconds']:.6f}",
                    "candidate_generation_calls_shared": candidate["calls"],
                    "candidate_instances_shared": candidate["instances"],
                    "possible_station_evaluations_shared": candidate["possible_station_evaluations"],
                    "candidate_reduction_pct_shared": f"{candidate['reduction_pct']:.4f}",
                    "candidate_recall": "N/A: no labeled true matches",
                    "picker_calls": summary["picker_calls"],
                    "picker_time_s": f"{summary['picker_seconds']:.6f}",
                    "picker_mean_us": f"{summary['picker_mean_us']:.4f}" if summary["picker_mean_us"] is not None else "",
                    "picker_calls_per_s": f"{summary['picker_calls_per_s']:.4f}" if summary["picker_calls_per_s"] is not None else "",
                    "simulation_wall_s_shared": f"{profile['wall_seconds']:.6f}",
                    "simulation_drivers_per_s_shared": f"{profile['simulation_drivers_per_s']:.4f}",
                    "process_peak_rss_mb_cumulative": f"{profile['process_peak_rss_mb_cumulative']:.2f}",
                    "precision": "N/A: no labeled pairs",
                    "recall": "N/A: no labeled pairs",
                    "f1": "N/A: no labeled pairs",
                    "f0_5": "N/A: no labeled pairs",
                    "true_positives": "N/A",
                    "false_positives": "N/A",
                    "false_negatives": "N/A",
                    "training_time_s": "N/A: no training stage",
                    "preprocessing_time_s_shared": f"{preprocessing_seconds:.6f}",
                    "feature_extraction_time_s": "Included in picker time; not isolated",
                })


def markdown_table(headers, rows):
    output = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    output.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(output)


def fmt(value, digits=2):
    return "N/A" if value is None else f"{value:.{digits}f}"


def measured_interpretation(completed):
    statements = []
    for demand, profile in completed.items():
        summaries = profile["summaries"]
        pure = {name: value for name, value in summaries.items() if name != study.HOLDS_NAME}
        fastest = min(pure, key=lambda name: pure[name]["picker_mean_us"])
        winner = min(pure, key=lambda name: pure[name]["mean_total_min"])
        current = summaries[REFERENCE]
        held = summaries[study.HOLDS_NAME]
        wait_reduction = 100 * (current["mean_wait_min"] - held["mean_wait_min"]) / current["mean_wait_min"]
        statements.append(
            f"At {demand} demand, **{winner}** had the lowest mean simulated total time among pure rankers "
            f"({pure[winner]['mean_total_min']:.2f} min); **{fastest}** had the lowest mean picker time "
            f"({pure[fastest]['picker_mean_us']:.1f} µs/call). Reservation-aware selection reduced mean wait "
            f"from {current['mean_wait_min']:.2f} to {held['mean_wait_min']:.2f} min ({wait_reduction:.1f}%) "
            "in this simulator, but adds coordination and is not a pure ranker."
        )
    return "\n\n".join(statements)


def create_markdown(config, completed):
    rows = []
    for demand, profile in completed.items():
        for name, summary in profile["summaries"].items():
            rows.append((
                demand, name, fmt(summary["mean_total_min"]), fmt(summary["median_total_min"]),
                fmt(summary["p95_total_min"]), fmt(summary["mean_wait_min"]),
                f"{summary['wait_over_30_min_pct']:.1f}%", f"{summary['mean_cost_inr']:.0f}",
                f"{summary['mean_max_station_share_pct']:.0f}%",
            ))

    candidate_rows = []
    for demand, profile in completed.items():
        candidate = profile["candidate_generation"]
        candidate_rows.append((
            demand, candidate["calls"], candidate["instances"],
            f"{candidate['reduction_pct']:.1f}%", fmt(candidate["seconds"]),
            fmt(1000 * candidate["seconds"] / candidate["calls"] if candidate["calls"] else None),
            "N/A (no labeled pairs)",
        ))

    runtime_rows = []
    comparison_rows = []
    preprocessing_seconds = config["measurement_notes"]["preprocessing_time_s"]
    for demand, profile in completed.items():
        ref = profile["summaries"][REFERENCE]
        base = profile["summaries"][BASELINE]
        comparison = paired_difference(
            profile["summaries"]["generalized_cost (alternative)"]["per_trial_mean_total_min"],
            ref["per_trial_mean_total_min"],
        )
        relative_time_improvement = -comparison["mean"] / ref["mean_total_min"] * 100
        proposed_faster_pct = (
            (base["picker_seconds"] - ref["picker_seconds"]) / base["picker_seconds"] * 100
            if base["picker_seconds"] else None
        )
        comparison_rows.append((
            demand, "generalized_cost (alternative)", fmt(comparison["mean"]),
            f"[{fmt(comparison['low'])}, {fmt(comparison['high'])}]",
            f"{comparison['reference_faster_pct']:.1f}%" if comparison["reference_faster_pct"] is not None else "N/A",
            f"{relative_time_improvement:+.1f}%",
            f"{proposed_faster_pct:+.1f}%" if proposed_faster_pct is not None else "N/A",
            "Runtime difference is descriptive only; no repeated timing test.",
        ))
        for name, summary in profile["summaries"].items():
            runtime_rows.append((
                demand, name, fmt(preprocessing_seconds, 4), fmt(summary["picker_seconds"], 4),
                fmt(summary["picker_mean_us"], 1), fmt(summary["picker_calls_per_s"], 0),
                fmt(profile["wall_seconds"]), fmt(profile["process_peak_rss_mb_cumulative"]),
            ))

    env = config["environment"]
    station_count = config["dataset"]["station_records"]
    return f"""# Experimental Comparison of EV Charging Station Ranking Algorithms

## Abstract

This report evaluates the implemented station-selection algorithms in the EV Charge Optimizer. It does not evaluate business-entity matching: the inspected project has no S1/S2/S3 entity datasets or labeled duplicate pairs. Instead, the repository's existing paired simulation compares 10 station rankers and reservation-aware selection across three synthetic demand levels. The current weighted ranker is competitive at low demand, while generalized cost ranks better by mean realized total time at medium and high demand in this simulation. Reservation-aware selection has substantially lower simulated waits, but it is a different system mode that adds reservation coordination. All results are model-generated and should not be interpreted as field measurements.

## 1. Introduction and Objective

The objective is to compare the project's current recommendation model with implemented ranking alternatives using the same station snapshots, generated drivers, candidate filter, and simulated outcome model. Since this repository is an EV charging application, entity-match precision, recall, F1/F0.5, false positives/negatives, and blocking recall are not applicable and are not fabricated.

## 2. Existing and Proposed Systems

The application loads a validated station CSV into typed `Station` records. Connector names are normalized before compatibility filtering; unavailable stations are removed; candidates are restricted to a 10-km origin radius. Route distances/times use the study road graph or straight-line estimate, except when verified coordinates enable configured routing. Features include expected travel, wait, battery-aware charge duration, cost, availability, reliability, and rating. The current model uses weighted scoring and bounded top-k selection; it is not a learned classifier and has no training stage.

Candidate-generation algorithms are shared by the evaluated rankers: connector/status filtering plus origin-radius filtering using a precomputed route table. This experiment measures candidate counts and time for that common stage. It does not compare entity-resolution blocking methods.

The current system (Mode A) is `new_ranker (after)`. Comparators include the retained `legacy_ranker (before)`, TOPSIS, generalized cost, rated-power total-time, nearest, max availability, fastest rated charger, cheapest tariff, and deterministic random selection. `new_ranker + holds (implemented)` is reported separately because it adds stateful reservation/queue coordination rather than changing only the scoring rule.

## 3. Dataset and Experimental Configuration

The sole dataset is `{config['dataset']['name']}`: {station_count} station records and {config['dataset']['field_count']} CSV fields. It is explicitly synthetic demonstration state and uses approximate coordinates. No entity labels or train/validation/test splits exist. Phone/contact values and individual records are not reproduced in this report.

**Table 1. Dataset and experimental configuration.**

{markdown_table(['Item', 'Value'], [
    ('Station records', station_count),
    ('CSV fields', config['dataset']['field_count']),
    ('Labeled entity-match pairs', 'None; matching metrics not applicable'),
    ('Train/validation/test split', 'None; no supervised labels'),
    ('Demand scenarios', 'low, medium, high'),
    ('Trials per scenario', config['parameters']['trials']),
    ('Drivers per trial', config['parameters']['drivers_per_trial']),
    ('Random seed', config['parameters']['seed']),
    ('Machine', f"{env['cpu_model']}; {env['logical_cpu_count']} logical CPUs; {env['system_memory_mb']} MB RAM ({env['os']})"),
    ('Software', f"Python {env['python']}; FastAPI {env['fastapi']}; Pydantic {env['pydantic']}; Uvicorn {env['uvicorn']}"),
])}

## 4. Methodology

Each trial generates one station-state snapshot and a fixed set of drivers; every algorithm sees that paired input. The outcome simulator applies noisy arrival times, FIFO queues, generated background traffic, and battery-aware service durations. The ranking code does not know those random outcomes. Seeds are derived deterministically from the configured seed, demand level, and trial index. The simulation's service-time model shares the battery-aware charge estimator used by the current ranker, a known modeling asymmetry against rated-kW baselines.

Shared preprocessing time covers station loading and route-table construction. Candidate generation is timed around the actual connector/status/radius stage, excluding that route-table precomputation. Picker time is measured around each algorithm's selection call, including its in-call feature preparation; feature extraction is not separately isolated. Wall time covers the complete simulation for one demand level. Peak RSS is the process high-water mark, not an isolated per-algorithm measurement. No runtime significance test was conducted. Training time is not applicable.

## 5. Candidate Generation

**Table 2. Shared candidate-generation performance.**

{markdown_table(['Demand', 'Requests', 'Candidate instances', 'Reduction', 'Time (s)', 'Mean (ms/request)', 'Recall'], candidate_rows)}

Reduction is relative to evaluating every station for every algorithm-driver request: $1 - candidates / (requests × stations)$. Candidate recall cannot be computed without ground-truth eligible stations or labeled pairs; the radius/connector rules may intentionally exclude valid choices.

## 6. Matching Accuracy

**Table 3. Entity-matching accuracy metrics.**

{markdown_table(['Metric', 'Result', 'Reason'], [
    ('Precision, recall, F1, F0.5', 'N/A', 'No labeled entity pairs or match predictions'),
    ('TP, FP, FN', 'N/A', 'No ground-truth duplicate labels'),
    ('Blocking recall', 'N/A', 'No known true-match pairs to test against'),
])}

These are unavailable rather than zero. The project instead evaluates simulated travel, wait, and charge outcomes.

## 7. Results

**Table 4. Simulated recommendation outcome comparison.** Values are means unless labeled otherwise; total and wait are minutes, cost is INR, and station share is the maximum fraction of trial drivers assigned to one station.

{markdown_table(['Demand', 'Algorithm', 'Mean total (min)', 'Median (min)', 'P95 (min)', 'Mean wait (min)', 'Wait >30 min', 'Mean cost (INR)', 'Max station share'], rows)}

**Table 5. Runtime and resource comparison.** Preprocessing is shared startup time; feature extraction is included in picker time and not isolated. Wall time and peak RSS are shared across algorithms for each scenario and repeated for traceability.

{markdown_table(['Demand', 'Algorithm', 'Preprocess shared (s)', 'Picker total (s)', 'Mean picker (µs)', 'Calls/s', 'Scenario wall (s)', 'Peak RSS (MB)'], runtime_rows)}

No preprocessing or training time is attributed to an individual ranker: candidate inputs and feature preparation are shared. The CSV includes every algorithm/scenario outcome plus N/A values for unsupported entity-matching metrics.

**Table 6. Proposed ranker versus generalized-cost alternative.** Difference is alternative minus current mean trial total time; positive means the current ranker was faster. Relative time improvement is `(current mean - alternative mean) / current mean`; positive values favor generalized cost. The 95% interval is a normal-approximation interval over paired trial means. Picker-time percentage compares current selection time with the legacy ranker's measured selection time and is descriptive only.

{markdown_table(['Demand', 'Comparator', 'Paired difference (min)', '95% interval (min)', 'Trials current faster', 'Relative time improvement', 'Picker-time reduction vs legacy', 'Runtime inference'], comparison_rows)}

## 8. Discussion

The results are scenario-specific, not universal model rankings. Compare the mean and tail outcomes together: the system with the lowest mean may not minimize high-wait risk or cost. Reservation-aware results should not be attributed to ranking alone because reservations reduce herding by informing later simulated drivers of earlier selections. Current-versus-alternative paired intervals describe simulated outcome differences; they do not establish external validity.

{measured_interpretation(completed)}

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
"""


def create_pdf(path, config, completed):
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError as error:
        raise RuntimeError("PDF generation requires ReportLab: install with `uv pip install reportlab`.") from error

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], alignment=TA_CENTER, fontSize=19, leading=23))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=7, leading=9))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], spaceBefore=8, spaceAfter=5))
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), rightMargin=13 * mm, leftMargin=13 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = [
        Paragraph("Experimental Comparison of EV Charging Station Ranking Algorithms", styles["ReportTitle"]),
        Spacer(1, 5 * mm),
        Paragraph("Abstract", styles["Heading2"]),
        Paragraph("This report evaluates the implemented EV station rankers using the repository's paired synthetic simulation. This workspace is not a business-entity matching project and contains no labeled entity pairs; matching metrics are reported as not applicable. Simulation outcomes are assumptions-based and are not field measurements.", styles["BodyText"]),
        Paragraph("1. Existing Pipeline and Methods", styles["Section"]),
        Paragraph("Validated station CSV loading; connector/status normalization and 10-km spatial filtering; route estimates; battery-aware charge, wait, cost, availability, reliability and rating features; then weighted scoring or a rule-based ranker. No learned classifier or training stage exists. The evaluation uses the existing paired simulation with identical generated snapshots and drivers across rankers.", styles["BodyText"]),
        Paragraph("2. Dataset and Configuration", styles["Section"]),
    ]
    setup = [
        ["Dataset", config["dataset"]["name"]],
        ["Stations / fields", f"{config['dataset']['station_records']} / {config['dataset']['field_count']}"],
        ["Ground-truth pairs / data split", "None / not applicable"],
        ["Trials / drivers / seed", f"{config['parameters']['trials']} / {config['parameters']['drivers_per_trial']} / {config['parameters']['seed']}"],
        ["Hardware", f"{config['environment']['cpu_model']}; {config['environment']['logical_cpu_count']} logical CPUs; {config['environment']['system_memory_mb']} MB RAM; {config['environment']['os']}"],
        ["Python", config["environment"]["python"]],
    ]
    story.append(make_pdf_table(setup, [48 * mm, 210 * mm], styles, colors, Table, TableStyle))
    story += [Paragraph("3. Candidate Generation", styles["Section"])]
    candidate_table = [["Demand", "Requests", "Candidates", "Reduction", "Time (s)", "Recall"]]
    for demand, profile in completed.items():
        c = profile["candidate_generation"]
        candidate_table.append([demand, str(c["calls"]), str(c["instances"]), f"{c['reduction_pct']:.1f}%", f"{c['seconds']:.4f}", "N/A"])
    story.append(make_pdf_table(candidate_table, [35 * mm, 38 * mm, 40 * mm, 35 * mm, 35 * mm, 40 * mm], styles, colors, Table, TableStyle))
    story.append(Paragraph("Recall is unavailable because the data contains no labeled true matches. Reduction is measured against all station-by-request evaluations.", styles["Small"]))
    story += [Paragraph("4. Simulated Outcomes", styles["Section"])]
    story.append(Paragraph("Mean / median / P95 values are simulated total minutes. Wait is minutes, cost is INR, and concentration is the maximum share of trial drivers assigned to one station.", styles["Small"]))
    for demand, profile in completed.items():
        story.append(Paragraph(f"Demand: {demand}", styles["Heading3"]))
        table = [["Algorithm", "Mean min", "Median", "P95", "Wait min", ">30 min", "Cost INR", "Max share"]]
        for name, s in profile["summaries"].items():
            table.append([name, f"{s['mean_total_min']:.1f}", f"{s['median_total_min']:.1f}", f"{s['p95_total_min']:.1f}", f"{s['mean_wait_min']:.1f}", f"{s['wait_over_30_min_pct']:.1f}%", f"{s['mean_cost_inr']:.0f}", f"{s['mean_max_station_share_pct']:.0f}%"])
        story.append(make_pdf_table(table, [68 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm], styles, colors, Table, TableStyle))
        story.append(Paragraph("Picker/runtime resources (shared wall time and process peak RSS)", styles["Small"]))
        runtime_table = [["Algorithm", "Calls", "Picker (s)", "Mean (µs)", "Calls/s", "Wall (s)", "Peak RSS (MB)"]]
        for name, s in profile["summaries"].items():
            runtime_table.append([
                name, str(s["picker_calls"]), f"{s['picker_seconds']:.6f}",
                f"{s['picker_mean_us']:.1f}" if s["picker_mean_us"] is not None else "N/A",
                f"{s['picker_calls_per_s']:.0f}" if s["picker_calls_per_s"] is not None else "N/A",
                f"{profile['wall_seconds']:.2f}",
                f"{profile['process_peak_rss_mb_cumulative']:.1f}",
            ])
        story.append(make_pdf_table(runtime_table, [68 * mm, 28 * mm, 32 * mm, 32 * mm, 30 * mm, 30 * mm, 38 * mm], styles, colors, Table, TableStyle))
    story += [PageBreak(), Paragraph("5. Accuracy, Runtime, and Interpretation", styles["Section"])]
    story.append(make_pdf_table([
        ["Metric", "Result"],
        ["Precision / recall / F1 / F0.5", "N/A: no labeled entity pairs"],
        ["TP / FP / FN / blocking recall", "N/A: no ground truth"],
        ["Training time", "N/A: no training stage"],
        ["Runtime significance", "Not tested; picker timing is descriptive"],
        ["Memory", "Process-level peak RSS; not per algorithm"],
    ], [70 * mm, 188 * mm], styles, colors, Table, TableStyle))
    story.append(Paragraph(f"Shared preprocessing (station loading plus route-table construction) took {config['measurement_notes']['preprocessing_time_s']:.4f} seconds. Feature extraction is performed within some picker calls and is not isolated; picker timing includes that work. Wall time covers all algorithms and the complete simulation for one demand level. Because the outcome model uses the current battery-aware charging estimator and all data are synthetic, these values do not establish real-world superiority. Reservation-aware selection changes system behavior by coordinating reservations and is not a pure ranker comparison.", styles["BodyText"]))
    story += [Paragraph("Measured scenario winners", styles["Section"])]
    for statement in measured_interpretation(completed).split("\n\n"):
        story.append(Paragraph(statement.replace("**", ""), styles["BodyText"]))
    story += [Paragraph("Limitations", styles["Section"]), Paragraph("The dataset has 47 synthetic station records and approximate coordinates. There are no duplicate labels, entity splits, external traffic observations, or real charge sessions. Runtime is a single-process measurement on one machine. No statistical significance is claimed for compute timings.", styles["BodyText"])]
    doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)


def make_pdf_table(data, widths, styles, colors, Table, TableStyle):
    from reportlab.platypus import Paragraph

    wrapped = []
    for row_index, row in enumerate(data):
        wrapped.append([
            Paragraph(str(value), styles["Small"] if row_index else styles["BodyText"])
            for value in row
        ])
    table = Table(wrapped, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244b45")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9aa7a2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf3f0")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def pdf_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.35, 0.4, 0.38)
    margin = 13 * 72 / 25.4
    canvas.drawString(margin, 8 * 72 / 25.4, "EV Charge Optimizer | Synthetic simulation study")
    canvas.drawRightString(doc.pagesize[0] - margin, 8 * 72 / 25.4, f"Page {doc.page}")
    canvas.restoreState()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=300)
    parser.add_argument("--users", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fresh", action="store_true", help="Ignore any previous matching checkpoint.")
    args = parser.parse_args()
    if args.trials < 2 or args.users < 1:
        parser.error("--trials must be at least 2 and --users must be positive")

    REPORTS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    preprocessing_start = perf_counter()
    base = StationRepository().all()
    study.RouteTable(base)
    preprocessing_seconds = perf_counter() - preprocessing_start
    dataset_hash = hashlib.sha256(DATA_FILE.read_bytes()).hexdigest()
    with DATA_FILE.open(newline="", encoding="utf-8-sig") as dataset_file:
        field_count = len(next(csv.reader(dataset_file)))
    parameters = {"trials": args.trials, "drivers_per_trial": args.users, "seed": args.seed, "demand_levels": list(study.LOADS)}
    identity = {"parameters": parameters, "dataset_sha256": dataset_hash, "algorithms": list(study.ALGORITHMS) + [study.HOLDS_NAME]}
    experiment_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    config = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "parameters": parameters,
        "dataset": {
            "name": DATA_FILE.name,
            "path_relative_to_project": DATA_FILE.relative_to(ROOT).as_posix(),
            "sha256": dataset_hash,
            "station_records": len(base),
            "field_count": field_count,
            "ground_truth_entity_pairs": 0,
            "contains_synthetic_state": True,
        },
        "environment": environment_info(),
        "algorithms": identity["algorithms"],
        "measurement_notes": {
            "candidate_generation": "Timed connector/status/radius filtering; excludes route table precomputation.",
            "picker_time": "Timed selection function calls; descriptive, single-process measurement.",
            "wall_time": "Full evaluation for one demand level, shared by all algorithms.",
            "memory": "Process peak RSS high-water mark; not isolated per algorithm.",
            "preprocessing_time_s": preprocessing_seconds,
            "matching_metrics": "Not applicable: no entity labels or predicted match pairs.",
            "simulation": "Synthetic station state, origins, driver profiles, traffic, arrivals and charge outcomes.",
            "paired_interval": "Normal-approximation 95% CI over trial-level paired mean total times; not a claim about field outcomes.",
        },
        "completed_demand_levels": [],
    }
    config_path = REPORTS / "experiment_config.json"
    checkpoint_path = REPORTS / ".algorithm_comparison_checkpoint.json"
    csv_path = REPORTS / "algorithm_comparison_results.csv"
    completed = {} if args.fresh else load_checkpoint(checkpoint_path, experiment_id)
    for demand in study.LOADS:
        if demand in completed:
            print(f"Resuming: {demand} demand results already available")
            continue
        print(f"Running {args.trials} trials at {demand} demand...")
        try:
            completed[demand] = time_profiled_run(args.trials, args.users, args.seed, demand)
            checkpoint_write(checkpoint_path, experiment_id, completed)
            write_csv(csv_path, experiment_id, completed, args.trials, args.users, preprocessing_seconds)
            config["completed_demand_levels"] = list(completed)
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            print(f"Completed {demand}: {completed[demand]['wall_seconds']:.2f}s")
        except Exception:
            logging.exception("Experiment failed at demand level %s", demand)
            config["status"] = "incomplete"
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            raise

    write_csv(csv_path, experiment_id, completed, args.trials, args.users, preprocessing_seconds)
    report_path = REPORTS / "algorithm_comparison_report.md"
    report_path.write_text(create_markdown(config, completed), encoding="utf-8")
    create_pdf(REPORTS / "algorithm_comparison_report.pdf", config, completed)
    config["status"] = "complete"
    config["completed_demand_levels"] = list(completed)
    config["outputs"] = [
        "algorithm_comparison_report.md", "algorithm_comparison_report.pdf",
        "algorithm_comparison_results.csv", "experiment_config.json",
        "reproduce_experiments.md",
    ]
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    reproduce = """# Reproducing the Algorithm Comparison

Run commands from the `backend/` directory.

## Requirements

Use the project's Python 3.11 virtual environment and install its pinned dependencies. PDF generation additionally uses ReportLab:

```bash
source .venv311/bin/activate
uv pip install -r requirements.txt
uv pip install reportlab
```

## Run

```bash
python -m eval.generate_research_report --trials 300 --users 12 --seed 7
```

The generator runs the existing paired simulation for low, medium, and high demand. It records the data SHA-256, seed, parameters, machine/software information, candidate-generation timing, picker timing, scenario wall time, and process peak RSS. Completed demand levels are checkpointed under `reports/`; rerunning the same command resumes compatible completed levels. Use `--fresh` to ignore a previous checkpoint. Optional parameters are `--trials`, `--users`, and `--seed`.

## Interpretation

The dataset is synthetic station data, not business entities. No entity matching labels exist, so precision, recall, F1/F0.5, TP/FP/FN, and candidate recall are unavailable. Scenario trip outcomes are simulated; runtime figures are local measurements on the recorded machine. Runtime timing is descriptive, and no compute-time significance test is performed. Do not compare these simulated travel/charge minutes to field observations.
"""
    (REPORTS / "reproduce_experiments.md").write_text(reproduce, encoding="utf-8")
    print(f"Reports written to {REPORTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())