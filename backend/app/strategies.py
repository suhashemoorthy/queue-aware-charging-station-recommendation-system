"""Every ranking algorithm the app can use, selectable by name.

The app's own ranker is "new_ranker". The others are the alternatives and baselines from
the comparison study. All of them rank the SAME rows (travel + wait + charge time and
cost for the driver's own battery), so they differ only in how they choose. Rule-based
algorithms have no score; they show their rule instead.
"""

import math
import random
from statistics import median
from types import SimpleNamespace

from .config import get_settings
from .legacy_ranker import rank_candidates as legacy_rank_candidates
from .models import Recommendation
from .recommender import (
    BENEFIT_CRITERIA,
    build_recommendation,
    clamp,
    normalize_weights,
    prepare_rows,
    rank_candidates,
)

VALUE_OF_TIME_INR_PER_MIN = 5.0  # INR 300 per hour: an assumption, not a measurement

# id -> (label, group, description)
ALGORITHMS = {
    "new_ranker": (
        "New ranker (current)", "Your approach",
        "Weighted score over expected total time (travel + wait + charge for your battery), "
        "cost, availability, reliability and rating.",
    ),
    "legacy_ranker": (
        "Legacy ranker (before)", "Previous version",
        "The original weighted sum of 8 criteria, using the charger's rated kW and min-max scaling.",
    ),
    "topsis": (
        "TOPSIS", "Alternative algorithm",
        "Multi-criteria method: closest to the ideal option and furthest from the worst, "
        "using the same criteria and weights as the new ranker.",
    ),
    "generalized_cost": (
        "Generalized cost", "Alternative algorithm",
        "Lowest total time + cost / value of time (INR 300 per hour assumed). No weights.",
    ),
    "min_total_time": (
        "Min total time (rated kW)", "Baseline",
        "Lowest travel + wait + charge time, with charge time taken from the charger's rated kW "
        "(no battery model).",
    ),
    "nearest": ("Nearest station", "Baseline", "Shortest travel time."),
    "max_availability": (
        "Max availability", "Baseline", "Highest share of free ports, then shortest queue.",
    ),
    "fastest_rated_kw": ("Fastest rated charger", "Baseline", "Highest rated charger power."),
    "cheapest": ("Cheapest tariff", "Baseline", "Lowest price per kWh."),
    "random": (
        "Random", "Baseline",
        "Any compatible station (the same request always gives the same order).",
    ),
}


# ------------------------------------------------------------- scoring algorithms
def _fill(values):
    known = [v for v in values if v is not None]
    return None if not known else [median(known) if v is None else v for v in values]


def topsis_scores(rows, battery_urgency="LOW") -> list[float]:
    """Closeness to the ideal solution, 0..1 (higher is better)."""
    columns = {
        "total_time": [r.total_time for r in rows],
        "availability": [clamp(r.station.available_ports / max(r.station.total_ports, 1), 0, 1) for r in rows],
    }
    for name, values in (
        ("cost", [r.session_cost for r in rows]),
        ("reliability", [r.station.reliability_score for r in rows]),
        ("rating", [r.station.rating / 5 if r.station.rating > 0 else None for r in rows]),
    ):
        filled = _fill(values)
        if filled is not None:
            columns[name] = filled
    weights = normalize_weights(get_settings().recommendation_weights, set(columns), battery_urgency)

    weighted = {}
    for name, values in columns.items():
        norm = math.sqrt(sum(v * v for v in values)) or 1.0  # vector normalisation
        weighted[name] = [weights[name] * v / norm for v in values]
    best = {n: (max if n in BENEFIT_CRITERIA else min)(v) for n, v in weighted.items()}
    worst = {n: (min if n in BENEFIT_CRITERIA else max)(v) for n, v in weighted.items()}

    scores = []
    for i, row in enumerate(rows):
        d_best = math.sqrt(sum((weighted[n][i] - best[n]) ** 2 for n in weighted))
        d_worst = math.sqrt(sum((weighted[n][i] - worst[n]) ** 2 for n in weighted))
        closeness = d_worst / (d_best + d_worst) if d_best + d_worst > 0 else 1.0
        if row.unverified:
            closeness *= get_settings().unverified_connector_penalty
        scores.append(closeness)
    return scores


def generalized_cost_values(rows) -> list[float]:
    """Total time + cost / value of time, in minutes (lower is better)."""
    costs = _fill([r.session_cost for r in rows]) or [0.0] * len(rows)
    values = []
    for row, cost in zip(rows, costs):
        value = row.total_time + cost / VALUE_OF_TIME_INR_PER_MIN
        if row.unverified:
            value /= get_settings().unverified_connector_penalty
        values.append(value)
    return values


# Used by the comparison study (eval/compare_rankers.py): pick the single best station.
def topsis_pick(stations, battery_kwh, start_soc, end_soc, battery_urgency="LOW"):
    rows = prepare_rows(stations, 0, 0, battery_kwh, start_soc, end_soc, "occupancy_estimate")
    if not rows:
        return None
    scores = topsis_scores(rows, battery_urgency)
    return rows[max(range(len(rows)), key=lambda i: (scores[i], -rows[i].total_time))].station.station_id


