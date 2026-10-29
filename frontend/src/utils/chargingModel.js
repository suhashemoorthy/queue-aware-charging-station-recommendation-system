// Reference implementation. The backend (backend/app/charging_model.py) is the single
// source of truth and the UI shows its numbers. This file is kept only so that
// backend/tests/test_charging_model.py can check both versions agree.
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
