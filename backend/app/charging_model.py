"""Battery-aware charging model.

Python port of frontend/src/utils/chargingModel.js. The backend is now the single
source of truth: the ranking, the charge time and the session cost all come from here.
tests/test_charging_model.py runs the JS reference and checks both give the same numbers.

IMPORTANT: every number in the TABLES below is an assumption about typical vehicles,
not measured data. Replace them with real vehicle specs when you have them.
"""

from dataclasses import dataclass
from functools import lru_cache
import math

# Highest power a battery of this size can accept: (max battery kWh, C-rate, cap in kW).
POWER_TIERS = [
    (5.0, 1.0, 6.0),
    (15.0, 1.0, 15.0),
    (30.0, 1.0, 30.0),
    (60.0, 1.2, 60.0),
    (math.inf, 2.0, 150.0),
]

# On AC the vehicle's on-board charger is the limit: (max battery kWh, cap in kW).
AC_CAP_TIERS = [
    (5.0, 3.3),
    (30.0, 7.4),
    (math.inf, 11.0),
]

EFFICIENCY = 0.92  # share of grid energy that ends up in the battery
STEPS = 100        # the charge is integrated in this many SoC slices


@dataclass(frozen=True)
class ChargeEstimate:
    minutes: float
    cost_inr: float
    billed_kwh: float
    energy_kwh: float
    vehicle_limit_kw: float
    delivered_kw: float
    limited_by: str  # "battery" or "charger"


def _round(value: float, digits: int) -> float:
    """Round half up, like JavaScript Math.round (Python round() is banker's rounding)."""
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor


def charger_mode(connector_class: str, power_kw: float) -> str:
    """'AC' or 'DC'. Unknown connector class: above 22 kW is assumed DC."""
    if connector_class == "DC":
        return "DC"
    if connector_class in {"AC_TYPE2", "AC_3PIN"}:
        return "AC"
    return "DC" if power_kw > 22 else "AC"


def max_accept_kw(battery_kwh: float, mode: str) -> float:
    """Maximum power (kW) the battery/vehicle can accept. No user input needed."""
    _, c_rate, cap_kw = next(t for t in POWER_TIERS if battery_kwh <= t[0])
    limit = min(battery_kwh * c_rate, cap_kw)
    if mode == "AC":
        ac_cap = next(t for t in AC_CAP_TIERS if battery_kwh <= t[0])[1]
        limit = min(limit, ac_cap)
    return limit


def taper(soc: float, mode: str) -> float:
    """Fraction of full power allowed at this state of charge. DC slows near full."""
    if mode == "AC" or soc < 0.8:
        return 1.0
    if soc < 0.9:
        return 0.5
    return 0.2


@lru_cache(maxsize=65536)
def estimate_charge(
    power_kw: float,
    connector_class: str,
    tariff_inr_per_kwh: float,
    battery_kwh: float,
    start_soc: float = 0.1,
    end_soc: float = 0.8,
) -> ChargeEstimate:
    if not battery_kwh > 0:
        raise ValueError("battery_kwh must be greater than 0")
    if not power_kw > 0:
        raise ValueError("power_kw must be greater than 0")
    if not (0 <= start_soc < end_soc <= 1):
        raise ValueError("need 0 <= start_soc < end_soc <= 1")

    mode = charger_mode(connector_class, power_kw)
    vehicle_limit_kw = max_accept_kw(battery_kwh, mode)
    limit_kw = min(power_kw, vehicle_limit_kw)  # the real bottleneck
    limited_by = "battery" if vehicle_limit_kw < power_kw else "charger"

    soc_step = (end_soc - start_soc) / STEPS
    energy_per_step = battery_kwh * soc_step
    minutes = 0.0
    for i in range(STEPS):
        soc = start_soc + (i + 0.5) * soc_step  # middle of the slice
        delivered = limit_kw * taper(soc, mode) * EFFICIENCY
        minutes += energy_per_step / delivered * 60

    energy_kwh = battery_kwh * (end_soc - start_soc)  # stored in the battery
    billed_kwh = energy_kwh / EFFICIENCY              # what the meter counts
    return ChargeEstimate(
        minutes=_round(minutes, 1),
        cost_inr=_round(billed_kwh * tariff_inr_per_kwh, 2),
        billed_kwh=_round(billed_kwh, 2),
        energy_kwh=_round(energy_kwh, 2),
        vehicle_limit_kw=_round(vehicle_limit_kw, 2),
        delivered_kw=_round(limit_kw * EFFICIENCY, 2),
        limited_by=limited_by,
    )
