# Changes in this version

## Version 3: choose the ranking algorithm

A dropdown on the form selects which algorithm from the comparison study ranks the stations; the cards update straight away. A checkbox also shows every algorithm's top 3 for the same request in one table.

| id | Algorithm | Group |
|---|---|---|
| `new_ranker` | New ranker (current), the default | Your approach |
| `legacy_ranker` | Original ranker | Previous version |
| `topsis` | TOPSIS | Alternative algorithm |
| `generalized_cost` | Time + cost / value of time (INR 300/h assumed) | Alternative algorithm |
| `min_total_time` | Lowest travel + wait + charge using rated kW | Baseline |
| `nearest`, `max_availability`, `fastest_rated_kw`, `cheapest`, `random` | Simple rules | Baseline |

- `GET /api/algorithms` lists them; `POST /api/recommend` takes `"algorithm"` (default `new_ranker`, unknown id -> 422); `POST /api/compare` runs all of them on one request.
- All algorithms rank the same rows (travel + wait + charge and cost for the driver's own battery, after other drivers' reservations), so the cards are comparable. Scoring algorithms show a score; rule-based ones show their rule (for example "travel 5.9 min") because they have no score. The legacy ranker keeps its own score and wait but shows the same charge estimate.
- Code: `backend/app/strategies.py` (one implementation, also used by `eval/compare_rankers.py`; the comparison numbers are unchanged), `backend/app/legacy_ranker.py` (moved from `eval/`).
- Tests: `backend/tests/test_algorithm_selection.py` (36 tests: each rule, the API for every algorithm, compare, unknown id). 105 backend tests in total.

---

## Version 2: reservations (concurrent drivers)

Recommendations used to change nothing, so drivers who saw the same result all went to the
same station. The backend now has reservation holds and a first-come queue.

| Endpoint | What it does |
|---|---|
| `POST /api/reservations` | Take a port atomically. `201` held, `409 station_full` (response says whether you can queue and the expected wait), `409 user_has_active_reservation`, `404`, `422` |
| `POST /api/queue` | Join the FIFO queue of a full station (`409 port_available` if a port is free) |
| `GET /api/reservations/{id}` | Status, seconds left on the hold, queue position, expected wait |
| `POST /api/reservations/{id}/arrive` | Hold becomes an active charging session |
| `DELETE /api/reservations/{id}` | Release a hold, leave the queue or finish a session; frees the port and promotes the head of the queue. Safe to repeat |
| `GET /api/stations/{id}/availability` | Base ports, held, charging, queue, effective free |

How it behaves
- One lock guards all reservation state, so "is a port free?" and "take it" cannot interleave. Exactly one of N simultaneous requests wins a single free port.
- A hold lasts `RESERVATION_HOLD_MINUTES` (10). Expiry is checked on every call, then the next person in the queue is promoted. Queue slots expire after `RESERVATION_QUEUE_TTL_MINUTES` (60). Queue length per station is capped (`RESERVATION_MAX_QUEUE_PER_STATION`, 10).
- Queue order is a server sequence number. One active reservation per user. `Idempotency-Key` header makes retries safe.
- Holds do not edit the station cache: effective free = station ports - held. `/api/recommend` ranks on that, so later drivers see held ports as taken and queue slots as longer waits (`holds_applied`, `app_queue_length` on each recommendation).
- Frontend: Reserve / Join queue / I have arrived / Release on each card, with a countdown.

Tests (`backend/tests/test_reservations.py`, 30 tests): logic with a fake clock, 100 threads at one free port (exactly 1 succeeds; 3 ports -> exactly 3), parallel queue joins get unique positions 1..N, parallel reserve/release never oversells, and 40 simultaneous HTTP requests to a real uvicorn server (exactly one `201`, 39 `409`). Removing the lock makes all 50 requests succeed, so the tests do detect the race.

Limits: in memory and single process (use Redis or a database for several workers); no authentication (`user_id` is an id the browser makes up); cars queued by outside drivers only appear through the station's own queue length. Try it: `python scripts/concurrent_drivers_demo.py --drivers 20` against a running server.

Evaluation: the "ranker + holds" row in `eval/results.md` now runs the real `ReservationManager`.

---

## Version 1: ranking and charging model

## What changed and why

| Area | Before | Now |
|---|---|---|
| Ranking objective | Weighted sum of distance, travel, wait, rated kW, cost, rating, reliability. The "Estimated total" on the card was not what was ranked. | Ranks on **expected total time** (travel + wait + charge for the user's own battery) plus cost, availability, reliability and rating. Time and cost use a ratio-to-best scale. |
| Charging speed | Rated charger kW (a 60 kW charger looked fast for a 3.7 kWh battery). | **Delivered kW** from `app/charging_model.py` (battery-aware, max power derived from battery size, AC/DC aware). The frontend now shows the backend's numbers. |
| Weights | Summed past 1.0 under urgency; missing rating/reliability capped the score at 85%; the 0 ports penalty (x0.55) double counted availability. | Weights are renormalised over criteria that have data, urgency boost included. No extra penalty multiplier. |
| Distance | Straight-line distance at 30 km/h. | Straight line x `ROAD_CIRCUITY_FACTOR` (1.3, assumption) at `FALLBACK_SPEED_KMH`. Both configurable. OSRM still used when verified. |
| Connectors | Stations with no listed connector (20 of 47) were silently dropped. | Kept, flagged `unverified`, shown with a badge and a UI note, score x0.85. `INCLUDE_UNVERIFIED_CONNECTORS=false` restores the old behaviour. |
| Demo data | 5 fully occupied stations had a wait of 0. | Fixed (CBE002, CBE004, CBE009, CBE033, CBE047). A test now guards all state invariants. |
| Wait for full stations | Trusted the CSV value even when 0. | Falls back to the occupancy estimate when no port is free and the wait is 0. |
| Tests | 17/18 passing; the failing one depended on live ranking order. | 105 backend + 2 frontend tests passing. |
| CORS | Only `localhost:5173`. | Also `127.0.0.1:5173` and port 5174 (Vite's fallback port). |

## New and changed files
- `backend/app/charging_model.py` (new): Python port of the charging model. `frontend/src/utils/chargingModel.js` is kept only as a reference; `tests/test_charging_model.py` checks both give the same numbers on 384 input combinations.
- `backend/app/recommender.py`: new `rank_candidates` (extra args: `battery_capacity_kwh`, `start_soc`, `end_soc`), `normalize_weights`.
- `backend/app/algorithms.py`: `filter_by_connector`, circuity in the fallback route.
- `backend/app/config.py`, `models.py`, `main.py`, `routing.py`, `.env`, `.env.example`.
- `backend/eval/` (new): `compare_rankers.py` simulation, `legacy_ranker.py` (the original ranking function, for before/after), `results.md` (output).
- `frontend/src/App.tsx`: shows backend charge time, delivered kW, cost and total; unverified-connector note.

## Run
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
python -m eval.compare_rankers --trials 150      # optional: regenerates eval/results.md

cd ../frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Known limits (not fixed here)
- No reservation/hold endpoint: recommendations do not reserve a port, so concurrent users can still be sent to the same station. `eval/results.md` shows this is the largest remaining lever.
- Coordinates are still locality-level synthetic estimates; distances are estimates.
- Every number in `charging_model.py` (C-rates, caps, efficiency), the tariffs in the demo CSV and the circuity factor are assumptions, not measurements.
- Reliability and rating are empty in the CSV, so those criteria are dropped from scoring.
