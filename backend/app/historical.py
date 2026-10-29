import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_historical_data(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def estimate_arrival_rate(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row["arrivals"]) for row in rows if row.get("arrivals")]
    return sum(values) / len(values) if values else None


def estimate_service_rate(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row["service_rate"]) for row in rows if row.get("service_rate")]
    return sum(values) / len(values) if values else None


def get_peak_factor(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 1.0
    values = [float(row["peak_factor"]) for row in rows if row.get("peak_factor")]
    return sum(values) / len(values) if values else 1.0
