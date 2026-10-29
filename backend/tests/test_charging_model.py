import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.charging_model import estimate_charge, max_accept_kw

JS_MODEL = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "chargingModel.js"


def test_small_battery_is_limited_by_battery_not_charger():
    result = estimate_charge(25, "DC", 17.5, 3.7)  # 3.7 kWh on a 25 kW DC charger
    assert result.limited_by == "battery"
    assert result.delivered_kw == 3.4
    assert result.minutes == 45.7  # not the 6.2 min a nameplate-kW formula gives
    assert result.cost_inr == 49.27


def test_large_battery_on_slow_ac_is_limited_by_charger():
    result = estimate_charge(7.4, "AC_TYPE2", 13, 30)
    assert result.limited_by == "charger"
    assert result.minutes == 185.1


def test_max_accept_power_is_derived_from_battery_size():
    assert max_accept_kw(3.7, "DC") == 3.7      # 1C, under the 6 kW band cap
    assert max_accept_kw(3.7, "AC") == 3.3      # on-board charger limit
    assert max_accept_kw(4.9, "DC") == 4.9
    assert max_accept_kw(30, "DC") == 30
    assert max_accept_kw(60, "DC") == 60        # 1.2C = 72 kW, capped at 60
    assert max_accept_kw(100, "AC") == 11


@pytest.mark.parametrize(
    "kwargs",
    [
        {"battery_kwh": 0},
        {"power_kw": 0},
        {"start_soc": 0.8, "end_soc": 0.2},
        {"end_soc": 1.5},
    ],
)
def test_invalid_inputs_are_rejected(kwargs):
    base = dict(power_kw=25, connector_class="DC", tariff_inr_per_kwh=15, battery_kwh=40)
    with pytest.raises(ValueError):
        estimate_charge(**{**base, **kwargs})


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_model_matches_javascript_reference():
    """Guards against the two implementations drifting apart."""
    cases = [
        (power, cls, tariff, battery, start, end)
        for power, cls in [(3.3, "AC_3PIN"), (7.4, "AC_TYPE2"), (22, "AC_TYPE2"),
                           (25, "DC"), (50, "DC"), (60, "DC"), (30, "UNKNOWN"), (7, "UNKNOWN")]
        for tariff in (13.0, 22.5)
        for battery in (2.5, 3.7, 12, 30, 40, 75)
        for start, end in [(0.1, 0.8), (0.27, 0.8), (0.0, 1.0), (0.6, 0.95)]
    ]
    script = (
        "import {estimateCharge} from %s;"
        "const cases = %s;"
        "console.log(JSON.stringify(cases.map(([p,c,t,b,s,e]) => estimateCharge("
        "{station:{powerKw:p,connectorClass:c,tariffInrPerKwh:t},batteryKwh:b,startSoc:s,endSoc:e}))));"
    ) % (json.dumps(JS_MODEL.as_uri()), json.dumps(cases))
    output = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, check=True,
    ).stdout
    js_results = json.loads(output)
    for case, js in zip(cases, js_results):
        py = estimate_charge(*case)
        assert py.minutes == pytest.approx(js["minutes"], abs=0.051), case
        assert py.cost_inr == pytest.approx(js["cost"], abs=0.011), case
        assert py.delivered_kw == pytest.approx(js["powerKw"], abs=0.011), case
        assert py.vehicle_limit_kw == pytest.approx(js["vehicleLimitKw"], abs=0.011), case
        assert py.limited_by == js["limitedBy"], case