def generalized_cost_pick(stations, battery_kwh, start_soc, end_soc, battery_urgency="LOW"):
    rows = prepare_rows(stations, 0, 0, battery_kwh, start_soc, end_soc, "occupancy_estimate")
    if not rows:
        return None
    values = generalized_cost_values(rows)
    return rows[min(range(len(rows)), key=lambda i: values[i])].station.station_id


# ---------------------------------------------------------------- the entry point
def run_algorithm(
    algorithm: str,
    stations,
    latitude: float,
    longitude: float,
    *,
    top_k: int = 3,
    battery_urgency: str = "LOW",
    weights: dict[str, float] | None = None,
    queue_model: str | None = None,
    battery_capacity_kwh: float | None = None,
    start_soc: float = 0.1,
    end_soc: float = 0.8,
) -> list[Recommendation]:
    """Top-k recommendations from the chosen algorithm. Raises KeyError for an unknown id."""
    if algorithm not in ALGORITHMS:
        raise KeyError(algorithm)
    if not stations:
        return []
    settings = get_settings()
    battery_kwh = battery_capacity_kwh or settings.default_battery_capacity_kwh

    if algorithm == "new_ranker":
        return rank_candidates(
            stations, latitude, longitude, top_k=top_k, battery_urgency=battery_urgency,
            weights=weights, queue_model=queue_model, battery_capacity_kwh=battery_kwh,
            start_soc=start_soc, end_soc=end_soc,
        )

    rows = prepare_rows(stations, latitude, longitude, battery_kwh, start_soc, end_soc, queue_model)
    if not rows:
        return []
    by_id = {row.station.station_id: row for row in rows}

    if algorithm == "legacy_ranker":
        legacy = legacy_rank_candidates(
            [row.station for row in rows], latitude, longitude, top_k=top_k,
            battery_urgency=battery_urgency, queue_model=queue_model or settings.queue_model,
        )
        results = []
        for rec in legacy:
            row = by_id[rec.station_id]
            # The legacy ranker has no battery model: show the same charge estimate as the
            # others so the cards are comparable, but keep its own score and wait.
            total = rec.travel_time_min + rec.estimated_wait_min + row.charge.minutes
            results.append(rec.model_copy(update={
                "algorithm": algorithm,
                "score_note": None,
                "charge_time_min": row.charge.minutes,
                "total_time_min": round(total, 1),
                "session_cost_inr": row.session_cost,
                "delivered_kw": row.charge.delivered_kw,
                "vehicle_limit_kw": row.charge.vehicle_limit_kw,
                "limited_by": row.charge.limited_by,
            }))
        return results

    # Everything else: an ordering of the rows, best first, with an optional score.
    scores: list[float | None] = [None] * len(rows)
    notes: list[str | None] = [None] * len(rows)
    energy_kwh = battery_kwh * (end_soc - start_soc)

    if algorithm == "topsis":
        scores = topsis_scores(rows, battery_urgency)
        keys = [(-s, r.total_time) for s, r in zip(scores, rows)]
    elif algorithm == "generalized_cost":
        values = generalized_cost_values(rows)
        keys = [(v, r.total_time) for v, r in zip(values, rows)]
        notes = [f"time + cost/value-of-time = {v:.1f} min-equivalent" for v in values]
    elif algorithm == "min_total_time":
        values = [
            r.station.travel_time_min + r.wait_minutes
            + energy_kwh / (r.station.charging_speed_kw * 0.92) * 60
            for r in rows
        ]
        keys = [(v, r.total_time) for v, r in zip(values, rows)]
        notes = [f"rated-kW estimate: {v:.1f} min" for v in values]
    elif algorithm == "nearest":
        keys = [(r.station.travel_time_min, r.station.station_id) for r in rows]
        notes = [f"travel {r.station.travel_time_min:.1f} min" for r in rows]
    elif algorithm == "max_availability":
        keys = [
            (-(r.station.available_ports / max(r.station.total_ports, 1)),
             r.station.queue_length, r.station.travel_time_min)
            for r in rows
        ]
        notes = [f"{r.station.available_ports}/{r.station.total_ports} ports free" for r in rows]
    elif algorithm == "fastest_rated_kw":
        keys = [(-r.station.charging_speed_kw, r.station.travel_time_min) for r in rows]
        notes = [f"rated {r.station.charging_speed_kw:g} kW" for r in rows]
    elif algorithm == "cheapest":
        keys = [
            (r.station.cost_per_kwh if r.station.cost_per_kwh > 0 else math.inf, r.station.travel_time_min)
            for r in rows
        ]
        notes = [f"INR {r.station.cost_per_kwh:g} per kWh" for r in rows]
    else:  # random
        rng = random.Random(f"{latitude:.4f},{longitude:.4f},{battery_kwh:g},{start_soc:.2f},{end_soc:.2f}")
        draws = [rng.random() for _ in rows]
        keys = [(d, r.station.station_id) for d, r in zip(draws, rows)]
        notes = ["random pick"] * len(rows)

    if algorithm == "topsis":
        notes = [f"closeness to the ideal option: {s:.2f}" for s in scores]
    order = sorted(range(len(rows)), key=lambda i: keys[i])[:top_k]
    return [
        build_recommendation(
            rows[i], rank, battery_urgency, score=scores[i], score_note=notes[i], algorithm=algorithm
        )
        for rank, i in enumerate(order, start=1)
    ]
