"""Synthetic birth data (Constitution VII: no real people's birth details in training data).

Time zones are fixed standard offsets per city; daylight saving and historical zone changes are
ignored. That is fine here: the chart is computed from exactly the UTC moment we define.
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from src.chart.engine import compute_chart

CITIES_CSV = Path(__file__).with_name("cities.csv")
INDIA_SHARE = 0.75
START, END = datetime(1940, 1, 1), datetime(2015, 12, 31, 23, 59)
AS_OF = date(2026, 10, 5)  # reference date for "current dasha" in the v1 dataset


def load_cities() -> list[dict]:
    with open(CITIES_CSV, encoding="utf-8") as f:
        return [{**r, "lat": float(r["lat"]), "lon": float(r["lon"]), "tz": float(r["tz"])}
                for r in csv.DictReader(f)]


def random_birth(rng: random.Random, cities: list[dict]) -> dict:
    india = [c for c in cities if c["country"] == "India"]
    other = [c for c in cities if c["country"] != "India"]
    city = rng.choice(india if rng.random() < INDIA_SHARE else other)
    span = int((END - START).total_seconds() // 60)
    dt = START + timedelta(minutes=rng.randrange(span))
    return {"datetime": dt.isoformat(timespec="minutes"), "city": city["city"], "country": city["country"],
            "lat": city["lat"], "lon": city["lon"], "tz": city["tz"]}


def chart_for_seed(seed: int, as_of: date = AS_OF) -> dict:
    """Deterministic: the same seed always gives the same birth and chart."""
    rng = random.Random(seed)
    b = random_birth(rng, load_cities())
    chart = compute_chart(datetime.fromisoformat(b["datetime"]), b["tz"], b["lat"], b["lon"], as_of)
    chart["birth"].update({"city": b["city"], "country": b["country"], "seed": seed})
    return chart
