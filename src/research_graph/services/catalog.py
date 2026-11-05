"""Catalog queries always use the latest observation of each listing."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from research_graph.models.entities import Brand, CarModel, Listing, Location, Observation


def catalog_query() -> Any:
    latest = (
        select(Observation.listing_id, func.max(Observation.observed_at).label("observed_at"))
        .group_by(Observation.listing_id)
        .subquery()
    )
    return (
        select(
            Listing,
            CarModel.name,
            Brand.name,
            Location.name,
            Observation.price,
            Observation.observed_at,
        )
        .join(CarModel, Listing.car_model_id == CarModel.id)
        .join(Brand, CarModel.brand_id == Brand.id)
        .join(Location, Listing.location_id == Location.id)
        .join(latest, latest.c.listing_id == Listing.id)
        .join(
            Observation,
            (Observation.listing_id == Listing.id)
            & (Observation.observed_at == latest.c.observed_at),
        )
    )


def listing_dict(row: Any) -> dict[str, Any]:
    listing, name, brand, location, price, observed_at = row
    return {
        "id": listing.id,
        "source_id": listing.source_id,
        "is_demo": listing.link.startswith("https://demo.drom.ru/"),
        "name": name,
        "brand": brand,
        "location": location,
        "price": price,
        "observed_at": observed_at.isoformat(),
        "year": listing.year,
        "mileage": listing.mileage,
        "body_type": listing.body_type,
        "fuel_type": listing.fuel_type,
        "transmission": listing.transmission,
        "power": listing.power,
        "engine_displacement": listing.engine_displacement,
        "link": listing.link,
    }


def get_listing(session: Session, listing_id: int) -> dict[str, Any] | None:
    row = session.execute(catalog_query().where(Listing.id == listing_id)).first()
    return listing_dict(row) if row else None
