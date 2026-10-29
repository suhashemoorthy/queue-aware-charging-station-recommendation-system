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


def typical_session_minutes(charging_speed_kw: float) -> float:
    """Typical length of one charging session (same rule the demo data uses)."""
    if charging_speed_kw <= 0:
        return 30.0
    return min(max(15 / (charging_speed_kw * 0.92) * 60, 20.0), 90.0)


def queue_wait_minutes(cars_ahead: int, ports: int, charging_speed_kw: float) -> float:
    """Wait for a newcomer with `cars_ahead` waiting: the rest of the current session
    (half a session on average) plus one session per car ahead, shared by all ports."""
    return (cars_ahead + 0.5) * typical_session_minutes(charging_speed_kw) / max(ports, 1)
