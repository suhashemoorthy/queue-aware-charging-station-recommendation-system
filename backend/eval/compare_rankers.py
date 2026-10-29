"""Compare recommendation algorithms when several drivers choose at the same time.

Run from the backend folder:   python -m eval.compare_rankers --trials 150

How it works (all of it is a SIMULATION built on stated assumptions, not real-world data):
  1. Each trial draws one snapshot of the station state (ports, queue, wait) at a given
     demand level, and N drivers with different batteries, start charge and origins.
  2. Every algorithm sees the SAME snapshot and the same drivers (paired design) and
     picks a station for each driver, exactly like the app does: independent picks, no
     reservation, so drivers can herd onto the same station.
  3. The outcome is then played out: drivers arrive after a noisy travel time, queue
     FIFO at the chosen station together with the cars already waiting and some
     background traffic, and charge for a noisy time. Realised total time = travel +
     wait + charge. Cost = billed energy x tariff.

Caveat: the true charge time uses the same battery-aware model as the new ranker, so
the "rated kW" baselines are penalised by that modelling assumption. Waits, traffic and
arrivals are random and none of the algorithms knows them in advance.
"""

import argparse
import heapq
import logging
import math
import random
import statistics
from pathlib import Path

logging.disable(logging.CRITICAL)

from app.algorithms import (  # noqa: E402
    apply_road_network_distance,
    filter_by_connector,
    haversine_distance,
)
from app.charging_model import estimate_charge  # noqa: E402
from app.recommender import rank_candidates  # noqa: E402
from app.reservations import ReservationError, ReservationManager, adjust_for_reservations  # noqa: E402
from app.repository import StationRepository  # noqa: E402
from app.legacy_ranker import rank_candidates as legacy_rank_candidates  # noqa: E402
from app.strategies import generalized_cost_pick, topsis_pick  # noqa: E402

ORIGINS = {
    "RS_PURAM": (11.0055, 76.9537),
    "GANDHIPURAM": (11.0168, 76.9558),
    "PEELAMEDU": (11.0301, 77.0007),
    "AVINASHI_ROAD": (11.0183, 77.0067),
    "PSG_TECH": (11.0242, 76.9344),
}
BATTERIES_KWH = [3.7, 12, 24, 40, 60]
RADIUS_KM = 10.0
LOADS = {"low": 0.30, "medium": 0.55, "high": 0.80}  # average share of ports busy
TRAFFIC_SIGMA = 0.25      # log-normal noise on travel time
BG_HORIZON_MIN = 180      # background (non-app) arrivals are generated for this long
BG_FACTOR = 0.15          # background arrival intensity relative to station capacity


# ----------------------------------------------------------------------------- helpers
def session_mean_min(station) -> float:
    """Typical length of one session at this station (same rule as the demo data)."""
    return min(max(15 / (station.charging_speed_kw * 0.92) * 60, 20), 90)


def make_snapshot(rng, base, load):
    """New station state at the given demand level, obeying the physical rules."""
    snapshot = []
    for station in base:
        s = station.model_copy(deep=True)
        s.dynamic_data_source = "synthetic_demo_state"
        if s.status != "operational":
            s.available_ports, s.occupied_ports, s.queue_length, s.estimated_wait_min = 0, 0, 0, 0.0
            s.out_of_service_ports = s.total_ports
        else:
            s.out_of_service_ports = 0
            utilisation = min(max(load + rng.uniform(-0.2, 0.2), 0.05), 0.97)
            busy = sum(rng.random() < utilisation for _ in range(s.total_ports))
            s.occupied_ports, s.available_ports = busy, s.total_ports - busy
            s.queue_length = (
                min(2 * s.total_ports, int(rng.expovariate(1 / (0.4 + 2.4 * load))))
                if s.available_ports == 0 else 0
            )
            s.estimated_wait_min = (
                round((s.queue_length + 0.5) * session_mean_min(s) / s.total_ports, 1)
                if s.available_ports == 0 else 0.0
            )
        snapshot.append(s)
    return snapshot


