# EV Charge Optimizer: Technical Description

This description reflects the current workspace files. `NOT FOUND` means no implementation or value was found in the inspected project files.

## 1. OVERVIEW

The app is a Coimbatore EV charging-station recommender for a driver choosing where to charge. The implemented flow is: load the frontend, choose current/target battery, battery capacity, connector, preset origin, and search radius; submit to the FastAPI recommendation endpoint; receive up to three ranked stations; inspect availability, travel/wait/charge estimates, cost, and then open a Google Maps directions URL. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `App`, `findCharger`; [backend/app/main.py](../backend/app/main.py), `recommend`, `data_status`; [backend/app/recommender.py](../backend/app/recommender.py), `maps_url`.

Authentication, user accounts, a destination input, and a true route-detour workflow are **NOT FOUND**. The current radius is from the origin, not a trip destination. Source: [frontend/src/App.tsx](../frontend/src/App.tsx), `LOCATIONS`, `App`; [docs/ALGORITHMS.md](ALGORITHMS.md).

## 2. TECH STACK AND STRUCTURE

**Frontend:** React and React DOM resolve to 19.2.8; TypeScript 5.9.3; Vite 7.3.6; `@vitejs/plugin-react` 4.7.0; React type packages 19.2.18 and 19.2.7. The `package.json` ranges are `react`/`react-dom` `^19.1.1`, TypeScript `^5.8.3`, Vite `^7.1.2`, and plugin `^4.6.0`; exact versions above come from `package-lock.json` (lockfileVersion 3). Build is Vite plus `tsc -b`. Sources: [frontend/package.json](../frontend/package.json), [frontend/package-lock.json](../frontend/package-lock.json), [frontend/tsconfig.json](../frontend/tsconfig.json).

**Backend:** Python packages are pinned in requirements: FastAPI 0.116.1, Uvicorn standard 0.35.0, HTTPX 0.28.1, Pydantic 2.11.7, pydantic-settings 2.10.1, pytest 8.4.1. A Python version pin is **NOT FOUND**. Sources: [backend/requirements.txt](../backend/requirements.txt), [backend/.env.example](../backend/.env.example).

**Two-level project tree:**

```text
backend/
  app/ (algorithms.py, cache.py, collector.py, config.py, historical.py,
        live_data.py, main.py, models.py, ocpi.py, osm.py, queue_model.py,
        recommender.py, repository.py, routing.py, tomtom.py)
  data/ (coimbatore_ev_stations_replica_demo_synthetic.csv, stations.json,
         verified_origin_coordinates.json, verified_station_coordinates.json)
  tests/ (test_csv_integration.py, test_hybrid.py, test_recommender.py)
  requirements.txt
  .env.example
frontend/
  src/ (App.tsx, main.tsx, styles.css, utils/chargingModel.js,
        utils/chargingModel.d.ts, utils/chargingModel.test.js)
  index.html
  package.json
  package-lock.json
  tsconfig.json
docs/
  ALGORITHMS.md
  TECHNICAL_DESCRIPTION.md
```

The browser entry is `frontend/src/main.tsx` (`ReactDOM.createRoot`, renders `App`); the UI and form handler are in `frontend/src/App.tsx` (`App`, `findCharger`). The backend entry is `backend/app/main.py` (`app`, FastAPI routes). Sources: [frontend/src/main.tsx](../frontend/src/main.tsx), [frontend/src/App.tsx](../frontend/src/App.tsx), [backend/app/main.py](../backend/app/main.py).

**Install/run commands** (also recorded in the workspace-root `cmd.txt`; run the terminals separately):

```bash
cd ev-charge-optimizer/backend
python3 -m venv .venv-linux
source .venv-linux/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
cd ev-charge-optimizer/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

`npm run build` runs `tsc -b && vite build`; `npm test` runs Node's built-in test runner for the charging model. Sources: [cmd.txt](../../cmd.txt), [frontend/package.json](../frontend/package.json).

**Environment configuration:** Pydantic Settings reads `.env` (`Settings.model_config`). Defaults/configurable names in [backend/app/config.py](../backend/app/config.py), `Settings`, and [backend/.env.example](../backend/.env.example): `TOMTOM_API_KEY` (unset); `OCPI_BASE_URL`/`OCPI_TOKEN` (unset); OCPI endpoints `/locations`, `/status`; Overpass URL `https://overpass-api.de/api/interpreter`; routing mode `academic`, algorithm `dijkstra`, OSRM URL unset; station/live refresh 3600/180 seconds; queue model `occupancy_estimate`; historical/data/coordinate paths unset; default battery 60 kWh; OSM refresh false; CORS origin `http://localhost:5173`. The eight configurable recommendation weights and defaults are documented in section 4.

There is a backend HTTP API (`/health`, `/api/stations`, `/api/data-status`, `POST /api/recommend`) and **no database implementation or database dependency was found**. Not all data/computation is in the browser: the backend loads station records, filters/ranks recommendations, and returns them; the browser computes the final vehicle-specific charging estimate from each returned station. Sources: [backend/app/main.py](../backend/app/main.py), `health`, `stations`, `data_status`, `recommend`; [backend/app/repository.py](../backend/app/repository.py), `StationRepository`; [frontend/src/App.tsx](../frontend/src/App.tsx), `findCharger`, `App`.

## 3. DATA

### Files and loading

