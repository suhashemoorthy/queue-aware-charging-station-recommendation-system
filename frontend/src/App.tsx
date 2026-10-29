import {
  FormEvent,
  useEffect,
  useState
} from "react";


const API_URL =
  "http://localhost:8000";

const formatInr = (amount: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2
  }).format(amount);


interface Recommendation {
  rank: number;

  station_id: string;
  name: string;
  operator: string;
  address: string | null;
  source_name: string;
  coordinate_source: string | null;
  coordinate_verified: boolean;
  dynamic_data_source: string;
  route_source: string;

  latitude: number;
  longitude: number;

  score: number;
  score_percent: number | null;

  road_distance_km: number;
  travel_time_min: number;

  available_ports: number;
  total_ports: number;
  queue_length: number;

  charging_speed_kw: number;
  cost_per_kwh: number;
  connector_class: string;

  rating: number;
  reliability_score: number | null;

  estimated_wait_min: number;

  live_data: boolean;
  live_source: string;
  last_updated: string | null;
  connector_compatibility: string;
  battery_urgency: string;
  queue_model_source: string;
  holds_applied: number;
  app_queue_length: number;
  score_note: string | null;
  algorithm: string;

  // Charging estimate for the user's own battery, computed by the backend.
  charge_time_min: number;
  total_time_min: number;
  session_cost_inr: number | null;
  delivered_kw: number;
  vehicle_limit_kw: number;
  limited_by: "battery" | "charger";

  reasons: string[];

  navigation_url: string;
}


interface ApiResponse {
  algorithm_label: string;
  required_energy_kwh: number;
  recommendations: Recommendation[];
  battery_urgency: string;
  data_status: {
    live_data?: {
      source?: string;
    };
  };
}


const LOCATIONS = [
  {
    id: "RS_PURAM",
    name: "RS Puram",
    latitude: 11.0055,
    longitude: 76.9537,
    coordinate_source: "study_graph_estimate"
  },
  {
    id: "GANDHIPURAM",
    name: "Gandhipuram",
    latitude: 11.0168,
    longitude: 76.9558,
    coordinate_source: "study_graph_estimate"
  },
  {
    id: "PEELAMEDU",
    name: "Peelamedu",
    latitude: 11.0301,
    longitude: 77.0007,
    coordinate_source: "study_graph_estimate"
  },
  {
    id: "AVINASHI_ROAD",
    name: "Avinashi Road",
    latitude: 11.0183,
    longitude: 77.0067,
    coordinate_source: "study_graph_estimate"
  },
  {
    id: "PSG_COLLEGE_OF_TECHNOLOGY",
    name: "PSG College of Technology (approx.)",
    latitude: 11.0242,
    longitude: 76.9344,
    coordinate_source: "synthetic_approximation"
  }
];


interface AlgorithmInfo {
  id: string;
  label: string;
  group: string;
  description: string;
}

interface CompareCase {
  algorithm: string;
  label: string;
  group: string;
  recommendations: Recommendation[];
}

interface Reservation {
  id: string;
  station_id: string;
  status: "HELD" | "QUEUED" | "CHARGING" | "COMPLETED" | "CANCELLED" | "EXPIRED";
  seconds_remaining: number | null;
  queue_position: number | null;
  cars_ahead: number | null;
  estimated_wait_min: number | null;
  promoted_from_queue: boolean;
}

const ACTIVE_STATUSES = ["HELD", "QUEUED", "CHARGING"];