def make_user(rng):
    battery = rng.choice(BATTERIES_KWH)
    return {
        "origin": rng.choice(list(ORIGINS)),
        "battery_kwh": battery,
        "start_soc": rng.uniform(0.10, 0.40),
        "end_soc": 0.80,
        "connector": "CCS2" if rng.random() < 0.8 else "Type2",
        "travel_noise": math.exp(rng.gauss(0, TRAFFIC_SIGMA)),
        "charge_noise": rng.uniform(0.90, 1.15),
    }


def urgency(user) -> str:
    """Same thresholds as the API."""
    range_km = user["battery_kwh"] * user["start_soc"] / 0.18
    if range_km < RADIUS_KM:
        return "CRITICAL"
    if range_km < RADIUS_KM * 2:
        return "HIGH"
    if range_km < RADIUS_KM * 4:
        return "MEDIUM"
    return "LOW"


class RouteTable:
    """Route estimates per origin, computed once with the app's own fallback routing."""

    def __init__(self, base):
        self.table = {}
        for key, (lat, lon) in ORIGINS.items():
            copies = [s.model_copy(deep=True) for s in base]
            apply_road_network_distance(copies, lat, lon)
            self.table[key] = {
                s.station_id: (
                    s.road_distance_km,
                    s.travel_time_min,
                    haversine_distance(lat, lon, s.latitude, s.longitude) <= RADIUS_KM,
                )
                for s in copies
            }

    def candidates(self, user, snapshot):
        kept, _ = filter_by_connector(snapshot, user["connector"], include_unverified=True)
        out = []
        for s in kept:
            km, minutes, in_radius = self.table[user["origin"]][s.station_id]
            if in_radius and s.charging_speed_kw > 0:
                s.road_distance_km, s.travel_time_min, s.route_source = km, minutes, "haversine_estimate"
                out.append(s)
        return out


def charge_of(station, user):
    return estimate_charge(
        station.charging_speed_kw, station.connector_class, station.cost_per_kwh,
        user["battery_kwh"], user["start_soc"], user["end_soc"],
    )


# ------------------------------------------------------------------------- algorithms
def pick_nearest(c, u, rng):
    return min(c, key=lambda s: (s.travel_time_min, s.station_id)).station_id


def pick_max_availability(c, u, rng):
    return max(c, key=lambda s: (s.available_ports / max(s.total_ports, 1), -s.queue_length, -s.travel_time_min)).station_id


def pick_fastest_rated(c, u, rng):
    return max(c, key=lambda s: (s.charging_speed_kw, -s.travel_time_min)).station_id


def pick_cheapest(c, u, rng):
    return min(c, key=lambda s: (s.cost_per_kwh, s.travel_time_min)).station_id


def pick_random(c, u, rng):
    return rng.choice(sorted(c, key=lambda s: s.station_id)).station_id


def pick_naive_total_time(c, u, rng):
    """Minimise travel + wait + charge time, but with the charger's RATED kW (no battery model)."""
    energy = u["battery_kwh"] * (u["end_soc"] - u["start_soc"])
    return min(
        c, key=lambda s: s.travel_time_min + s.estimated_wait_min + energy / (s.charging_speed_kw * 0.92) * 60
    ).station_id


def pick_legacy(c, u, rng):
    result = legacy_rank_candidates(
        c, 0, 0, top_k=1, battery_urgency=urgency(u), queue_model="occupancy_estimate"
    )
    return result[0].station_id if result else None


def pick_new(c, u, rng):
    result = rank_candidates(
        c, 0, 0, top_k=1, battery_urgency=urgency(u), queue_model="occupancy_estimate",
        battery_capacity_kwh=u["battery_kwh"], start_soc=u["start_soc"], end_soc=u["end_soc"],
    )
    return result[0].station_id if result else None