| Input | How code loads/uses it |
|---|---|
| `backend/data/coimbatore_ev_stations_replica_demo_synthetic.csv` | Default `StationRepository` data file; `csv.DictReader` with UTF-8 BOM handling; `_csv_station` validates/converts selected columns. Current workspace data: 47 rows, all `dynamic_data_source=synthetic_demo_state`. Sources: [backend/app/repository.py](../backend/app/repository.py), `DATA_FILE`, `_load_csv`, `_csv_station`; [backend/app/main.py](../backend/app/main.py), repository initialization. |
| `backend/data/stations.json` | Alternate station dataset only when `STATION_DATA_PATH` selects a `.json` file; decoded with `json.loads`, required to be an array of `Station` model records. It is **not** the default. Sources: [backend/app/repository.py](../backend/app/repository.py), `StationRepository._load`; [backend/app/config.py](../backend/app/config.py), `station_data_path`. |
| `backend/data/verified_station_coordinates.json` | Coordinate overlay keyed by station ID; validates numeric latitude/longitude and `source` beginning `verified_`; applies a deep model copy. Current file is `{}`. Sources: [backend/app/repository.py](../backend/app/repository.py), `_apply_verified_coordinates`; [backend/app/main.py](../backend/app/main.py), repository initialization. |
| `backend/data/verified_origin_coordinates.json` | Preset-origin coordinate overlay keyed by origin ID, with numeric latitude/longitude and `source` beginning `verified_`. Current file is `{}`. Sources: [backend/app/repository.py](../backend/app/repository.py), `load_verified_origins`; [backend/app/main.py](../backend/app/main.py), `recommend`. |
| `/api/recommend` request/response | Browser POSTs journey inputs; backend responds with `required_energy_kwh`, `recommendations`, urgency, and status. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `findCharger`; [backend/app/models.py](../backend/app/models.py), `RecommendationRequest`, `RecommendationResponse`; [backend/app/main.py](../backend/app/main.py), `recommend`. |
| OCPI, TomTom, Overpass, OSRM | Optional backend HTTP data/routing providers; configuration and actual use described in sections 2, 6, and 10. Sources: [backend/app/collector.py](../backend/app/collector.py), `StationCollector`; [backend/app/live_data.py](../backend/app/live_data.py), `refresh_live_data`; [backend/app/routing.py](../backend/app/routing.py), `RoutingService`. |
| Historical CSV | A path setting and CSV/rate helper functions exist, but no historical CSV file or call site wiring them into recommendations was found. **NOT FOUND** as active data input. Sources: [backend/app/config.py](../backend/app/config.py), `historical_csv_path`; [backend/app/historical.py](../backend/app/historical.py), `load_historical_data`, `estimate_arrival_rate`, `estimate_service_rate`, `get_peak_factor`; search of `backend/app` call sites. |

The JSON API does not cause the frontend to load the station CSV: the backend repository reads it at startup, populates `StationCache`, and `findCharger` calls only `POST /api/recommend`. `GET /api/stations` and `/api/data-status` exist but are not called by `App`. Sources: [backend/app/main.py](../backend/app/main.py), module initialization and route functions; [frontend/src/App.tsx](../frontend/src/App.tsx), `findCharger`.

### CSV column inventory

CSV parsing yields text cells; the semantic type below describes the content. `NOT USED` means the current repository adapter does not map that column into `Station`. For mapped columns, `_csv_station` is the mapper and `App` is the browser renderer. Source for all rows: [backend/app/repository.py](../backend/app/repository.py), `REQUIRED_CSV_COLUMNS`, `_csv_station`; [backend/app/models.py](../backend/app/models.py), `Station`; [frontend/src/App.tsx](../frontend/src/App.tsx), `Recommendation`, `App`.

| CSV field | Semantic type | Mapping / UI use |
|---|---|---|
| `station_id` | text ID | `Station.station_id`; React key, not displayed as text. |
| `station_name` | text | `Station.name`; card heading. |
| `address` | text | `Station.address`; included in backend-generated navigation destination, not rendered on card. |
| `connector_types` | delimited text/list | split on `;` or `,`; backend connector compatibility filter. |
| `reported_slot_count` | integer-like text | NOT USED. |
| `contact_phone` | text | NOT USED. |
| `opening_hours` | text | `Station.opening_hours`; NOT displayed. |
| `source_url` | URL/text | `Station.source_url`; NOT displayed. |
| `listing_operator` | text | `Station.operator`, fallback `Unknown`; NOT displayed. |
| `reported_power` | unit-bearing text | NOT USED. |
| `reported_status` | category/text | NOT USED; code uses `sim_station_status`. |
| `source_name` | category/text | `Station.source_name`; API field, NOT rendered by `App`. |
| `record_note` | text | NOT USED. |
| `latitude` | float text | `Station.latitude`; backend distance/routing; not shown on card. |
| `longitude` | float text | `Station.longitude`; backend distance/routing; not shown on card. |
| `coordinate_source` | category/text | `Station.coordinate_source`; recommendation metadata; card instead shows route-source wording. |
| `coordinate_note` | text | `Station.coordinate_note`; NOT rendered. |
| `sim_total_ports` | integer text | `Station.total_ports`; Availability card metric. |
| `sim_available_ports` | integer text | `Station.available_ports`; Availability and reason badge. |
| `sim_occupied_ports` | integer text | `Station.occupied_ports`; queue wait estimator. |
| `sim_queue_length` | integer text | `Station.queue_length`; Queue card metric. |
| `sim_estimated_wait_min` | optional float text | `Station.estimated_wait_min`; Wait card metric for synthetic source; blank becomes `0.0`. |
| `sim_charging_power` | unit-bearing text | first numeric substring converted to `Station.charging_speed_kw`; Charger Power and charging-model input. |
| `sim_price_inr_per_kwh` | float text | `Station.cost_per_kwh`; displayed tariff and charging-model input. |
| `sim_station_status` | status category/text | `Station.status`; filters non-operational candidates. |
| `simulation_timestamp` | ISO datetime text | `Station.station_last_updated`; not included in recommendation UI data. |
| `dynamic_data_source` | category/text | `Station.dynamic_data_source`/initial `live_source`; data-source tag and simulated-price label. |
| `latitude_original` | float text | NOT USED. |
| `longitude_original` | float text | NOT USED. |
| `dist_to_center_km` | float text | NOT USED. |
| `nearest_station_km` | float text | NOT USED. |
| `connector_class` | category (`DC`, `AC_TYPE2`, `AC_3PIN`, `UNKNOWN`) | `Station.connector_class`; recommendation API; selects AC/DC charging-model behavior. Missing value defaults to `UNKNOWN`. |
| `connector_normalized` | delimited text/list | NOT USED; backend normalizes `connector_types` instead. |
| `sim_charging_power_original` | unit-bearing text | NOT USED. |
| `power_kw` | float text | NOT USED; adapter uses `sim_charging_power`. |
| `power_source` | category/text | NOT USED. |
| `charger_speed_class` | category/text | NOT USED. |
| `sim_price_inr_per_kwh_original` | float text | NOT USED. |
| `tariff_inr_per_kwh` | float text | NOT USED by current CSV adapter; `sim_price_inr_per_kwh` supplies `Station.cost_per_kwh` and the model tariff. |
| `effective_kw` | float text | NOT USED. |
| `price_inr_per_hour_per_port` | float text | NOT USED. |
| `station_max_kw` | float text | NOT USED. |
| `station_price_inr_per_hour_all_ports` | float text | NOT USED. |
| `sim_out_of_service_ports` | integer text | NOT mapped by `_csv_station`; model default is zero unless provider state updates it. |

Current CSV distributions: source names ZigWheels 20, CarDekho and/or ZigWheels 12, EV Charge Finder 15; all 47 rows use `synthetic_demo_state`; coordinate-source values are synthetic estimates/fallbacks; connector classes include UNKNOWN 20, DC 21, AC_TYPE2 5, AC_3PIN 1. Current simulated tariffs range INR 11.50–23.50/kWh and parsed charging power ranges 3.3–60 kW. Source: [backend/data/coimbatore_ev_stations_replica_demo_synthetic.csv](../backend/data/coimbatore_ev_stations_replica_demo_synthetic.csv), columns `source_name`, `dynamic_data_source`, `coordinate_source`, `connector_class`, `sim_price_inr_per_kwh`, `sim_charging_power`; counts/ranges computed from its current rows.

