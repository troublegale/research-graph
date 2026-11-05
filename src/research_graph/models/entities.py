"""Relational domain entities."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative metadata."""


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class CarModel(Base):
    __tablename__ = "car_models"
    __table_args__ = (UniqueConstraint("brand_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint("year IS NULL OR year BETWEEN 1900 AND 2100"),
        CheckConstraint("mileage IS NULL OR mileage >= 0"),
        CheckConstraint("power IS NULL OR power > 0"),
        CheckConstraint("engine_displacement IS NULL OR engine_displacement > 0"),
        Index("ix_listings_year_mileage", "year", "mileage"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(200), unique=True)
    car_model_id: Mapped[int] = mapped_column(ForeignKey("car_models.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    year: Mapped[int | None]
    mileage: Mapped[float | None]
    body_type: Mapped[str] = mapped_column(String(100), default="unknown")
    fuel_type: Mapped[str] = mapped_column(String(100), default="unknown")
    transmission: Mapped[str] = mapped_column(String(100), default="unknown")
    power: Mapped[float | None]
    engine_displacement: Mapped[float | None]
    link: Mapped[str] = mapped_column(String(1000), default="")


class Observation(Base):
    __tablename__ = "listing_observations"
    __table_args__ = (
        UniqueConstraint("listing_id", "observed_at"),
        CheckConstraint("price > 0"),
        Index("ix_observations_price", "price"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[int]


class SearchRequest(Base):
    __tablename__ = "search_requests"
    __table_args__ = (
        CheckConstraint("budget > 0"),
        CheckConstraint("min_year IS NULL OR min_year BETWEEN 1900 AND 2100"),
        CheckConstraint("max_mileage IS NULL OR max_mileage >= 0"),
        CheckConstraint("status IN ('open', 'closed')"),
        CheckConstraint("revision >= 1"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    budget: Mapped[int]
    min_year: Mapped[int | None]
    max_mileage: Mapped[float | None]
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    body_type: Mapped[str | None] = mapped_column(String(100))
    transmission: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    revision: Mapped[int] = mapped_column(default=1)


class Candidate(Base):
    __tablename__ = "request_candidates"
    __table_args__ = (
        UniqueConstraint("request_id", "listing_id"),
        CheckConstraint("request_revision >= 1"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("search_requests.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    request_revision: Mapped[int]


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    algorithm: Mapped[str] = mapped_column(String(40))
    metrics_json: Mapped[str]


class PriceEstimate(Base):
    __tablename__ = "price_estimates"
    __table_args__ = (CheckConstraint("predicted_price > 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"), index=True)
    predicted_price: Mapped[float]
    features_json: Mapped[str]