def pick_topsis(c, u, rng):
    return topsis_pick(c, u["battery_kwh"], u["start_soc"], u["end_soc"], urgency(u))


def pick_generalized_cost(c, u, rng):
    return generalized_cost_pick(c, u["battery_kwh"], u["start_soc"], u["end_soc"], urgency(u))


ALGORITHMS = {
    "random": pick_random,
    "nearest": pick_nearest,
    "max_availability": pick_max_availability,
    "fastest_rated_kw": pick_fastest_rated,
    "cheapest": pick_cheapest,
    "naive_total_time": pick_naive_total_time,
    "legacy_ranker (before)": pick_legacy,
    "TOPSIS (alternative)": pick_topsis,
    "generalized_cost (alternative)": pick_generalized_cost,
    "new_ranker (after)": pick_new,
}
HOLDS_NAME = "new_ranker + holds (implemented)"


# --------------------------------------------------------------------------- outcome
def realise(snapshot, choices, users, rng, load, travel_for):
    """Play out the FIFO queues. choices: {user_index: station_id}."""
    by_station = {}
    for index, station_id in choices.items():
        by_station.setdefault(station_id, []).append(index)
    stations = {s.station_id: s for s in snapshot}
    outcomes = {}
    for station_id, indexes in by_station.items():
        s = stations[station_id]
        ports = max(s.total_ports - s.out_of_service_ports, 1)
        sess = session_mean_min(s)
        free_at = [rng.uniform(0, sess) if i < s.occupied_ports else 0.0 for i in range(ports)]
        heapq.heapify(free_at)
        events = [(0.0, 0, sess * rng.uniform(0.5, 1.5), None) for _ in range(s.queue_length)]
        clock, rate = 0.0, BG_FACTOR * load * ports / sess
        while rate > 0:
            clock += rng.expovariate(rate)
            if clock > BG_HORIZON_MIN:
                break
            events.append((clock, 1, sess * rng.uniform(0.5, 1.5), None))
        for index in indexes:
            u = users[index]
            charge = charge_of(s, u)
            travel = travel_for[(station_id, index)] * u["travel_noise"]
            events.append((travel, 1, charge.minutes * u["charge_noise"], index))
        events.sort(key=lambda e: (e[0], e[1]))
        for arrival, _, service, index in events:
            free = heapq.heappop(free_at)
            start = max(arrival, free)
            heapq.heappush(free_at, start + service)
            if index is not None:
                u = users[index]
                charge = charge_of(s, u)
                outcomes[index] = {
                    "total": arrival + (start - arrival) + service,
                    "wait": start - arrival,
                    "cost": charge.cost_inr,
                    "station": station_id,
                }
    return outcomes