Other transformations/defaults: `_required_text` rejects blank required fields; `_number` rejects non-numeric fields; `_power_kw` extracts the first numeric token; `_connectors` splits connector strings; blank simulated wait becomes zero; blank operator becomes `Unknown`; blank/missing connector class becomes `UNKNOWN`; `_load` rejects duplicate station IDs. Source: [backend/app/repository.py](../backend/app/repository.py), `_required_text`, `_number`, `_power_kw`, `_connectors`, `_csv_station`, `StationRepository._load`.

`Station` defaults `rating=0`, `reliability_score=None`, queue and port counters to zero, route distance/time to `None`, and dynamic source to `static`; CSV adapter does not set rating or reliability, so the default CSV recommendations have no measured reliability/rating. Sources: [backend/app/models.py](../backend/app/models.py), `Station`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station`; [frontend/src/App.tsx](../frontend/src/App.tsx), reliability metric.

## 4. RECOMMENDATION AND RANKING ALGORITHM

The backend first selects permitted statuses and matching connectors, uses Haversine radius filtering, obtains/estimates route data, then `rank_candidates` keeps the top three with a bounded min-heap. Source: [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/app/algorithms.py](../backend/app/algorithms.py), `spatial_filter`, `haversine_distance`; [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates`.

**Exact score/match code — full `rank_candidates` function:** [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates`.

```python
def rank_candidates(
    stations,
    latitude: float,
    longitude: float,
    top_k: int = 3,
    battery_urgency: str = "LOW",
    weights: dict[str, float] | None = None,
    queue_model: str | None = None,
) -> list[Recommendation]:

    if not stations:
        return []

    # ----------------------------------------------------
    # Road graph calculation.
    # ----------------------------------------------------

    osrm_attempt_failed = any(
        station.route_source == "osrm_unavailable"
        for station in stations
    )
    if (
        not any(station.travel_time_min is not None for station in stations)
        and not osrm_attempt_failed
    ):
        stations = apply_road_network_distance(stations, latitude, longitude)

    # ----------------------------------------------------
    # Do not rank failed routes. A missing route is an unavailable candidate,
    # not a large travel time that can leak into the result card.
    stations = [
        station
        for station in stations
        if station.road_distance_km is not None
        and station.travel_time_min is not None
    ]
    if not stations:
        return []

    max_distance = max(
        station.road_distance_km
        for station in stations
    )

    max_travel_time = max(
        station.travel_time_min
        for station in stations
    )

    max_speed = max(
        station.charging_speed_kw
        for station in stations
    )

    min_cost = min(
        station.cost_per_kwh
        for station in stations
    )

    max_cost = max(
        station.cost_per_kwh
        for station in stations
    )

    wait_values = [
        _wait_estimate(station, queue_model or get_settings().queue_model)[0]
        for station in stations
    ]
    max_wait = max(wait_values, default=0.0)
    score_weights = weights or get_settings().recommendation_weights
    if battery_urgency in {"HIGH", "CRITICAL"}:
        score_weights = {
            **score_weights,
            "travel_time": score_weights["travel_time"] + 0.05,
            "availability": score_weights["availability"] + 0.05,
            "distance": score_weights["distance"] + 0.02,
        }

    heap = []

    for station in stations:

        availability_ratio = (
            station.available_ports
            / max(
                station.total_ports,
                1,
            )
        )

        distance_score = inverse_normalize(
            station.road_distance_km,
            0,
            max_distance,
        )

        travel_score = inverse_normalize(
            station.travel_time_min,
            0,
            max_travel_time,
        )

        speed_score = (
            station.charging_speed_kw
            / max(
                max_speed,
                1,
            )
        )

        availability_score = clamp(
            availability_ratio,
            0,
            1,
        )

        cost_score = inverse_normalize(
            station.cost_per_kwh,
            min_cost,
            max_cost,
        )

        rating_score = (
            station.rating / 5.0
        )

        reliability_score = station.reliability_score or 0.0

        wait_minutes, wait_source = _wait_estimate(
            station,
            queue_model or get_settings().queue_model,
        )

        wait_score = inverse_normalize(
            wait_minutes,
            0,
            max_wait,
        )

        if max_distance == 0:
            distance_score = 1.0
        if max_travel_time == 0:
            travel_score = 1.0

        score = (
            score_weights["distance"]
            * distance_score

            + score_weights["travel_time"]
            * travel_score

            + score_weights["charging_speed"]
            * speed_score

            + score_weights["availability"]
            * availability_score

            + score_weights["cost"]
            * cost_score

            + score_weights["rating"]
            * rating_score

            + score_weights["reliability"]
            * reliability_score

            + score_weights["wait_time"]
            * wait_score
        )

        # Hard operational penalty.
        #
        # A station with no available ports can still be
        # recommended, but it should not beat a clearly
        # available station merely because it is nearby.
        if station.available_ports == 0:
            score *= 0.55

        score = clamp(
            score,
            0,
            1,
        )

        reasons = []

        if station.available_ports > 0:
            reasons.append(
                f"{station.available_ports} "
                f"ports currently available"
            )
        else:
            reasons.append(
                "No port currently available"
            )

        if station.charging_speed_kw >= 100:
            reasons.append(
                "High-power fast charging"
            )
        elif station.charging_speed_kw >= 60:
            reasons.append(
                "Fast charging capability"
            )

        if station.travel_time_min <= 10:
            reasons.append(
                "Low travel-time overhead"
            )

        if (station.reliability_score or 0.0) >= 0.94:
            reasons.append(
                "High reliability score"
            )

        if station.live_data:
            reasons.append(
                "Live availability"
            )

        item = (
            score,
            station.station_id,
            station,
            wait_minutes,
            reasons,
            wait_source,
        )

        if len(heap) < top_k:
            heappush(heap, item)

        elif score > heap[0][0]:
            heappop(heap)
            heappush(heap, item)

        logger.info(
            "recommendation station=%s distance_km=%.2f travel_time_min=%.1f "
            "availability=%d/%d wait_min=%.1f cost=%.2f "
            "rating=%.2f reliability=%.2f urgency=%s score=%.4f",
            station.station_id,
            station.road_distance_km,
            station.travel_time_min,
            station.available_ports,
            station.total_ports,
            wait_minutes,
            station.cost_per_kwh,
            station.rating,
            station.reliability_score or 0.0,
            battery_urgency,
            score,
        )

    results = []

    while heap:

        (
            score,
            _station_id,
            station,
            wait_minutes,
            reasons,
            wait_source,
        ) = heappop(heap)

        results.append(
            Recommendation(
                rank=0,

                station_id=station.station_id,
                name=station.name,
                operator=station.operator,
                address=station.address,
                source_name=station.source_name,
                coordinate_source=station.coordinate_source,
                coordinate_verified=station.coordinate_verified,
                dynamic_data_source=station.dynamic_data_source,
                route_source=station.route_source,

                latitude=station.latitude,
                longitude=station.longitude,

                score=round(score, 4),
                score_percent=round(
                    score * 100,
                    1,
                ),

                road_distance_km=round(
                    station.road_distance_km,
                    2,
                ),

                travel_time_min=round(
                    station.travel_time_min,
                    1,
                ),

                available_ports=(
                    station.available_ports
                ),

                total_ports=(
                    station.total_ports
                ),

                queue_length=station.queue_length,

                charging_speed_kw=(
                    station.charging_speed_kw
                ),

                cost_per_kwh=(
                    station.cost_per_kwh
                ),
                connector_class=station.connector_class,

                rating=station.rating,

                reliability_score=(
                    station.reliability_score
                ),

                estimated_wait_min=round(
                    wait_minutes,
                    1,
                ),

                live_data=station.live_data,

                live_source=station.live_source,
                last_updated=station.live_last_updated,
                connector_compatibility="compatible",
                battery_urgency=battery_urgency,
                queue_model_source=wait_source,

                reasons=reasons,

                navigation_url=maps_url(
                    station.name,
                    station.address,
                ),
            )
        )

    results.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    for index, result in enumerate(
        results,
        start=1,
    ):
        result.rank = index

    return results
```

**Match formula:** `score_percent = round(clamp(weighted_score, 0, 1) * 100, 1)`, quoted in `rank_candidates` above. Each numeric criterion is normalized over the current candidate set: lower distance, travel time, wait, and price produce higher scores; speed, availability ratio, and rating/reliability produce higher scores. The charging-speed score uses station-rated `charging_speed_kw`, not the later vehicle-limited frontend power model. Sources: [backend/app/recommender.py](../backend/app/recommender.py), `inverse_normalize`, `rank_candidates`; [frontend/src/App.tsx](../frontend/src/App.tsx), score display.

Weights defined in [backend/app/config.py](../backend/app/config.py), `Settings.recommendation_weights`: distance 0.10, travel time 0.20, availability 0.20, wait 0.15, charging speed 0.15, cost 0.05, rating 0.05, reliability 0.10. Their sum is 1.0 in the normal case. `DEFAULT_WEIGHTS` in [backend/app/recommender.py](../backend/app/recommender.py) duplicates the same numbers. Settings/environment may change the weights; there is no weight input in the form. For HIGH/CRITICAL urgency, code adds 0.05 to travel-time and availability and 0.02 to distance without renormalizing; final score is then clamped to 1.0. Top-k defaults to 3 and the API explicitly passes 3. Sources: [backend/app/config.py](../backend/app/config.py), `Settings`; [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/app/recommender.py](../backend/app/recommender.py), `DEFAULT_WEIGHTS`, `rank_candidates`.

Exact normalization helpers, quoted from [backend/app/recommender.py](../backend/app/recommender.py), `clamp`, `inverse_normalize`:

```python
def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:

    return max(
        minimum,
        min(maximum, value),
    )


def inverse_normalize(
    value: float,
    minimum: float,
    maximum: float,
) -> float:

    if maximum <= minimum:
        return 1.0

    return 1.0 - (
        (value - minimum)
        / (maximum - minimum)
    )
```

**Distance and travel inputs to ranking:** Haversine straight-line distance is used first to exclude candidates beyond the radius, and the default CSV route estimate again uses Haversine distance with a 30 km/h assumed speed. For non-CSV legacy stations with a graph-node mapping, Dijkstra uses hard-coded edge distances and times. Optional OSRM is described in section 6. Sources: [backend/app/algorithms.py](../backend/app/algorithms.py), `haversine_distance`, `spatial_filter`, `dijkstra`, `apply_road_network_distance`; [backend/app/routing.py](../backend/app/routing.py), `RoutingService`.

**Wait and queue:** Synthetic demo records return their CSV wait value. Other records use the configured occupancy or M/M/c model. The queue count shown in the UI is the station's `queue_length` field; the M/M/c expected queue length is calculated but not returned to the card as its queue count. Sources: [backend/app/recommender.py](../backend/app/recommender.py), `_wait_estimate`; [backend/app/queue_model.py](../backend/app/queue_model.py), `estimate_wait_minutes`, `mmc_wait_minutes`; [frontend/src/App.tsx](../frontend/src/App.tsx), `App` queue/wait metrics.

```python
def _wait_estimate(station, queue_model: str) -> tuple[float, str]:
    if station.dynamic_data_source == "synthetic_demo_state":
        return station.estimated_wait_min, station.dynamic_data_source
    return estimate_wait_minutes(
        station.available_ports,
        station.occupied_ports,
        station.reserved_ports,
        station.charging_speed_kw,
        queue_model,
    )
```

Full queue functions from [backend/app/queue_model.py](../backend/app/queue_model.py), `mmc_wait_minutes`, `estimate_wait_minutes`:

```python
import math


def mmc_wait_minutes(lambda_arrival: float, mu_service: float, number_of_ports: int) -> tuple[float, float, float]:
    """Return utilization, expected queue length, and wait in minutes."""
    if lambda_arrival <= 0 or mu_service <= 0 or number_of_ports <= 0:
        return 0.0, 0.0, 0.0
    capacity = number_of_ports * mu_service
    utilization = lambda_arrival / capacity
    if utilization >= 1:
        return min(utilization, 10.0), math.inf, math.inf
    rho = utilization
    probability_empty = 1.0 / sum((number_of_ports * rho) ** n / math.factorial(n) for n in range(number_of_ports))
    probability_empty /= 1 + ((number_of_ports * rho) ** number_of_ports / math.factorial(number_of_ports)) * (1 / (1 - rho))
    lq = probability_empty * ((number_of_ports * rho) ** number_of_ports * rho) / (math.factorial(number_of_ports) * (1 - rho) ** 2)
    return rho, lq, lq / lambda_arrival * 60


def estimate_wait_minutes(available_ports: int, occupied_ports: int, reserved_ports: int, charging_speed_kw: float, model: str = "occupancy_estimate") -> tuple[float, str]:
    if model == "mmc":
        service_rate = max(charging_speed_kw, 30.0) / 60.0 / 45.0
        _, _, wait = mmc_wait_minutes(max(occupied_ports, 1) / 45.0, service_rate, max(available_ports + occupied_ports, 1))
        return (0.0 if math.isinf(wait) else wait), "simulation"
    if available_ports > 0:
        return 0.0, "occupancy_estimate"
    return max(0.0, (occupied_ports + reserved_ports * 0.5) * max(30.0, 45.0 - min(charging_speed_kw, 120.0) * 0.08)), "occupancy_estimate"
```

`queue_length` itself is **not** estimated by `estimate_wait_minutes`: CSV `sim_queue_length` is parsed as an integer and displayed; live integrations update port counts, but the inspected `StationCache.update_live_state` does not change `queue_length`. Source: [backend/app/repository.py](../backend/app/repository.py), `_csv_station`; [backend/app/cache.py](../backend/app/cache.py), `update_live_state`; [frontend/src/App.tsx](../frontend/src/App.tsx), Queue metric.

**Charge time and session cost:** calculated in frontend `estimateCharge`, quoted in section 5; total is exactly `travel_time_min + estimated_wait_min + chargeEstimate.minutes`. Reliability is **not calculated** from historical observations in the active code: `rank_candidates` uses `station.reliability_score or 0.0`, while CSV adapter does not populate it. Sources: [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station`; [frontend/src/App.tsx](../frontend/src/App.tsx), `App`.

**Badges/reasons:** `rank_candidates` above constructs `"No port currently available"` when availability is zero; `"Low travel-time overhead"` when travel time is at most 10 minutes; fast-charging badges at rated power thresholds 60/100 kW; reliability badge at 0.94; and live-availability badge if `live_data`. The zero-port candidate is retained but its score is multiplied by 0.55. Source: [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates`.

**Unavailable, ties, missing values:** `recommend` skips statuses outside operational/available/unknown; empty connector lists are marked unknown and omitted from compatible candidates; incompatible listed connectors are excluded. `rank_candidates` drops failed/missing routes. Zero available ports are not excluded, only penalized. The bounded heap admits a new candidate only when its score is strictly greater than the current minimum; an equal-score later candidate does not replace it. Heap tuples include `station_id`, so equal-score heap ordering is also affected by ID ordering; final sort key is score only. `inverse_normalize` returns 1 when max <= min. Missing reliability is scored as zero. Sources: [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/app/recommender.py](../backend/app/recommender.py), `inverse_normalize`, `rank_candidates`.

## 5. CHARGING MODEL

The form has no vehicle max-charging-power field, state, validation, localStorage value, or request parameter. The form provides start SOC (`battery`), end SOC (`targetBattery`), battery capacity, and connector selection. `findCharger` posts capacity and SOC percentages; `App` converts percentages to fractions and calls `estimateCharge` for each returned station. Connector compatibility is checked on the backend using `connector_types`; `estimateCharge` itself selects AC/DC mode from station `connectorClass` and does not compare connectors. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `App`, `findCharger`; [backend/app/main.py](../backend/app/main.py), `RecommendationRequest` handling in `recommend`; [backend/app/algorithms.py](../backend/app/algorithms.py), `connectors_compatible`.

**Full current model code** from [frontend/src/utils/chargingModel.js](../frontend/src/utils/chargingModel.js):

```javascript
// Highest power a battery of this size can safely accept, by size band.
const POWER_TIERS = [
  { maxKwh: 5, cRate: 1.0, capKw: 6 },
  { maxKwh: 15, cRate: 1.0, capKw: 15 },
  { maxKwh: 30, cRate: 1.0, capKw: 30 },
  { maxKwh: 60, cRate: 1.2, capKw: 60 },
  { maxKwh: Infinity, cRate: 2.0, capKw: 150 },
];

// On AC, the vehicle's on-board charger is the limit.
const AC_CAP_TIERS = [
  { maxKwh: 5, capKw: 3.3 },
  { maxKwh: 30, capKw: 7.4 },
  { maxKwh: Infinity, capKw: 11 },
];

const EFFICIENCY = 0.92;

function findTier(tiers, batteryKwh) {
  return tiers.find((tier) => batteryKwh <= tier.maxKwh);
}

function chargerMode(station) {
  if (station.connectorClass === "DC") return "DC";
  if (station.connectorClass === "AC_TYPE2" || station.connectorClass === "AC_3PIN") return "AC";
  return station.powerKw > 22 ? "DC" : "AC";
}

export function maxAcceptKw(batteryKwh, mode) {
  const tier = findTier(POWER_TIERS, batteryKwh);
  let limit = Math.min(batteryKwh * tier.cRate, tier.capKw);
  if (mode === "AC") {
    limit = Math.min(limit, findTier(AC_CAP_TIERS, batteryKwh).capKw);
  }
  return limit;
}

function taper(soc, mode) {
  if (mode === "AC") return 1;
  if (soc < 0.8) return 1;
  if (soc < 0.9) return 0.5;
  return 0.2;
}

export function estimateCharge({ station, batteryKwh, startSoc = 0.1, endSoc = 0.8 }) {
  if (!(batteryKwh > 0)) throw new Error("batteryKwh must be greater than 0");
  if (!(startSoc >= 0 && endSoc <= 1 && startSoc < endSoc)) {
    throw new Error("need 0 <= startSoc < endSoc <= 1");
  }

  const mode = chargerMode(station);
  const vehicleLimitKw = maxAcceptKw(batteryKwh, mode);
  const limitKw = Math.min(station.powerKw, vehicleLimitKw);
  const limitedBy = vehicleLimitKw < station.powerKw ? "battery" : "charger";

  const steps = 100;
  const socStep = (endSoc - startSoc) / steps;
  const energyPerStepKwh = batteryKwh * socStep;
  let minutes = 0;
  for (let index = 0; index < steps; index++) {
    const soc = startSoc + (index + 0.5) * socStep;
    const powerKw = limitKw * taper(soc, mode) * EFFICIENCY;
    minutes += (energyPerStepKwh / powerKw) * 60;
  }

  const energyKwh = batteryKwh * (endSoc - startSoc);
  const billedKwh = energyKwh / EFFICIENCY;
  const cost = billedKwh * station.tariffInrPerKwh;

  return {
    minutes: Math.round(minutes * 10) / 10,
    cost: Math.round(cost * 100) / 100,
    billedKwh: Math.round(billedKwh * 100) / 100,
    energyKwh: Math.round(energyKwh * 100) / 100,
    vehicleLimitKw: Math.round(vehicleLimitKw * 100) / 100,
    powerKw: Math.round(limitKw * EFFICIENCY * 100) / 100,
    limitedBy,
  };
}
```

The browser maps station `charging_speed_kw` to `powerKw`, `connector_class` to `connectorClass`, and `cost_per_kwh` to `tariffInrPerKwh`; it uses current/target battery percent divided by 100 and the user-entered battery capacity. `Power limit` displays `limitedBy` and model-returned delivered `powerKw`; `Charge` uses model `minutes`; cost uses model `cost` when station price is > 0, otherwise UI says `Unavailable`. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `Recommendation`, `App` result mapping; [frontend/src/utils/chargingModel.js](../frontend/src/utils/chargingModel.js), `estimateCharge`.

**Inputs, type, default, validation and use:** [frontend/src/App.tsx](../frontend/src/App.tsx), `App`, `findCharger`; backend constraints: [backend/app/models.py](../backend/app/models.py), `RecommendationRequest`.

| Form control | Type/default | Validation/use |
|---|---|---|
| Current battery | range, 27%; range 0–100 | Sent as `battery_percent`; estimate uses `/100`. Target must exceed it. |
| Target battery | range, 80%; min is current + 1, max 100 | Sent as `target_battery_percent`; backend also rejects target <= current; estimate uses `/100`. |
| Battery capacity | number, 60 kWh; HTML min 0.1, max 500, step 0.1 | Frontend requires finite, >0, <=500; backend Pydantic field >0 and <=500; sent as `battery_capacity_kwh`; controls model tier and energy. |
| Connector | select, CCS2; options CCS2, Type2 | Sent as `connector_type`; backend strips and rejects empty string, normalizes and filters station connectors. |
| Current location | select, default Peelamedu (index 2); five hard-coded presets | Sent as coordinates, source, and origin ID; no browser geolocation. |
| Maximum distance from origin | range, default 10 km; range 1–30 | Sent as `max_detour_km`; API accepts >0 and <=100; backend uses Haversine radius. |
| Vehicle max charging power | **NOT FOUND** in current frontend/API | Removed; `maxAcceptKw` is inferred from battery capacity and AC/DC mode in `chargingModel.js`. |

`Estimated total` is the frontend sum below (source: [frontend/src/App.tsx](../frontend/src/App.tsx), `App` station card):

```tsx
{(
  station.travel_time_min
  + station.estimated_wait_min
  + chargeEstimate.minutes
).toFixed(1)} min
```

The two requested model tests live in [frontend/src/utils/chargingModel.test.js](../frontend/src/utils/chargingModel.test.js), and TypeScript declarations are in [frontend/src/utils/chargingModel.d.ts](../frontend/src/utils/chargingModel.d.ts).

## 6. LOCATION AND DISTANCE

Location is a hard-coded dropdown, not browser GPS. Default index 2 is Peelamedu; presets are RS Puram, Gandhipuram, Peelamedu, Avinashi Road, and PSG College of Technology with literal coordinates. `recommend` prefers an origin sidecar entry keyed by preset ID if present; the current sidecar is empty. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `LOCATIONS`, `App`, `findCharger`; [backend/app/repository.py](../backend/app/repository.py), `load_verified_origins`; [backend/data/verified_origin_coordinates.json](../backend/data/verified_origin_coordinates.json).

Exact Haversine code from [backend/app/algorithms.py](../backend/app/algorithms.py), `haversine_distance`:

```python
def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:

    phi1 = radians(lat1)
    phi2 = radians(lat2)

    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)

    a = (
        sin(d_phi / 2) ** 2
        + cos(phi1)
        * cos(phi2)
        * sin(d_lambda / 2) ** 2
    )

    return (
        2
        * EARTH_RADIUS_KM
        * atan2(
            sqrt(a),
            sqrt(1 - a),
        )
    )
```

The radius-filter implementation from [backend/app/algorithms.py](../backend/app/algorithms.py), `spatial_filter`:

```python
def spatial_filter(
    stations,
    latitude: float,
    longitude: float,
    max_distance_km: float,
):
    candidates = []

    for station in stations:

        distance = haversine_distance(
            latitude,
            longitude,
            station.latitude,
            station.longitude,
        )

        if distance <= max_distance_km:

            station.road_distance_km = distance

            candidates.append(station)

    return candidates
```

For current CSV records, `apply_road_network_distance` intentionally bypasses the legacy CBE graph IDs and uses their dataset coordinates. Exact route assignment from [backend/app/algorithms.py](../backend/app/algorithms.py), `apply_road_network_distance`:

```python
def apply_road_network_distance(
    stations,
    latitude: float,
    longitude: float,
):
    source = nearest_graph_node(
        latitude,
        longitude,
    )

    distances, times, _ = dijkstra(
        ROAD_GRAPH,
        source,
    )

    for station in stations:

        node = (
            STATION_NODE.get(station.station_id)
            if station.source != "coimbatore_csv"
            else None
        )

        if node:
            if node in distances and distances[node] < inf:
                station.road_distance_km = distances[node]
                station.travel_time_min = times[node]
                station.route_source = "academic_study_graph_estimate"
            continue

        # The supplied CSV has synthetic coordinates but no graph-node
        # identity. Use a clearly documented academic estimate rather than a
        # failed-route sentinel in the user-facing result.
        distance_km = haversine_distance(
            latitude,
            longitude,
            station.latitude,
            station.longitude,
        )
        station.road_distance_km = distance_km
        station.travel_time_min = (
            distance_km / ACADEMIC_FALLBACK_SPEED_KMH * 60.0
        )
        station.route_source = "haversine_estimate"

    return stations
```

Graph nodes/edges and their prefilled distance/travel-time values are hard-coded in `ROAD_GRAPH`/`NODE_COORDINATES`. The fallback assumes 30 km/h. Sources: [backend/app/algorithms.py](../backend/app/algorithms.py), `ROAD_GRAPH`, `NODE_COORDINATES`, `nearest_graph_node`, `dijkstra`, `apply_road_network_distance`; [backend/app/config.py](../backend/app/config.py), `routing_mode`, `routing_algorithm`.

Optional OSRM uses `/table/v1/driving` and returns provider distance/duration. In `recommend`, it calls `route_many` only when `ROUTING_MODE=osrm`, and only station/origin pairs with verified coordinates are submitted; other stations use estimates. The sidecars in this workspace are empty, so no bundled endpoint qualifies as verified. Route errors for verified endpoints are omitted from ranking rather than substituted with fabricated travel time. Sources: [backend/app/routing.py](../backend/app/routing.py), `RoutingService.route_many`; [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/data/verified_station_coordinates.json](../backend/data/verified_station_coordinates.json), [backend/data/verified_origin_coordinates.json](../backend/data/verified_origin_coordinates.json).

`approximate, unverified coordinates` is not a geocoder status from a live service: the CSV labels coordinates as synthetic locality estimates/jitter or city fallback, and code leaves `coordinate_verified=False` unless the sidecar overlays them. The UI labels non-OSRM routes approximate/unverified. Sources: [backend/data/coimbatore_ev_stations_replica_demo_synthetic.csv](../backend/data/coimbatore_ev_stations_replica_demo_synthetic.csv), `coordinate_source`, `coordinate_note`; [backend/app/models.py](../backend/app/models.py), `Station.coordinate_verified`; [frontend/src/App.tsx](../frontend/src/App.tsx), station card route text.

`ROUTING_ALGORITHM=astar` is configured and `RoutingService.route` contains an A* branch, but the active API path calls `route_many` for OSRM and the academic helper for estimates; no call site for `routing.route` was found. Thus A* is implemented but **NOT FOUND as active API routing behavior**. Sources: [backend/app/routing.py](../backend/app/routing.py), `RoutingService.route`; [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/app/config.py](../backend/app/config.py), `routing_algorithm`.

Navigation is a direct Google Maps Directions URL made from station name/address plus Coimbatore, not a Google API call; the URL does not include station coordinates. Sources: [backend/app/recommender.py](../backend/app/recommender.py), `maps_url`; [frontend/src/App.tsx](../frontend/src/App.tsx), Navigate anchor.

## 7. STATE AND CONCURRENCY

Form values, recommendations, energy summary, urgency, loading, and error are React `useState` in `App`; `localStorage`/`sessionStorage` is **NOT FOUND**. Availability and reserved/out-of-service counts live in the backend `StationCache` in memory, guarded by a process-local `threading.RLock`; initial values come from repository records and live providers may update them. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `App`; [backend/app/cache.py](../backend/app/cache.py), `StationCache`; [backend/app/main.py](../backend/app/main.py), cache initialization.

`reserved_ports` is a status field supplied by OCPI/TomTom and used as an input to wait estimation; there is no reservation endpoint, hold/checkout action, station lock, or queue-join action. **Reservation behavior: NOT FOUND.** Sources: [backend/app/models.py](../backend/app/models.py), `StationLiveState`, `Station`; [backend/app/ocpi.py](../backend/app/ocpi.py), `normalize_ocpi_status`; [backend/app/tomtom.py](../backend/app/tomtom.py), `parse_availability`; [backend/app/main.py](../backend/app/main.py), all route decorators.

Two users against the same single backend process see the same in-memory cached station state; recommendations do not reserve or mutate a port. Multiple backend processes would have separate caches. No database, cross-process lock, atomic reservation update, optimistic conflict check, or multi-user account/session implementation was found. The cache lock protects individual cache operations only. Sources: [backend/app/cache.py](../backend/app/cache.py), `StationCache`; [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/app/models.py](../backend/app/models.py), request/state models.

## 8. UI

There is one named React UI component, `App`; no separate station-card component or router is present. `main.tsx` mounts it under `React.StrictMode`. Source: [frontend/src/main.tsx](../frontend/src/main.tsx), [frontend/src/App.tsx](../frontend/src/App.tsx), `App`.

`App` shows a hero, journey-parameter form, required-energy/urgency summary, recommendation list, empty/error/loading states, and the Navigate link. Each card displays rank/name, match percentage, live/simulated/static tag, availability, charger rated power, distance, travel estimate, wait, queue count, model charge time, power limiter/delivered kW, price/kWh, estimated session cost, reliability, reason badges, source/update text, route-source text, total time, and navigation. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `App`, `findCharger`; [frontend/src/styles.css](../frontend/src/styles.css), `.metrics`, `.station-card`, media query.

Sorting is done by backend score; there is no user sorting control. The form offers connector, origin, and maximum-distance selection; there are no separate client filters. No map, reservation button, queue-join button, login, or saved preferences are present. Sources: [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates`; [frontend/src/App.tsx](../frontend/src/App.tsx), `App`.

## 9. TESTS AND QUALITY

- [backend/tests/test_recommender.py](../backend/tests/test_recommender.py): Dijkstra and A* shortest-path behavior; available-versus-busy ranking; top-k bound.
- [backend/tests/test_csv_integration.py](../backend/tests/test_csv_integration.py): CSV validation/indexing, connector aliases, graph-ID behavior, coordinate overlays, origin validation, OSRM verified endpoint/matrix behavior, API defaults and navigation URL.
- [backend/tests/test_hybrid.py](../backend/tests/test_hybrid.py): OSM/OCPI normalization, cache lookup, queue models, API fallback status, provider failure retention.
- [frontend/src/utils/chargingModel.test.js](../frontend/src/utils/chargingModel.test.js): 3.7 kWh battery / 25 kW DC station -> 45.7 min, battery-limited; 30 kWh / 7.4 kW AC -> 185.1 min, charger-limited.

`npm run build` performs TypeScript project build and Vite production build; `npm test` uses Node's built-in test runner. A separate lint script/config is **NOT FOUND**. No Python lint/type-check configuration is present. Sources: [frontend/package.json](../frontend/package.json), scripts; [frontend/tsconfig.json](../frontend/tsconfig.json); [backend/requirements.txt](../backend/requirements.txt).

Latest observed checks: the two Node charging tests pass and frontend build passes. Backend suite has 18 test functions; 17 pass and `test_osrm_api_requires_both_verified_endpoints` fails while looking for CBE010 in returned recommendations (`StopIteration`). Source: [backend/tests/test_csv_integration.py](../backend/tests/test_csv_integration.py), `test_osrm_api_requires_both_verified_endpoints`.

Project-source TODO/FIXME markers: **NOT FOUND** (search was limited to `backend/app`, `backend/tests`, `frontend/src`, and `docs`; installed virtualenv dependencies were excluded).

## 10. ASSUMPTIONS AND LIMITS

- **Charging-model assumptions:** power tiers are 5/15/30/60 kWh bands with C-rates 1.0/1.0/1.0/1.2 and caps 6/15/30/60 kW; above 60 kWh uses C-rate 2.0 and cap 150 kW. AC caps are 3.3/7.4/11 kW at 5/30/above-30 kWh bands. Efficiency is 0.92. DC taper is full below 80% SOC, 0.5 from 80–90%, and 0.2 at/above 90%; AC does not taper. The model uses 100 slices and default SOC fractions 0.1/0.8; UI passes actual selected current/target percentages. These are hard-coded heuristics; measured vehicle specifications are **NOT FOUND**. Source: [frontend/src/utils/chargingModel.js](../frontend/src/utils/chargingModel.js), `POWER_TIERS`, `AC_CAP_TIERS`, `EFFICIENCY`, `chargerMode`, `maxAcceptKw`, `taper`, `estimateCharge`.
- **Charge model limitations:** unknown connector class guesses DC only if charger power >22 kW, otherwise AC; `limitedBy` is battery only if vehicle limit is strictly lower than station power (equal is charger-limited). User connector compatibility is filtered by backend connector type, separately from model's AC/DC classification. Source: [frontend/src/utils/chargingModel.js](../frontend/src/utils/chargingModel.js), `chargerMode`, `estimateCharge`; [backend/app/algorithms.py](../backend/app/algorithms.py), `connectors_compatible`.
- **Battery/input assumptions:** UI defaults current SOC 27%, target 80%, capacity 60 kWh, origin Peelamedu, max radius 10 km, connector CCS2; backend fallback capacity is 60 kWh and consumption default is 0.18 kWh/km. UI accepts capacity >0 and <=500 kWh; backend rejects request capacity >500. Sources: [frontend/src/App.tsx](../frontend/src/App.tsx), `App`, `findCharger`; [backend/app/config.py](../backend/app/config.py), `Settings`; [backend/app/models.py](../backend/app/models.py), `RecommendationRequest`.
- **Tariff assumption:** CSV contains synthetic demo tariffs; repository maps `sim_price_inr_per_kwh`, not the separate `tariff_inr_per_kwh` column. Charge cost is `battery energy / 0.92 * tariff`; no taxes, time-of-use rates, session fees, or measured billing are included. UI labels the row simulated when source is `synthetic_demo_state` and calls zero/nonpositive tariff unavailable. Sources: [backend/app/repository.py](../backend/app/repository.py), `_csv_station`; [frontend/src/utils/chargingModel.js](../frontend/src/utils/chargingModel.js), `estimateCharge`; [frontend/src/App.tsx](../frontend/src/App.tsx), price/cost card.
- **Distance/routing assumptions:** Earth radius 6371 km; fallback speed 30 km/h; graph distances and travel minutes are fixed edge values; current CSV coordinates are explicitly synthetic estimates. The max-distance control tests straight-line distance, not road detour. OSRM is optional and default routing mode is academic. Sources: [backend/app/algorithms.py](../backend/app/algorithms.py), `EARTH_RADIUS_KM`, `ACADEMIC_FALLBACK_SPEED_KMH`, `ROAD_GRAPH`, `haversine_distance`; [backend/app/config.py](../backend/app/config.py), `Settings`; [docs/ALGORITHMS.md](ALGORITHMS.md).
- **Wait assumptions:** occupancy model returns zero wait if any port is available; otherwise it uses occupied ports plus half reserved ports and constants 30, 45, 120, 0.5, 0.08. M/M/c uses 45-minute service duration, minimum 30 kW, and returns zero for infinite wait. Synthetic rows bypass these estimators and use CSV wait values (blank -> 0). Historical rate helpers/peak factor are not connected to the recommender. Sources: [backend/app/queue_model.py](../backend/app/queue_model.py), `estimate_wait_minutes`, `mmc_wait_minutes`; [backend/app/recommender.py](../backend/app/recommender.py), `_wait_estimate`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station`; [backend/app/historical.py](../backend/app/historical.py), historical helpers.
- **Ranking/rating inconsistency:** ranking's charging-speed term uses the station's rated kW, not the model's battery-limited delivered kW. CSV records do not populate rating/reliability, so current data defaults to rating zero/reliability absent; the UI reports reliability N/A. High/critical urgency increases weights without renormalization. Sources: [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station`; [backend/app/models.py](../backend/app/models.py), `Station`; [frontend/src/App.tsx](../frontend/src/App.tsx), reliability display.
- **Live-data limits:** OCPI/TomTom are optional and only apply when configured/provider station identifiers exist. OCPI `get_locations` exists but collector's `refresh_live_data` calls `get_evse_status`; CSV adapter does not populate TomTom availability IDs. OpenStreetMap refresh is disabled by default, and if enabled a nonempty Overpass result replaces cached repository stations rather than merging. Sources: [backend/app/ocpi.py](../backend/app/ocpi.py), `OCPIClient`; [backend/app/live_data.py](../backend/app/live_data.py), `refresh_live_data`; [backend/app/collector.py](../backend/app/collector.py), `refresh_stations`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station`.
- **Potential configuration issue:** default CORS allows `http://localhost:5173`; if Vite must switch to 5174 because 5173 is busy, that origin is not in the default `CORS_ORIGINS`. Source: [backend/app/config.py](../backend/app/config.py), `cors_origins`, `allowed_origins`; [backend/.env.example](../backend/.env.example), `CORS_ORIGINS`.
- **Routing config inconsistency:** `routing_algorithm=astar` has a code branch in `RoutingService.route`, but the API does not call that method; it calls `route_many` only for OSRM and otherwise reaches Dijkstra-based `apply_road_network_distance`. Source: [backend/app/routing.py](../backend/app/routing.py), `RoutingService.route`; [backend/app/main.py](../backend/app/main.py), `recommend`; [backend/app/algorithms.py](../backend/app/algorithms.py), `apply_road_network_distance`.

## 11. SUMMARY TABLE

| Feature | File | Status |
|---|---|---|
| Ranking | [backend/app/recommender.py](../backend/app/recommender.py), `rank_candidates` | Implemented |
| Wait estimation | [backend/app/queue_model.py](../backend/app/queue_model.py), `estimate_wait_minutes`; [backend/app/recommender.py](../backend/app/recommender.py), `_wait_estimate` | Partial: synthetic values for current CSV; occupancy/M/M/c options for other sources |
| Queue display | [frontend/src/App.tsx](../frontend/src/App.tsx), `App`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station` | Implemented as a displayed field; current CSV queue is synthetic data |
| Pricing | [frontend/src/utils/chargingModel.js](../frontend/src/utils/chargingModel.js), `estimateCharge`; [backend/app/repository.py](../backend/app/repository.py), `_csv_station` | Partial: cost formula implemented; current rate data is simulated |
| Reservations | [backend/app/models.py](../backend/app/models.py), `reserved_ports`; [backend/app/main.py](../backend/app/main.py), routes | Missing: status can be ingested; no reservation action/API |
| Multi-user handling | [backend/app/cache.py](../backend/app/cache.py), `StationCache` | Partial: shared per-process in-memory cache with lock; no persistence or cross-process coordination |
| Backend | [backend/app/main.py](../backend/app/main.py), FastAPI routes; [backend/app/repository.py](../backend/app/repository.py) | Implemented |
| Tests | [backend/tests/](../backend/tests/), [frontend/src/utils/chargingModel.test.js](../frontend/src/utils/chargingModel.test.js) | Partial: tests exist; one backend routing integration test currently fails |
