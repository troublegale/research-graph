"""Streaming CSV validation and idempotent relational import."""

import csv
import logging
import math
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from research_graph.models.entities import Brand, CarModel, Listing, Location, Observation
from research_graph.schemas import CarFeatures

logger = logging.getLogger(__name__)


@dataclass
class CleanRow:
    source_id: str
    link: str
    observed_at: datetime
    price: int
    features: CarFeatures


@dataclass
class ImportReport:
    loaded: int = 0
    duplicates: int = 0
    rejected: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


def number(value: str | None) -> float | None:
    """Normalize missing markers; reject non-finite numeric data."""
    if value is None or value.strip().lower() in {"", "nan", "none", "null"}:
        return None
    normalized = value.strip().removesuffix("LTR").strip()
    normalized = re.sub(r"\s+", "", normalized).replace(",", ".")
    result = float(normalized)
    if not math.isfinite(result):
        raise ValueError("non-finite number")
    return result


def clean_row(row: dict[str, str]) -> CleanRow:
    """Convert one raw Kaggle row; essential identity/price/date cannot be missing."""
    link = row.get("link", "").strip()
    match = re.fullmatch(r"https?://(?:[a-z0-9-]+\.)*drom\.ru/[^\s]*/(\d+)\.html/?", link)
    if not match:
        raise ValueError("invalid listing link")
    price = number(row.get("price"))
    if price is None or not 0 < price <= 1_000_000_000 or not price.is_integer():
        raise ValueError("invalid price")
    year = number(row.get("year"))
    if year is not None and not year.is_integer():
        raise ValueError("invalid year")
    observed = datetime.fromisoformat(row.get("parse_date", ""))
    if observed.tzinfo is not None:
        observed = observed.astimezone(UTC).replace(tzinfo=None)
    features = CarFeatures(
        brand=row.get("brand", "").strip(),
        name=row.get("name", "").strip(),
        location=row.get("location", "").strip(),
        year=int(year) if year is not None else None,
        mileage=number(row.get("mileage")),
        body_type=row.get("bodyType", "").strip() or "unknown",
        fuel_type=row.get("fuelType", "").strip() or "unknown",
        transmission=row.get("transmission", "").strip() or "unknown",
        power=number(row.get("power")),
        engine_displacement=number(row.get("engineDisplacement")),
    )
    if features.year is not None and features.year > observed.year + 1:
        raise ValueError("year after observation")
    return CleanRow(match[1], link, observed, int(price), features)


def read_rows(path: Path, limit: int | None = None) -> Iterator[dict[str, str]]:
    """Read without loading the source file or descriptions into a DataFrame."""
    csv.field_size_limit(10_000_000)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"brand", "name", "price", "location", "link", "parse_date"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV missing required columns: " + ", ".join(sorted(required)))
        for index, row in enumerate(reader):
            if limit is not None and index >= limit:
                break
            yield {key: value or "" for key, value in row.items() if key is not None}


def load_row(session: Session, row: CleanRow) -> bool:
    """Load one observation; latest observed attributes win regardless of input order."""
    brand = session.scalar(select(Brand).where(Brand.name == row.features.brand))
    if brand is None:
        brand = Brand(name=row.features.brand)
        session.add(brand)
        session.flush()
    model = session.scalar(
        select(CarModel).where(CarModel.brand_id == brand.id, CarModel.name == row.features.name)
    )
    if model is None:
        model = CarModel(brand_id=brand.id, name=row.features.name)
        session.add(model)
        session.flush()
    location = session.scalar(select(Location).where(Location.name == row.features.location))
    if location is None:
        location = Location(name=row.features.location)
        session.add(location)
        session.flush()
    listing = session.scalar(select(Listing).where(Listing.source_id == row.source_id))
    if listing is None:
        listing = Listing(source_id=row.source_id)
        session.add(listing)
    else:
        existing = session.scalar(
            select(Observation.id).where(
                Observation.listing_id == listing.id, Observation.observed_at == row.observed_at
            )
        )
        if existing is not None:
            return False
    latest = (
        None
        if listing.id is None
        else session.scalar(
            select(Observation.observed_at)
            .where(Observation.listing_id == listing.id)
            .order_by(Observation.observed_at.desc())
            .limit(1)
        )
    )
    if latest is None or row.observed_at >= latest:
        listing.car_model_id = model.id
        listing.location_id = location.id
        listing.link = row.link
        for key, value in row.features.model_dump(exclude={"brand", "name", "location"}).items():
            setattr(listing, key, value)
    session.flush()
    session.add(Observation(listing_id=listing.id, observed_at=row.observed_at, price=row.price))
    session.flush()
    return True


def import_csv(session: Session, path: Path, limit: int | None = None) -> ImportReport:
    """Commit bounded batches; malformed rows are rejected with aggregated reasons."""
    report = ImportReport()
    for index, raw in enumerate(read_rows(path, limit), 1):
        try:
            row = clean_row(raw)
        except (ValueError, ValidationError) as exc:
            reason = "invalid features" if isinstance(exc, ValidationError) else str(exc)
            report.rejected += 1
            report.reasons[reason] += 1
            continue
        if load_row(session, row):
            report.loaded += 1
        else:
            report.duplicates += 1
        if index % 500 == 0:
            session.commit()
            logger.info("ETL progress: %s", report)
    session.commit()
    logger.info("ETL complete: %s", report)
    return report
