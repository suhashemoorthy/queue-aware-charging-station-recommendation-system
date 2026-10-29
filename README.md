# Queue-aware charging station recommendation system

An EV charging station recommendation app with queue-aware ranking, route and charging-time estimates, live-data integrations, and reservation/queue handling.

## Why this approach

Choosing the nearest, cheapest, or highest-power station in isolation can make a trip worse: drivers may converge on one busy station, and rated charger power alone does not capture how long a particular battery needs to charge. This system ranks stations by the driver's estimated total stop time (travel + queue wait + battery-specific charging time), while also considering cost and, when available, station availability, reliability, and rating. Criteria with missing data are omitted and the remaining weights are normalized.

## Project scope and data

The system targets station selection for a driver journey: it filters candidates by connector compatibility, operating status, and maximum distance from the origin, then ranks them using the driver's battery and target charge. The app exposes 10 selectable strategies, including the current weighted ranker, TOPSIS, generalized cost, and simple nearest, cheapest, availability, power, and random baselines.

The default dataset contains 47 Coimbatore station records. Their demonstration availability, queues, waits, tariffs, and coordinates are synthetic or approximate; they are not live measurements. Charging energy, duration, and cost are calculated from request and station inputs. OCPI, TomTom, OpenStreetMap refresh, and OSRM routing are optional integrations, not a guarantee that every displayed station has live data or verified routing.

Recommendations are paired with atomic reservations and a FIFO queue. That means simultaneous drivers cannot all claim the same last port, and a released or expired hold can be offered to the next queued driver. Routing and live availability are integrated when configured; estimates and data sources remain identifiable when providers are unavailable. The implementation also uses a bounded top-k selection rather than sorting every candidate.

### Simulation results

The comparison uses paired simulations: every strategy receives the same station snapshot and 12 driver inputs per trial. With 300 trials per demand level and seed 7, adding reservation holds to the new ranker reduced mean simulated total time compared with the same ranker making independent picks:

| Demand | New ranker alone | New ranker + holds | Difference |
|---|---:|---:|---:|
| Low | 68.4 min | 44.2 min | -24.2 min |
| Medium | 74.8 min | 46.5 min | -28.3 min |
| High | 86.3 min | 50.6 min | -35.7 min |

These are simulation results using synthetic station conditions and stated assumptions, not a guarantee of real-world performance. See [the full evaluation](backend/eval/results.md) and [algorithm notes](docs/ALGORITHMS.md) for details.

## Limitations and next steps

The current evaluation does not validate real arrival patterns, occupancy, or end-to-end route accuracy. The supplied station state is synthetic, and the simulator's service-time model shares the current ranker's charging estimator. The next validation steps are to use real availability and arrival data, verify road routes and station coordinates, and repeat runtime and memory measurements across runs. See [the technical description](docs/TECHNICAL_DESCRIPTION.md) for implementation details and assumptions.

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