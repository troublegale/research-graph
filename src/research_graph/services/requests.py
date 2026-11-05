"""Transactional search-request and shortlist operations."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from research_graph.models.entities import (
    Brand,
    Candidate,
    CarModel,
    Listing,
    Location,
    Observation,
    SearchRequest,
)
from research_graph.schemas import RequestCreate
from research_graph.services.catalog import catalog_query, get_listing, listing_dict


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def require_request(session: Session, request_id: int, *, editable: bool = False) -> SearchRequest:
    item = session.scalar(
        select(SearchRequest).where(SearchRequest.id == request_id).with_for_update()
    )
    if item is None:
        raise DomainError(404, "not_found", "Заявка не найдена")
    if editable and item.status != "open":
        raise DomainError(409, "request_closed", "Сначала откройте заявку повторно")
    return item


def save_request(
    session: Session, data: RequestCreate, request_id: int | None = None
) -> SearchRequest:
    for entity, identity in ((Brand, data.brand_id), (Location, data.location_id)):
        if identity is not None and session.get(entity, identity) is None:
            raise DomainError(404, "reference_not_found", "Марка или город не найдены")
    item = (
        SearchRequest()
        if request_id is None
        else require_request(session, request_id, editable=True)
    )
    values = data.model_dump()
    if request_id is not None and any(
        getattr(item, key) != value for key, value in values.items() if key != "title"
    ):
        item.revision += 1
    for key, value in values.items():
        setattr(item, key, value)
    session.add(item)
    session.commit()
    return item


def matching_query(item: SearchRequest) -> Any:
    query = catalog_query().where(Observation.price <= item.budget)
    if item.min_year is not None:
        query = query.where(Listing.year >= item.min_year)
    if item.max_mileage is not None:
        query = query.where(Listing.mileage <= item.max_mileage)
    if item.brand_id is not None:
        query = query.where(CarModel.brand_id == item.brand_id)
    if item.location_id is not None:
        query = query.where(Listing.location_id == item.location_id)
    if item.body_type is not None:
        query = query.where(Listing.body_type == item.body_type)
    if item.transmission is not None:
        query = query.where(Listing.transmission == item.transmission)
    return query


def matches(session: Session, request_id: int, limit: int = 50) -> list[dict[str, Any]]:
    item = require_request(session, request_id)
    return [
        listing_dict(row)
        for row in session.execute(
            matching_query(item).order_by(Observation.price, Listing.id).limit(limit)
        )
    ]


def add_candidate(session: Session, request_id: int, listing_id: int) -> Candidate:
    item = require_request(session, request_id, editable=True)
    if get_listing(session, listing_id) is None:
        raise DomainError(404, "not_found", "Объявление не найдено")
    if (
        session.scalar(
            select(Candidate.id).where(
                Candidate.request_id == request_id, Candidate.listing_id == listing_id
            )
        )
        is not None
    ):
        raise DomainError(409, "duplicate_candidate", "Автомобиль уже в подборке")
    if session.execute(matching_query(item).where(Listing.id == listing_id)).first() is None:
        raise DomainError(
            409, "constraints_mismatch", "Автомобиль не соответствует требованиям заявки"
        )
    candidate = Candidate(
        request_id=request_id, listing_id=listing_id, request_revision=item.revision
    )
    session.add(candidate)
    session.commit()
    return candidate


def candidates(session: Session, request_id: int) -> list[dict[str, Any]]:
    item = require_request(session, request_id)
    rows = session.scalars(
        select(Candidate).where(Candidate.request_id == request_id).order_by(Candidate.id)
    )
    return [
        {
            "id": candidate.id,
            "stale": candidate.request_revision != item.revision,
            "listing": get_listing(session, candidate.listing_id),
        }
        for candidate in rows
    ]


def remove_candidate(session: Session, request_id: int, candidate_id: int) -> None:
    require_request(session, request_id, editable=True)
    candidate = session.scalar(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.request_id == request_id)
    )
    if candidate is None:
        raise DomainError(404, "not_found", "Кандидат не найден")
    session.delete(candidate)
    session.commit()


def change_status(session: Session, request_id: int, status: str) -> SearchRequest:
    item = require_request(session, request_id)
    if item.status == status:
        raise DomainError(409, "invalid_transition", "Заявка уже находится в этом состоянии")
    item.status = status
    session.commit()
    return item


def delete_request(session: Session, request_id: int) -> None:
    require_request(session, request_id, editable=True)
    session.execute(delete(Candidate).where(Candidate.request_id == request_id))
    session.execute(delete(SearchRequest).where(SearchRequest.id == request_id))
    session.commit()
