"""Relational, ETL and business-rule tests using real reversible migrations."""

import csv
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from research_graph.models.entities import Listing, Observation
from research_graph.pipelines.importer import clean_row, import_csv, load_row, number, read_rows
from research_graph.pipelines.seed import write_demo_csv
from research_graph.schemas import RequestCreate
from research_graph.services import requests as service
from research_graph.services.catalog import get_listing
from tests.db_fixtures import migration_config


@pytest.fixture
def raw() -> dict[str, str]:
    return {
        "brand": "Toyota",
        "name": "Corolla",
        "location": "Москва",
        "year": "2015.0",
        "mileage": "100000",
        "price": "1000000",
        "power": "120",
        "engineDisplacement": "1.6 LTR",
        "link": "https://moscow.drom.ru/toyota/corolla/123.html",
        "parse_date": "2023-06-01 12:00:00",
    }


def test_migrations_roundtrip(engine: Engine) -> None:
    assert len(inspect(engine).get_table_names()) == 10
    config = migration_config(str(engine.url))
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("nan", None),
        ("", None),
        ("1,6 LTR", 1.6),
        ("120", 120),
        ("1 000 000", 1000000),
        ("1\u00a0000", 1000),
    ],
)
def test_numeric_cleanup(value: str | None, expected: float | None) -> None:
    assert number(value) == expected


@pytest.mark.parametrize(
    "change",
    [
        {"link": "https://evil.test/123"},
        {"link": "https://evildrom.ru/toyota/corolla/123.html"},
        {"price": ""},
        {"price": "0"},
        {"price": "1.5"},
        {"price": "2147483648"},
        {"year": "2010.1"},
        {"year": "2040"},
        {"power": "-1"},
        {"mileage": "-10"},
        {"brand": ""},
        {"price": "inf"},
        {"parse_date": "invalid"},
    ],
)
def test_reject_bad_rows(raw: dict[str, str], change: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        clean_row(raw | change)


def test_observation_identity_and_out_of_order(db: Session, raw: dict[str, str]) -> None:
    first = clean_row(raw)
    assert load_row(db, first)
    assert not load_row(db, first)
    assert load_row(
        db,
        clean_row(
            raw
            | {"price": "1100000", "mileage": "110000", "parse_date": "2023-06-02T15:00:00+03:00"}
        ),
    )
    assert load_row(
        db,
        clean_row(
            raw | {"price": "900000", "mileage": "90000", "parse_date": "2023-05-01 12:00:00"}
        ),
    )
    db.commit()
    listing = db.scalar(select(Listing).where(Listing.source_id == "123"))
    assert listing is not None
    assert listing.mileage == 110000
    assert get_listing(db, listing.id)["price"] == 1100000  # type: ignore[index]
    assert get_listing(db, 999999) is None
    assert clean_row(raw | {"year": "", "mileage": ""}).features.year is None


def test_import_report_and_idempotence(db: Session, tmp_path: Path) -> None:
    path = tmp_path / "more.csv"
    write_demo_csv(path, 510)
    report = import_csv(db, path)
    assert report.loaded == 360
    assert report.duplicates == 150
    assert import_csv(db, path, 1).duplicates == 1
    assert db.scalar(select(func.count()).select_from(Observation)) == 510
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerow(["invalid"] * 13)
    report = import_csv(db, path)
    assert report.rejected == 1
    assert report.reasons
    path.write_text("wrong,header\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="required"):
        list(read_rows(path))


def test_database_constraints(db: Session) -> None:
    first = db.scalar(select(Observation))
    assert first is not None
    db.add(Observation(listing_id=first.listing_id, observed_at=first.observed_at, price=1))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(Observation(listing_id=999999, observed_at=first.observed_at, price=1))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_request_workflow(db: Session) -> None:
    data = RequestCreate(title="Город", budget=2_000_000)
    request = service.save_request(db, data)
    matches = service.matches(db, request.id)
    candidate = service.add_candidate(db, request.id, matches[0]["id"])
    with pytest.raises(service.DomainError, match="уже"):
        service.add_candidate(db, request.id, matches[0]["id"])
    assert not service.candidates(db, request.id)[0]["stale"]
    service.save_request(db, data.model_copy(update={"budget": 3_000_000}), request.id)
    assert service.candidates(db, request.id)[0]["stale"]
    assert service.change_status(db, request.id, "closed").status == "closed"
    for operation in (
        lambda: service.save_request(db, data, request.id),
        lambda: service.remove_candidate(db, request.id, candidate.id),
        lambda: service.delete_request(db, request.id),
        lambda: service.change_status(db, request.id, "closed"),
    ):
        with pytest.raises(service.DomainError):
            operation()
    service.change_status(db, request.id, "open")
    service.remove_candidate(db, request.id, candidate.id)
    assert service.candidates(db, request.id) == []
    with pytest.raises(service.DomainError):
        service.remove_candidate(db, request.id, candidate.id)
    service.delete_request(db, request.id)
    with pytest.raises(service.DomainError):
        service.require_request(db, request.id)


def test_request_filters_and_missing_references(db: Session) -> None:
    car = get_listing(db, 1)
    assert car is not None
    listing = db.get(Listing, 1)
    assert listing is not None
    from research_graph.models.entities import CarModel

    model = db.get(CarModel, listing.car_model_id)
    assert model is not None
    request = service.save_request(
        db,
        RequestCreate(
            title="Все ограничения",
            budget=2_000_000,
            min_year=2005,
            max_mileage=300000,
            brand_id=model.brand_id,
            location_id=listing.location_id,
            body_type=listing.body_type,
            transmission=listing.transmission,
        ),
    )
    assert service.matches(db, request.id)
    cheap = service.save_request(db, RequestCreate(title="Малый бюджет", budget=1))
    with pytest.raises(service.DomainError, match="соответствует"):
        service.add_candidate(db, cheap.id, 1)
    with pytest.raises(service.DomainError, match="найдено"):
        service.add_candidate(db, cheap.id, 999999)
    for fields in ({"brand_id": 999999}, {"location_id": 999999}):
        with pytest.raises(service.DomainError):
            service.save_request(
                db, RequestCreate.model_validate({"title": "Ошибка", "budget": 1, **fields})
            )