// There is no login in this prototype: a random id kept in the browser stands in for
// the driver, so the server can tell two drivers apart.
function getUserId(): string {
  try {
    const saved = window.localStorage.getItem("ev_user_id");
    if (saved) return saved;
    const created = crypto.randomUUID();
    window.localStorage.setItem("ev_user_id", created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

const USER_ID = getUserId();

async function reservationCall(
  path: string,
  method: "GET" | "POST" | "DELETE",
  body?: object
): Promise<{ ok: boolean; data: any }> {
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function App() {

  const [
    battery,
    setBattery
  ] = useState(27);

  const [
    targetBattery,
    setTargetBattery
  ] = useState(80);

  const [
    batteryCapacity,
    setBatteryCapacity
  ] = useState(60);

  const [
    locationIndex,
    setLocationIndex
  ] = useState(2);

  const [
    detour,
    setDetour
  ] = useState(10);

  const [
    connector,
    setConnector
  ] = useState("CCS2");

  const [
    results,
    setResults
  ] = useState<Recommendation[]>([]);

  const [
    energy,
    setEnergy
  ] = useState<number | null>(null);

  const [
    urgency,
    setUrgency
  ] = useState("LOW");

  const [
    loading,
    setLoading
  ] = useState(false);

  const [
    error,
    setError
  ] = useState("");


  const [
    algorithms,
    setAlgorithms
  ] = useState<AlgorithmInfo[]>([]);

  const [
    algorithm,
    setAlgorithm
  ] = useState("new_ranker");

  const [
    algorithmLabel,
    setAlgorithmLabel
  ] = useState("");

  const [
    compareAll,
    setCompareAll
  ] = useState(false);

  const [
    compareCases,
    setCompareCases
  ] = useState<CompareCase[]>([]);

  // The list of algorithms comes from the backend, so the UI and the API never disagree.
  useEffect(() => {
    fetch(`${API_URL}/api/algorithms`)
      .then((response) => response.json())
      .then((data) => setAlgorithms(data.algorithms ?? []))
      .catch(() => setAlgorithms([]));
  }, []);

  function chooseAlgorithm(id: string) {
    setAlgorithm(id);
    // Re-run straight away when results are already on screen.
    if (results.length > 0) {
      void findCharger({ preventDefault() {} } as FormEvent, id);
    }
  }

  const [
    reservation,
    setReservation
  ] = useState<Reservation | null>(null);

  const [
    reservationNote,
    setReservationNote
  ] = useState<{ stationId: string; text: string } | null>(null);

  const [
    secondsLeft,
    setSecondsLeft
  ] = useState<number | null>(null);

  // Poll the server so promotions from the queue and expired holds show up.
  useEffect(() => {
    if (!reservation || !ACTIVE_STATUSES.includes(reservation.status)) return;
    const timer = window.setInterval(async () => {
      const { ok, data } = await reservationCall(`/api/reservations/${reservation.id}`, "GET");
      if (ok) {
        setReservation(data);
        setSecondsLeft(data.seconds_remaining);
        if (data.status === "EXPIRED") {
          setReservationNote({ stationId: data.station_id, text: "Your hold expired and the port was released." });
        }
      }
    }, 10000);
    return () => window.clearInterval(timer);
  }, [reservation?.id, reservation?.status]);

  // Count the hold down locally between polls.
  useEffect(() => {
    if (secondsLeft === null || secondsLeft <= 0) return;
    const tick = window.setTimeout(() => setSecondsLeft(secondsLeft - 1), 1000);
    return () => window.clearTimeout(tick);
  }, [secondsLeft]);

  function adopt(data: Reservation) {
    setReservation(data);
    setSecondsLeft(data.seconds_remaining);
  }

  async function reservePort(stationId: string) {
    const { ok, data } = await reservationCall("/api/reservations", "POST", {
      station_id: stationId,
      user_id: USER_ID
    });
    if (ok) {
      adopt(data);
      setReservationNote(null);
      return;
    }
    const detail = data.detail ?? {};
    if (detail.error === "station_full") {
      setReservationNote({
        stationId,
        text: "Another driver just took the last port. You can join the queue, or pick another station."
      });
      void findCharger({ preventDefault() {} } as FormEvent);  // refresh the ranking
    } else {
      setReservationNote({ stationId, text: detail.message ?? "Could not reserve this station." });
    }
  }

  async function joinQueue(stationId: string) {
    const { ok, data } = await reservationCall("/api/queue", "POST", {
      station_id: stationId,
      user_id: USER_ID
    });
    if (ok) {
      adopt(data);
      setReservationNote(null);
    } else {
      setReservationNote({
        stationId,
        text: data.detail?.error === "port_available"
          ? "A port just became free: reserve it instead."
          : data.detail?.message ?? "Could not join the queue."
      });
    }
  }

  async function arrived() {
    if (!reservation) return;
    const { ok, data } = await reservationCall(`/api/reservations/${reservation.id}/arrive`, "POST");
    if (ok) adopt(data);
    else setReservationNote({ stationId: reservation.station_id, text: data.detail?.message ?? "Could not start the session." });
  }

  async function releaseReservation() {
    if (!reservation) return;
    const { ok } = await reservationCall(`/api/reservations/${reservation.id}`, "DELETE");
    if (ok) {
      setReservation(null);
      setSecondsLeft(null);
      setReservationNote(null);
      void findCharger({ preventDefault() {} } as FormEvent);  // freed ports show up again
    }
  }

  async function findCharger(
    event: FormEvent,
    algorithmOverride?: string
  ) {

    event.preventDefault();

    setError("");
    setResults([]);
    setCompareCases([]);

    if (targetBattery <= battery) {
      setError(
        "Target battery must be greater than current battery."
      );

      return;
    }

    if (!Number.isFinite(batteryCapacity) || batteryCapacity <= 0 || batteryCapacity > 500) {
      setError("Battery capacity must be greater than 0 and no more than 500 kWh.");

      return;
    }

    setLoading(true);

    const location =
      LOCATIONS[locationIndex];


    try {

      const requestBody = JSON.stringify({
        latitude: location.latitude,
        longitude: location.longitude,
        origin_coordinate_source: location.coordinate_source,
        origin_id: location.id,
        battery_percent: battery,
        target_battery_percent: targetBattery,
        battery_capacity_kwh: batteryCapacity,
        max_detour_km: detour,
        connector_type: connector,
        algorithm: algorithmOverride ?? algorithm
      });
      const post = (path: string) =>
        fetch(`${API_URL}${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: requestBody
        });

      const response = await post("/api/recommend");

      const data =
        await response.json();


      if (!response.ok) {
        throw new Error(
          data.detail ||
          "Recommendation request failed."
        );
      }


      const result =
        data as ApiResponse;


      setEnergy(
        result.required_energy_kwh
      );

      setUrgency(
        result.battery_urgency
      );

      setResults(
        result.recommendations
      );

      setAlgorithmLabel(
        result.algorithm_label
      );

      if (compareAll) {
        const compared = await post("/api/compare");
        if (compared.ok) {
          setCompareCases((await compared.json()).cases ?? []);
        }
      }

    } catch (err) {

      setError(
        err instanceof Error
          ? err.message
          : "Unable to contact backend."
      );

    } finally {

      setLoading(false);
    }
  }


  return (
    <main className="page">

      <section className="hero">

        <div className="eyebrow">
          EV CHARGE OPTIMIZER
        </div>

        <h1>
          Charge intelligently.
        </h1>

        <p>
          A multi-criteria charging
          recommendation engine for
          Coimbatore.
        </p>

      </section>


      <section className="workspace">

        <form
          className="control-panel"
          onSubmit={findCharger}
        >

          <div className="section-title">
            Journey parameters
          </div>


          <div className="grid">

            <label>
              <span>
                Current battery
              </span>

              <div className="input-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={battery}
                  onChange={(event) =>
                    setBattery(
                      Number(event.target.value)
                    )
                  }
                />

                <strong>
                  {battery}%
                </strong>
              </div>
            </label>


            <label>
              <span>
                Target battery
              </span>

              <div className="input-row">
                <input
                  type="range"
                  min={battery + 1}
                  max="100"
                  value={targetBattery}
                  onChange={(event) =>
                    setTargetBattery(
                      Number(event.target.value)
                    )
                  }
                />

                <strong>
                  {targetBattery}%
                </strong>
              </div>
            </label>


            <label>
              <span>
                Battery capacity (kWh)
              </span>

              <input
                type="number"
                min="0.1"
                max="500"
                step="0.1"
                value={batteryCapacity}
                onChange={(event) =>
                  setBatteryCapacity(
                    Number(event.target.value)
                  )
                }
              />
            </label>


            <label>
              <span>
                Connector
              </span>

              <select
                value={connector}
                onChange={(event) =>
                  setConnector(
                    event.target.value
                  )
                }
              >
                <option value="CCS2">
                  CCS2
                </option>

                <option value="Type2">
                  Type 2
                </option>
              </select>
            </label>


            <label>
              <span>
                Current location
              </span>

              <select
                value={locationIndex}
                onChange={(event) =>
                  setLocationIndex(
                    Number(event.target.value)
                  )
                }
              >
                {LOCATIONS.map(
                  (location, index) => (
                    <option
                      key={location.name}
                      value={index}
                    >
                      {location.name}
                    </option>
                  )
                )}
              </select>
            </label>


            <label>
              <span>
                Maximum distance from origin
              </span>

              <div className="input-row">
                <input
                  type="range"
                  min="1"
                  max="30"
                  value={detour}
                  onChange={(event) =>
                    setDetour(
                      Number(event.target.value)
                    )
                  }
                />

                <strong>
                  {detour} km
                </strong>
              </div>
            </label>

            <label className="wide">
              <span>
                Ranking algorithm
              </span>

              <select
                value={algorithm}
                onChange={(event) => chooseAlgorithm(event.target.value)}
              >
                {Array.from(new Set(algorithms.map((item) => item.group))).map((group) => (
                  <optgroup key={group} label={group}>
                    {algorithms
                      .filter((item) => item.group === group)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                  </optgroup>
                ))}
                {algorithms.length === 0 && (
                  <option value="new_ranker">New ranker (current)</option>
                )}
              </select>

              <small className="algorithm-help">
                {algorithms.find((item) => item.id === algorithm)?.description}
              </small>

              <span className="inline-check">
                <input
                  type="checkbox"
                  checked={compareAll}
                  onChange={(event) => setCompareAll(event.target.checked)}
                />
                Also compare all algorithms side by side
              </span>
            </label>


          </div>


          {error && (
            <div
              className="error"
              role="alert"
            >
              {error}
            </div>
          )}


          <button
            className="primary-button"
            type="submit"
            disabled={loading}
          >
            {loading
              ? "Computing..."
              : "Find optimal charger"}
          </button>

        </form>


        {energy !== null && (
          <div className="energy-summary">
            Required energy:
            <strong>
              {energy} kWh
            </strong>
            <strong>
              Battery urgency: {urgency}
            </strong>
          </div>
        )}


        <section className="results">

          <div className="section-title">
            Recommendations
          </div>


          {results.length === 0 &&
            !loading && (
              <div className="empty">
                Enter your journey parameters
                to calculate the best charging
                stations.
              </div>
            )}


          {results.length > 0 && algorithmLabel && (
            <p className="ranked-by">
              Ranked by: <strong>{algorithmLabel}</strong>
            </p>
          )}

          {results.map(
            (station) => {
              return (
              <article
                className={
                  station.rank === 1
                    ? "station-card featured"
                    : "station-card"
                }
                key={station.station_id}
              >

                <div className="card-top">

                  <div>

                    <div className="rank">
                      #{station.rank}
                      {station.rank === 1
                        ? " BEST MATCH"
                        : ""}
                    </div>

                    <h2>
                      {station.name}
                    </h2>

                  </div>


                  <div
                    className="score"
                    title="Relative score among the nearby options (travel + wait + charge time, cost, availability)."
                  >

                    {station.score_percent !== null ? (
                      <>
                        <strong>
                          {station.score_percent}%
                        </strong>

                        <span>
                          {station.algorithm === "topsis" ? "closeness" : "match"}
                        </span>
                      </>
                    ) : (
                      <span>{station.score_note}</span>
                    )}

                  </div>

                  <div className="data-source">
                    {station.live_data
                      ? `LIVE - ${station.live_source}`
                      : station.dynamic_data_source === "synthetic_demo_state"
                        ? "SIMULATED"
                        : "STATIC"}
                  </div>

                </div>


                <div className="metrics">

                  <div>
                    <span>
                      Availability
                    </span>

                    <strong>
                      {
                        station.available_ports
                      }
                      {" / "}
                      {
                        station.total_ports
                      } ports
                    </strong>
                  </div>


                  <div>
                    <span>
                      Charger Power
                    </span>

                    <strong>
                      {
                        station.charging_speed_kw
                      } kW
                    </strong>
                  </div>


                  <div>
                    <span>
                      {station.route_source === "OSRM"
                        ? "Road distance"
                        : "Approx. distance"}
                    </span>

                    <strong>
                      {station.road_distance_km} km
                    </strong>
                  </div>


                  <div>
                    <span>
                      {station.route_source === "OSRM"
                        ? "Travel time"
                        : "Travel estimate"}
                    </span>

                    <strong>
                      {
                        station.travel_time_min
                      } min
                    </strong>
                  </div>


                  <div>
                    <span>
                      Wait
                    </span>

                    <strong>
                      {station.estimated_wait_min} min
                    </strong>
                  </div>


                  <div>
                    <span>
                      Queue
                    </span>

                    <strong>
                      {station.queue_length}
                    </strong>
                  </div>


                  <div>
                    <span>
                      Charge
                    </span>

                    <strong>
                      {station.charge_time_min} min
                    </strong>
                  </div>


                  <div>
                    <span>
                      Power limit
                    </span>

                    <strong>
                      Limited by {station.limited_by}: {station.delivered_kw.toFixed(1)} kW
                    </strong>
                  </div>


                  <div>
                    <span>
                      {station.dynamic_data_source === "synthetic_demo_state"
                        ? "Simulated price"
                        : "Price"}
                    </span>

                    <strong>
                      {station.cost_per_kwh > 0
                        ? `${formatInr(station.cost_per_kwh)}/kWh`
                        : "Unavailable"}
                    </strong>
                  </div>


                  <div>
                    <span>
                      Estimated session cost
                    </span>

                    <strong>
                      {station.session_cost_inr !== null
                        ? formatInr(station.session_cost_inr)
                        : "Unavailable"}
                    </strong>
                  </div>


                  <div>
                    <span>
                      Reliability
                    </span>

                    <strong>
                      {station.reliability_score === null
                        ? "N/A"
                        : `${Math.round(
                            station.reliability_score * 100
                          )}%`}
                    </strong>
                  </div>

                </div>


                <div className="reason-list">

                  {station.reasons.map(
                    (reason) => (
                      <span
                        key={reason}
                        className="reason"
                      >
                        {reason}
                      </span>
                    )
                  )}

                </div>


                {station.connector_compatibility === "unverified" && (
                  <div className="last-updated">
                    Connector not listed for this station; check it fits your
                    vehicle before you go.
                  </div>
                )}

                <div className="last-updated">
                  {station.last_updated
                    ? `Updated ${new Date(station.last_updated).toLocaleString()}`
                    : `Data source: ${station.live_source}`}
                  <br />
                  {station.route_source === "OSRM"
                    ? "Route: OSRM, verified endpoint coordinates"
                    : station.route_source === "academic_study_graph_estimate"
                      ? "Route: academic study graph estimate"
                      : "Route: approximate, unverified coordinates"}
                </div>


                <div className="reservation-box">
                  {station.holds_applied > 0 && (
                    <div className="reservation-meta">
                      {station.holds_applied} port{station.holds_applied > 1 ? "s" : ""} held by other drivers
                    </div>
                  )}
                  {station.app_queue_length > 0 && (
                    <div className="reservation-meta">
                      {station.app_queue_length} driver{station.app_queue_length > 1 ? "s" : ""} queued here
                    </div>
                  )}

                  {reservation
                    && ACTIVE_STATUSES.includes(reservation.status)
                    && reservation.station_id === station.station_id ? (
                    <div className="reservation-active">
                      <strong>
                        {reservation.status === "HELD" && (
                          <>Port held for you{secondsLeft !== null ? ` · ${formatCountdown(secondsLeft)} left` : ""}</>
                        )}
                        {reservation.status === "QUEUED" && (
                          <>In queue: position {reservation.queue_position}
                            {reservation.estimated_wait_min !== null ? `, about ${reservation.estimated_wait_min.toFixed(0)} min` : ""}</>
                        )}
                        {reservation.status === "CHARGING" && <>Charging session active</>}
                      </strong>
                      <div className="reservation-actions">
                        {reservation.status === "HELD" && (
                          <button type="button" className="secondary" onClick={arrived}>
                            I have arrived
                          </button>
                        )}
                        <button type="button" className="secondary" onClick={releaseReservation}>
                          {reservation.status === "CHARGING" ? "Finish" : "Release"}
                        </button>
                      </div>
                    </div>
                  ) : reservation && ACTIVE_STATUSES.includes(reservation.status) ? (
                    <div className="reservation-meta">
                      You already hold a reservation at another station.
                    </div>
                  ) : station.available_ports > 0 ? (
                    <button type="button" className="secondary" onClick={() => reservePort(station.station_id)}>
                      Reserve a port (held 10 min)
                    </button>
                  ) : (
                    <button type="button" className="secondary" onClick={() => joinQueue(station.station_id)}>
                      Join the queue
                    </button>
                  )}

                  {reservationNote && reservationNote.stationId === station.station_id && (
                    <div className="reservation-note">{reservationNote.text}</div>
                  )}
                </div>

                <div className="card-bottom">

                  <div className="total-time">
                    Estimated total:
                    <strong>
                      {station.total_time_min.toFixed(1)} min
                    </strong>
                  </div>


                  <a
                    className="navigate"
                    href={station.navigation_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Search this listed station in Google Maps."
                  >
                    Navigate →
                  </a>

                </div>

              </article>
              );
            }
          )}

          {compareCases.length > 0 && (
            <div className="compare">
              <h3>Same request, every algorithm</h3>
              <table>
                <thead>
                  <tr>
                    <th>Algorithm</th>
                    <th>#1</th>
                    <th>#2</th>
                    <th>#3</th>
                  </tr>
                </thead>
                <tbody>
                  {compareCases.map((item) => (
                    <tr key={item.algorithm} className={item.algorithm === algorithm ? "selected" : ""}>
                      <td>
                        <strong>{item.label}</strong>
                        <small>{item.group}</small>
                      </td>
                      {[0, 1, 2].map((index) => {
                        const rec = item.recommendations[index];
                        return (
                          <td key={index}>
                            {rec ? (
                              <>
                                {rec.name}
                                <small>{rec.total_time_min.toFixed(1)} min total</small>
                              </>
                            ) : "-"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="compare-note">
                Total = travel + wait + charge for your battery. The choice of station is what differs.
              </p>
            </div>
          )}

        </section>

      </section>

    </main>
  );
}