import assert from "node:assert/strict";
import test from "node:test";

import { estimateCharge } from "./chargingModel.js";

test("small DC battery is limited by battery acceptance power", () => {
  const estimate = estimateCharge({
    station: {
      powerKw: 25,
      connectorClass: "DC",
      tariffInrPerKwh: 20,
    },
    batteryKwh: 3.7,
    startSoc: 0.1,
    endSoc: 0.8,
  });

  assert.equal(estimate.minutes, 45.7);
  assert.equal(estimate.limitedBy, "battery");
});

test("AC station is limited by charger power", () => {
  const estimate = estimateCharge({
    station: {
      powerKw: 7.4,
      connectorClass: "AC_TYPE2",
      tariffInrPerKwh: 20,
    },
    batteryKwh: 30,
    startSoc: 0.1,
    endSoc: 0.8,
  });

  assert.equal(estimate.minutes, 185.1);
  assert.equal(estimate.limitedBy, "charger");
});
