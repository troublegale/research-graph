"""Clearly synthetic data for offline demonstrations, never reported as real training."""

import csv
from pathlib import Path


def write_demo_csv(path: Path, size: int = 150) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "brand",
        "name",
        "location",
        "year",
        "mileage",
        "price",
        "bodyType",
        "fuelType",
        "transmission",
        "power",
        "engineDisplacement",
        "link",
        "parse_date",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index in range(size):
            brand, name = [("Лада", "Гранта"), ("Toyota", "Corolla"), ("Volkswagen", "Polo")][
                index % 3
            ]
            writer.writerow(
                {
                    "brand": brand,
                    "name": name,
                    "location": ["Москва", "Санкт-Петербург", "Казань"][index % 3],
                    "year": 2005 + index % 18,
                    "mileage": 10_000 + (index * 1703) % 250_000,
                    "price": 250_000 + (index % 18) * 65_000 + (index % 3) * 90_000,
                    "bodyType": "Седан",
                    "fuelType": "Бензин",
                    "transmission": "АКПП" if index % 2 else "Механика",
                    "power": 90 + index % 80,
                    "engineDisplacement": "1.6 LTR",
                    "link": f"https://demo.drom.ru/demo/car/{9_000_000_000 + index}.html",
                    "parse_date": "2023-06-01 12:00:00",
                }
            )