# ------------------------------------------------------------------------------ main
def run(trials, users_per_trial, seed, load_name):
    load = LOADS[load_name]
    base = StationRepository().all()
    routes = RouteTable(base)
    names = list(ALGORITHMS) + [HOLDS_NAME]
    per_trial = {n: [] for n in names}     # mean total per trial (for paired stats)
    all_totals = {n: [] for n in names}
    all_waits = {n: [] for n in names}
    all_costs = {n: [] for n in names}
    load_share = {n: [] for n in names}    # max share of drivers sent to one station

    for t in range(trials):
        rng = random.Random(f"{seed}-{load_name}-{t}")
        snapshot = make_snapshot(rng, base, load)
        users = [make_user(rng) for _ in range(users_per_trial)]
        for name in names:
            holds = name == HOLDS_NAME
            view = [s.model_copy(deep=True) for s in snapshot] if holds else snapshot
            by_id = {s.station_id: s for s in view}
            # With holds the drivers go through the app's real ReservationManager: each
            # one sees the ports and queue slots already taken by the drivers before them.
            manager = ReservationManager(by_id.get, hold_seconds=1e9, queue_ttl_seconds=1e9,
                                         max_queue_per_station=10_000, clock=lambda: 0.0) if holds else None
            pick = pick_new if holds else ALGORITHMS[name]
            choices, travel_for = {}, {}
            for i, user in enumerate(users):
                seen = adjust_for_reservations(view, manager.counts_for_ranking()) if holds else view
                cand = routes.candidates(user, seen)
                if not cand:
                    continue
                chosen = pick(cand, user, random.Random(f"{seed}-{t}-{i}-{name}"))
                if chosen is None:
                    continue
                choices[i] = chosen
                travel_for[(chosen, i)] = next(s for s in cand if s.station_id == chosen).travel_time_min
                if holds:
                    try:
                        manager.reserve(chosen, f"driver-{i:05d}")
                    except ReservationError:
                        try:
                            manager.join_queue(chosen, f"driver-{i:05d}")
                        except ReservationError:
                            pass
            outcome = realise(snapshot, choices, users, random.Random(f"{seed}-{t}-real"), load, travel_for)
            totals = [o["total"] for o in outcome.values()]
            if not totals:
                continue
            per_trial[name].append(statistics.fmean(totals))
            all_totals[name] += totals
            all_waits[name] += [o["wait"] for o in outcome.values()]
            all_costs[name] += [o["cost"] for o in outcome.values()]
            counts = {}
            for o in outcome.values():
                counts[o["station"]] = counts.get(o["station"], 0) + 1
            load_share[name].append(max(counts.values()) / len(outcome))
    return names, per_trial, all_totals, all_waits, all_costs, load_share


def pct(values, q):
    values = sorted(values)
    return values[min(int(q * len(values)), len(values) - 1)]


def report(load_name, results, reference="new_ranker (after)"):
    names, per_trial, totals, waits, costs, share = results
    lines = [f"### Demand level: {load_name}", "",
             "| algorithm | mean total (min) | median | p95 | mean wait | wait > 30 min | mean cost (INR) | max drivers on one station |",
             "|---|---|---|---|---|---|---|---|"]
    for n in names:
        t, w = totals[n], waits[n]
        lines.append(
            f"| {n} | {statistics.fmean(t):.1f} | {statistics.median(t):.1f} | {pct(t, .95):.1f} | "
            f"{statistics.fmean(w):.1f} | {100 * sum(x > 30 for x in w) / len(w):.1f}% | "
            f"{statistics.fmean(costs[n]):.0f} | {100 * statistics.fmean(share[n]):.0f}% |"
        )
    lines += ["", f"Paired difference in mean total time versus `{reference}` "
              "(positive = that algorithm is slower), 95% CI over trials:", "",
              "| algorithm | mean diff (min) | 95% CI | trials where reference was faster |", "|---|---|---|---|"]
    ref = per_trial[reference]
    for n in names:
        if n == reference:
            continue
        d = [a - b for a, b in zip(per_trial[n], ref)]
        mean = statistics.fmean(d)
        half = 1.96 * statistics.stdev(d) / math.sqrt(len(d))
        wins = 100 * sum(x > 0 for x in d) / len(d)
        lines.append(f"| {n} | {mean:+.1f} | [{mean - half:+.1f}, {mean + half:+.1f}] | {wins:.0f}% |")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=150)
    parser.add_argument("--users", type=int, default=12, help="drivers choosing at the same time")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="eval/results.md")
    args = parser.parse_args()
    sections = [
        f"# Ranker comparison (simulation)\n\n{args.trials} trials per demand level, "
        f"{args.users} drivers choosing at once, seed {args.seed}. See the docstring in "
        "`eval/compare_rankers.py` for the assumptions.\n"
    ]
    for level in LOADS:
        sections.append(report(level, run(args.trials, args.users, args.seed, level)))
        print(sections[-1], "\n")
    Path(args.out).write_text("\n\n".join(sections), encoding="utf-8")
    print("written", args.out)
