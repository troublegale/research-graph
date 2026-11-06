"""SQL aggregates over latest listing observations and persisted model evaluations."""

from typing import Any

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from research_graph.models.entities import Brand, Listing, Observation, PriceEstimate
from research_graph.services.catalog import catalog_query


def price_summary(session: Session) -> list[dict[str, Any]]:
    current = (
        catalog_query()
        .with_only_columns(
            Listing.id.label("listing_id"),
            Brand.name.label("brand"),
            Listing.year,
            Observation.price,
        )
        .subquery()
    )
    query = (
        select(
            current.c.brand,
            current.c.year,
            func.count().label("count"),
            func.avg(current.c.price).label("average_price"),
            func.min(current.c.price).label("min_price"),
            func.max(current.c.price).label("max_price"),
        )
        .group_by(current.c.brand, current.c.year)
        .order_by(current.c.brand, current.c.year)
    )
    return [dict(row) for row in session.execute(query).mappings()]


def deviation_summary(session: Session) -> list[dict[str, Any]]:
    # One latest estimate per listing prevents repeated clicks from biasing the report.
    estimates = (
        select(PriceEstimate.listing_id, func.max(PriceEstimate.id).label("estimate_id"))
        .where(PriceEstimate.listing_id.is_not(None))
        .group_by(PriceEstimate.listing_id)
        .subquery()
    )
    current = (
        catalog_query()
        .with_only_columns(Listing.id.label("listing_id"), Listing.location_id, Observation.price)
        .subquery()
    )
    from research_graph.models.entities import Location

    query = (
        select(
            Location.name.label("location"),
            func.count().label("count"),
            func.avg(
                (cast(current.c.price, Float) - PriceEstimate.predicted_price)
                / PriceEstimate.predicted_price
                * 100
            ).label("average_deviation_percent"),
        )
        .select_from(current)
        .join(Location, Location.id == current.c.location_id)
        .join(estimates, estimates.c.listing_id == current.c.listing_id)
        .join(PriceEstimate, PriceEstimate.id == estimates.c.estimate_id)
        .group_by(Location.name)
        .order_by(Location.name)
    )
    return [dict(row) for row in session.execute(query).mappings()]
