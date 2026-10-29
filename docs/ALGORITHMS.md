# Algorithms

The recommendation pipeline preserves the project's DSA core.

The default station repository loads `backend/data/coimbatore_ev_stations_replica_demo_synthetic.csv` through a validated adapter. Listing fields and synthetic demonstration state remain separate in the `Station` model. The coordinates are approximate synthetic test coordinates, and `synthetic_demo_state` is never treated as live provider data. `STATION_DATA_PATH` can select another compatible dataset without changing the DSA layer.

Verified station coordinates are supplied separately in `backend/data/verified_station_coordinates.json`, keyed by source record ID. Verified preset origins go in `backend/data/verified_origin_coordinates.json`, keyed by the frontend location ID (`RS_PURAM`, `GANDHIPURAM`, `PEELAMEDU`, `AVINASHI_ROAD`, or `PSG_COLLEGE_OF_TECHNOLOGY`). Each entry must include numeric latitude/longitude and a `source` beginning with `verified_`; optionally include a note for station coordinates. Both files are overlays and do not alter the source CSV or preset coordinates. OSRM table routing is used only when both the origin and station have validated sidecar coordinates. Other candidates retain the academic graph or straight-line-based estimate, labeled as estimates. CSV records do not inherit legacy station-ID graph mappings because those IDs identify different listing records. OSRM failure for verified endpoints is not silently replaced with a fabricated travel time.

The current form has no trip destination, so its distance limit is a maximum distance from the origin, not a route detour. An actual trip-detour calculation requires a verified destination and routes for origin-to-destination, origin-to-station, and station-to-destination.

- Station repository/cache: Python `dict`, average station lookup `O(1)`.
- Spatial prefilter: `O(n)` over candidate stations.
- Academic routing: Dijkstra with `heapq`, `O((V + E) log V)` time and `O(V + E)` space.
- OSRM routing: external latency is separate from local algorithmic complexity; academic routing remains available as fallback.
- Queue model: `O(1)` per station for deterministic or M/M/c estimates.
- Weighted scoring: `O(n)` after routing and normalization.
- Top-k selection: bounded min-heap, `O(n log k)` time and `O(k)` space, rather than sorting all candidates.

Overall local work is approximately `O(n + routing_cost + n log k)`. Network latency and provider availability are external concerns and are exposed through data-source fields rather than hidden.

OpenStreetMap refresh is opt-in with `ENABLE_OSM_REFRESH=true`. OCPI and TomTom may supply live status only when configured and available. The bundled CSV is a prototype aggregation of public listings plus synthetic coordinates/state; it is never presented as live occupancy.
