export interface ChargingStationInput {
  powerKw: number;
  connectorClass: "DC" | "AC_TYPE2" | "AC_3PIN" | string;
  tariffInrPerKwh: number;
}

export interface ChargeEstimate {
  minutes: number;
  cost: number;
  billedKwh: number;
  energyKwh: number;
  vehicleLimitKw: number;
  powerKw: number;
  limitedBy: "battery" | "charger";
}

export function maxAcceptKw(batteryKwh: number, mode: string): number;

export function estimateCharge(options: {
  station: ChargingStationInput;
  batteryKwh: number;
  startSoc?: number;
  endSoc?: number;
}): ChargeEstimate;
