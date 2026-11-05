"""FastAPI application factory: explicit database/model lifecycle and thin routes."""

import csv
import io
import logging
import math
import threading
import zipfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from catboost import CatBoostError
from fastapi import Body, Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from research_graph.config import Settings, get_settings
from research_graph.ml.artifact import MAX_ARCHIVE_BYTES, Predictor
from research_graph.models.entities import (
    Brand,
    CarModel,
    Listing,
    Location,
    Observation,
    SearchRequest,
)
from research_graph.pipelines.importer import clean_row
from research_graph.schemas import (
    CandidateCreate,
    CarFeatures,
    RequestCreate,
    RequestRead,
    RequestUpdate,
)
from research_graph.services import analytics
from research_graph.services import requests as service
from research_graph.services.catalog import catalog_query, get_listing, listing_dict
from research_graph.services.predictions import predict_and_save
from research_graph.storage.database import make_engine, session_factory

logger = logging.getLogger(__name__)
MAX_CSV_BYTES = 5 * 1024 * 1024


def db_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


Database = Annotated[Session, Depends(db_session)]


def require_predictor(request: Request) -> Predictor:
    predictor: Predictor | None = request.app.state.predictor
    if predictor is None:
        raise service.DomainError(409, "model_not_loaded", "Модель не загружена")
    return predictor


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        app.state.predictor = (
            Predictor(settings.model_path.read_bytes(), settings.ml_threads)
            if settings.model_path.is_file()
            else None
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="Автоподбор",
        version="0.2.0",
        description="Подбор по требованиям и оценка исторической цены объявлений. Цены сделок и доступность автомобилей не подтверждаются.",
        lifespan=lifespan,
    )
    app.state.sessions = session_factory(engine)
    app.state.predictor = None
    app.state.upload_lock = threading.Lock()

    @app.exception_handler(service.DomainError)
    async def domain_error(_: Request, exc: service.DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": str(exc)}}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(map(str, error["loc"])), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Проверьте поля запроса",
                    "details": details,
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.info("Database constraint conflict: %s", type(exc).__name__)
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "integrity_conflict",
                    "message": "Операция конфликтует с существующими данными",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unexpected application error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Внутренняя ошибка сервиса"}},
        )

    from starlette.exceptions import HTTPException

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
            headers=exc.headers,
        )

    @app.get("/api/health", tags=["Система"])
    def health(session: Database) -> dict[str, str]:
        session.execute(select(Brand.id).limit(1))
        return {"status": "ok"}

    @app.get("/api/reference", tags=["Каталог"])
    def reference(session: Database) -> dict[str, Any]:
        return {
            "brands": [
                {"id": item.id, "name": item.name}
                for item in session.scalars(select(Brand).order_by(Brand.name))
            ],
            "locations": [
                {"id": item.id, "name": item.name}
                for item in session.scalars(select(Location).order_by(Location.name))
            ],
            "body_types": list(
                session.scalars(select(Listing.body_type).distinct().order_by(Listing.body_type))
            ),
            "transmissions": list(
                session.scalars(
                    select(Listing.transmission).distinct().order_by(Listing.transmission)
                )
            ),
        }

    @app.get("/api/listings", tags=["Каталог"])
    def listings(
        session: Database,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        budget: Annotated[int | None, Query(gt=0)] = None,
        brand_id: Annotated[int | None, Query(gt=0)] = None,
        location_id: Annotated[int | None, Query(gt=0)] = None,
        min_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
        max_mileage: Annotated[float | None, Query(ge=0, le=10_000_000)] = None,
        sort: Literal["price", "-price", "year", "-year"] = "price",
    ) -> dict[str, Any]:
        query = catalog_query()
        for condition in (
            Observation.price <= budget if budget is not None else None,
            CarModel.brand_id == brand_id if brand_id is not None else None,
            Listing.location_id == location_id if location_id is not None else None,
            Listing.year >= min_year if min_year is not None else None,
            Listing.mileage <= max_mileage if max_mileage is not None else None,
        ):
            if condition is not None:
                query = query.where(condition)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        order = {
            "price": Observation.price.asc(),
            "-price": Observation.price.desc(),
            "year": Listing.year.asc(),
            "-year": Listing.year.desc(),
        }[sort]
        rows = session.execute(
            query.order_by(order, Listing.id).offset((page - 1) * page_size).limit(page_size)
        )
        return {
            "items": [listing_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @app.get("/api/listings/{listing_id}", tags=["Каталог"])
    def listing(session: Database, listing_id: int) -> dict[str, Any]:
        item = get_listing(session, listing_id)
        if item is None:
            raise service.DomainError(404, "not_found", "Объявление не найдено")
        return item

    @app.get("/api/requests", response_model=list[RequestRead], tags=["Заявки"])
    def requests_list(session: Database, page: Annotated[int, Query(ge=1)] = 1) -> Any:
        return session.scalars(
            select(SearchRequest)
            .order_by(SearchRequest.id.desc())
            .offset((page - 1) * 100)
            .limit(100)
        ).all()

    @app.post("/api/requests", response_model=RequestRead, status_code=201, tags=["Заявки"])
    def create_request(session: Database, data: RequestCreate) -> Any:
        return service.save_request(session, data)

    @app.get("/api/requests/{request_id}", response_model=RequestRead, tags=["Заявки"])
    def read_request(session: Database, request_id: int) -> Any:
        return service.require_request(session, request_id)

    @app.put("/api/requests/{request_id}", response_model=RequestRead, tags=["Заявки"])
    def update_request(session: Database, request_id: int, data: RequestUpdate) -> Any:
        return service.save_request(session, data, request_id)

    @app.delete("/api/requests/{request_id}", status_code=204, tags=["Заявки"])
    def delete_request(session: Database, request_id: int) -> Response:
        service.delete_request(session, request_id)
        return Response(status_code=204)

    @app.post("/api/requests/{request_id}/close", response_model=RequestRead, tags=["Заявки"])
    def close_request(session: Database, request_id: int) -> Any:
        return service.change_status(session, request_id, "closed")

    @app.post("/api/requests/{request_id}/reopen", response_model=RequestRead, tags=["Заявки"])
    def reopen_request(session: Database, request_id: int) -> Any:
        return service.change_status(session, request_id, "open")

    @app.post("/api/requests/{request_id}/match", tags=["Подбор"])
    def match(
        session: Database, request_id: int, limit: Annotated[int, Query(ge=1, le=100)] = 50
    ) -> Any:
        return service.matches(session, request_id, limit)

    @app.get("/api/requests/{request_id}/candidates", tags=["Подбор"])
    def candidate_list(session: Database, request_id: int) -> Any:
        return service.candidates(session, request_id)

    @app.post("/api/requests/{request_id}/candidates", status_code=201, tags=["Подбор"])
    def candidate_add(session: Database, request_id: int, data: CandidateCreate) -> dict[str, int]:
        item = service.add_candidate(session, request_id, data.listing_id)
        return {"id": item.id, "listing_id": item.listing_id}

    @app.delete(
        "/api/requests/{request_id}/candidates/{candidate_id}", status_code=204, tags=["Подбор"]
    )
    def candidate_remove(session: Database, request_id: int, candidate_id: int) -> Response:
        service.remove_candidate(session, request_id, candidate_id)
        return Response(status_code=204)

    @app.get("/api/analytics/prices", tags=["Аналитика"])
    def prices(session: Database) -> Any:
        return analytics.price_summary(session)

    @app.get("/api/analytics/deviations", tags=["Аналитика"])
    def deviations(session: Database) -> Any:
        return analytics.deviation_summary(session)

    @app.get("/api/model", tags=["ML"])
    def model_info(request: Request) -> dict[str, Any]:
        predictor = require_predictor(request)
        return {
            "version": predictor.version,
            **{
                key: value
                for key, value in predictor.metadata.items()
                if key not in {"coefficients", "intercept"}
            },
        }

    @app.post("/predict", tags=["ML"])
    def predict(
        request: Request,
        session: Database,
        cars: Annotated[list[CarFeatures], Body(min_length=1, max_length=1000)],
    ) -> Any:
        return predict_and_save(session, require_predictor(request), cars)

    @app.post("/api/listings/{listing_id}/estimate", tags=["ML"])
    def estimate(request: Request, session: Database, listing_id: int) -> Any:
        item = listing(session, listing_id)
        features = CarFeatures.model_validate({key: item[key] for key in CarFeatures.model_fields})
        result = predict_and_save(session, require_predictor(request), [features], [listing_id])[0]
        result["deviation_percent"] = round(
            (item["price"] - result["predicted_price"]) / result["predicted_price"] * 100, 2
        )
        return result

    @app.post("/upload-model", tags=["ML"])
    def upload_model(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, str]:
        if not settings.enable_model_upload:
            raise service.DomainError(403, "upload_disabled", "Загрузка модели отключена")
        data = file.file.read(MAX_ARCHIVE_BYTES + 1)
        try:
            predictor = Predictor(data, settings.ml_threads)
        except (
            ValueError,
            KeyError,
            TypeError,
            zipfile.BadZipFile,
            CatBoostError,
            RuntimeError,
        ) as exc:
            raise service.DomainError(
                400, "invalid_model", "Некорректный или несовместимый архив модели"
            ) from exc
        with app.state.upload_lock:
            settings.model_path.parent.mkdir(parents=True, exist_ok=True)
            # Re-uploading the same file need not replace it. On Windows the
            # browser may still hold the selected source file open.
            if not settings.model_path.is_file() or settings.model_path.read_bytes() != data:
                pending = settings.model_path.with_suffix(".pending")
                pending.write_bytes(data)
                pending.replace(settings.model_path)
            request.app.state.predictor = predictor
        return {"status": "loaded", "version": predictor.version}

    @app.post("/predict-from-csv", tags=["ML"])
    def predict_csv(
        request: Request, session: Database, file: Annotated[UploadFile, File()]
    ) -> Any:
        predictor = require_predictor(request)
        data = file.file.read(MAX_CSV_BYTES + 1)
        if len(data) > MAX_CSV_BYTES:
            raise service.DomainError(422, "file_size", "CSV не должен превышать 5 MiB")
        try:
            rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
            if not 1 <= len(rows) <= 1000:
                raise ValueError("batch size")
            cars = []
            for row in rows:
                if "bodyType" in row or "parse_date" in row:
                    cars.append(clean_row({**row, "price": row.get("price") or "1"}).features)
                else:
                    values: dict[str, Any] = {
                        key: value for key, value in row.items() if key in CarFeatures.model_fields
                    }
                    for key in ("year", "mileage", "power", "engine_displacement"):
                        if not values.get(key):
                            values[key] = None
                    cars.append(CarFeatures.model_validate(values))
            targets = (
                [float(row["price"]) for row in rows]
                if all(row.get("price") for row in rows)
                else None
            )
            if targets is not None and not all(
                math.isfinite(value) and value > 0 for value in targets
            ):
                raise ValueError("invalid price")
        except (ValueError, ValidationError, csv.Error, UnicodeError) as exc:
            raise service.DomainError(
                422,
                "invalid_csv",
                "Некорректный CSV: нужны признаки автомобиля, максимум 1000 строк",
            ) from exc
        result = predict_and_save(session, predictor, cars)
        metrics = None
        if targets is not None:
            from research_graph.ml.train import quality

            metrics = quality(targets, [item["predicted_price"] for item in result])
        return {
            "rows": [{**row, **prediction} for row, prediction in zip(rows, result, strict=True)],
            "metrics": metrics,
        }

    static = Path(__file__).parent.parent / "web"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static / "index.html")

    return app
