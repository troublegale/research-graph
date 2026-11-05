"""Validated API contracts, separate from ORM entities."""

from pydantic import BaseModel, ConfigDict, Field


class RequestCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "title": "Городская машина",
                    "budget": 1500000,
                    "min_year": 2012,
                    "max_mileage": 180000,
                }
            ]
        },
    )
    title: str = Field(min_length=1, max_length=200)
    budget: int = Field(gt=0, le=1_000_000_000)
    min_year: int | None = Field(default=None, ge=1900, le=2100)
    max_mileage: float | None = Field(default=None, ge=0, le=10_000_000)
    brand_id: int | None = Field(default=None, gt=0)
    location_id: int | None = Field(default=None, gt=0)
    body_type: str | None = Field(default=None, min_length=1, max_length=100)
    transmission: str | None = Field(default=None, min_length=1, max_length=100)


class RequestUpdate(RequestCreate):
    """PUT replaces the entire editable request; status has dedicated operations."""


class RequestRead(RequestCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    revision: int


class CarFeatures(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        json_schema_extra={
            "examples": [
                {
                    "brand": "Toyota",
                    "name": "Corolla",
                    "location": "Москва",
                    "year": 2015,
                    "mileage": 100000,
                    "power": 122,
                    "engine_displacement": 1.6,
                    "body_type": "Седан",
                    "fuel_type": "Бензин",
                    "transmission": "АКПП",
                }
            ]
        },
    )
    brand: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    location: str = Field(min_length=1, max_length=150)
    year: int | None = Field(default=None, ge=1900, le=2100)
    mileage: float | None = Field(default=None, ge=0, le=10_000_000)
    body_type: str = Field(default="unknown", max_length=100)
    fuel_type: str = Field(default="unknown", max_length=100)
    transmission: str = Field(default="unknown", max_length=100)
    power: float | None = Field(default=None, gt=0, le=3000)
    engine_displacement: float | None = Field(default=None, gt=0, le=20)


class CandidateCreate(BaseModel):
    listing_id: int = Field(gt=0)
