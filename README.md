# Queue-aware charging station recommendation system

An EV charging station recommendation app with queue-aware ranking, route and charging-time estimates, live-data integrations, and reservation/queue handling.

## Why this approach

Choosing the nearest, cheapest, or highest-power station in isolation can make a trip worse: drivers may converge on one busy station, and rated charger power alone does not capture how long a particular battery needs to charge. This system ranks stations by the driver's estimated total stop time (travel + queue wait + battery-specific charging time), while also considering cost and, when available, station availability, reliability, and rating. Criteria with missing data are omitted and the remaining weights are normalized.

Recommendations are paired with atomic reservations and a FIFO queue. That means simultaneous drivers cannot all claim the same last port, and a released or expired hold can be offered to the next queued driver. Routing and live availability are integrated when configured; estimates and data sources remain identifiable when providers are unavailable. The implementation also uses a bounded top-k selection rather than sorting every candidate.

### Simulation results

In the included simulation (300 trials per demand level, 12 simultaneous drivers, seed 7), adding reservation holds to the new ranker reduced mean total trip time compared with the same ranker making independent picks:

| Demand | New ranker alone | New ranker + holds | Difference |
|---|---:|---:|---:|
| Low | 68.4 min | 44.2 min | -24.2 min |
| Medium | 74.8 min | 46.5 min | -28.3 min |
| High | 86.3 min | 50.6 min | -35.7 min |

These are simulation results using synthetic station conditions and stated assumptions, not a guarantee of real-world performance. See [the full evaluation](backend/eval/results.md) and [algorithm notes](docs/ALGORITHMS.md) for details.

## Requirements

- Python 3.11
- Node.js and npm

## Run

From the project root, prepare the backend environment once:

```bash
cd backend
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install -r requirements.txt
cd ..
```

Then start both services:

```bash
python3 executeev.py
```

The frontend is served at `http://localhost:5173`; the API documentation is at `http://localhost:8000/docs`. Press Ctrl+C to stop both services. The launcher installs frontend npm packages on its first run.

To configure optional live-data providers, copy `backend/.env.example` to `backend/.env` and fill in the values you have. Do not commit `backend/.env`.

## Tests

```bash
cd backend
.venv311/bin/python -m pytest -q
```

## Project documentation

- [Algorithm notes](docs/ALGORITHMS.md)
- [Technical description](docs/TECHNICAL_DESCRIPTION.md)