"""User journeys, negative API contracts and persisted model inference."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from research_graph.api.app import create_app
from research_graph.config import Settings
from research_graph.ml.artifact import FEATURES, archive_bytes
from research_graph.schemas import CarFeatures

# Fixtures shared explicitly so every API test uses the migrated database.


def ridge_archive() -> bytes:
    return archive_bytes(
        {
            "format_version": 1,
            "features": FEATURES,
            "algorithm": "ridge",
            "coefficients": {"year": 1.0},
            "intercept": 1_000_000.0,
        }
    )


@pytest.fixture
def client(db: Session, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        database_url=str(db.get_bind().engine.url),
        model_path=tmp_path / "model.zip",
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_api_request_journey(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/reference").json()["brands"]
    data = {"title": "Первая машина", "budget": 2_000_000}
    response = client.post("/api/requests", json=data)
    assert response.status_code == 201
    identity = response.json()["id"]
    url = f"/api/requests/{identity}"
    assert client.get(url).json()["title"] == data["title"]
    assert client.get("/api/requests").json()
    matches = client.post(url + "/match").json()
    candidate = client.post(url + "/candidates", json={"listing_id": matches[0]["id"]})
    assert candidate.status_code == 201
    assert (
        client.post(url + "/candidates", json={"listing_id": matches[0]["id"]}).status_code == 409
    )
    assert client.get(url + "/candidates").json()
    assert client.put(url, json=data | {"budget": 3_000_000}).status_code == 200
    assert client.get(url + "/candidates").json()[0]["stale"]
    assert client.post(url + "/close").status_code == 200
    assert client.put(url, json=data).status_code == 409
    assert client.post(url + "/reopen").status_code == 200
    assert client.delete(url + f"/candidates/{candidate.json()['id']}").status_code == 204
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get("/not-a-route").json()["error"]["code"] == "http_error"


def test_requests_after_first_hundred_remain_accessible(client: TestClient, db: Session) -> None:
    from research_graph.models.entities import SearchRequest

    db.add_all([SearchRequest(title=f"Заявка {index}", budget=1000000) for index in range(101)])
    db.commit()
    first = client.get("/api/requests?page=1").json()
    second = client.get("/api/requests?page=2").json()
    assert len(first) == 100
    assert len(second) == 1
    assert second[0]["title"] == "Заявка 0"
    assert client.get(f"/api/requests/{second[0]['id']}").status_code == 200


@pytest.mark.parametrize("sort", ["price", "-price", "year", "-year"])
def test_catalog_filter_and_sort(client: TestClient, sort: str) -> None:
    data = client.get(
        "/api/listings",
        params={
            "sort": sort,
            "budget": 2_000_000,
            "brand_id": 1,
            "location_id": 1,
            "min_year": 2005,
            "max_mileage": 300000,
            "page_size": 3,
        },
    ).json()
    assert len(data["items"]) == 3
    assert data["total"] > 3
    assert client.get("/api/listings/1").status_code == 200
    assert client.get("/api/listings/999999").status_code == 404
    assert client.get("/api/listings?page_size=101").status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "budget": 1},
        {"title": "x", "budget": -1},
        {"title": "x", "budget": 1, "extra": True},
    ],
)
def test_request_validation(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/api/requests", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"]


@pytest.mark.parametrize(
    "parameters",
    [
        {"brand_id": 0},
        {"location_id": -1},
        {"min_year": 1800},
        {"max_mileage": -1},
        {"sort": "unsafe"},
    ],
)
def test_catalog_rejects_invalid_filters(client: TestClient, parameters: dict[str, Any]) -> None:
    assert client.get("/api/listings", params=parameters).status_code == 422


def test_model_upload_and_predictions(client: TestClient) -> None:
    car = CarFeatures(brand="Toyota", name="Corolla", location="Москва").model_dump()
    assert client.post("/predict", json=[car]).status_code == 409
    assert client.get("/api/model").status_code == 409
    assert client.post("/upload-model", files={"file": ("bad.pkl", b"bad")}).status_code == 400
    response = client.post("/upload-model", files={"file": ("model.zip", ridge_archive())})
    assert response.status_code == 200
    assert client.get("/api/model").json()["algorithm"] == "ridge"
    assert client.post("/predict", json=[car, car]).json()[0]["predicted_price"] == 1000000
    assert client.post("/predict", json=[]).status_code == 422
    assert client.post("/api/listings/1/estimate").json()["deviation_percent"] < 0
    assert client.post("/api/listings/1/estimate").status_code == 200
    assert client.get("/api/analytics/prices").json()
    assert client.get("/api/analytics/deviations").json()[0]["count"] == 1


def test_identical_upload_does_not_replace_open_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = ridge_archive()
    assert client.post("/upload-model", files={"file": ("model.zip", payload)}).status_code == 200

    def file_is_open(self: Path, target: Path) -> Path:
        raise PermissionError("source file is still selected in the browser")

    monkeypatch.setattr(Path, "replace", file_is_open)
    assert client.post("/upload-model", files={"file": ("model.zip", payload)}).status_code == 200


def test_csv_prediction(client: TestClient, tmp_path: Path) -> None:
    assert client.post("/predict-from-csv", files={"file": ("x.csv", b"x")}).status_code == 409
    client.post("/upload-model", files={"file": ("model.zip", ridge_archive())})
    data = "brand,name,location,price\nToyota,Corolla,Moscow,900000\n"
    response = client.post("/predict-from-csv", files={"file": ("x.csv", data.encode())})
    assert response.status_code == 200
    assert response.json()["metrics"]["mae"] == 100000
    assert (
        client.post(
            "/predict-from-csv",
            files={"file": ("x.csv", b"brand,name,location\nToyota,Corolla,Moscow\n")},
        ).json()["metrics"]
        is None
    )
    from research_graph.pipelines.seed import write_demo_csv

    path = tmp_path / "raw.csv"
    write_demo_csv(path, 2)
    assert (
        len(
            client.post("/predict-from-csv", files={"file": ("x.csv", path.read_bytes())}).json()[
                "rows"
            ]
        )
        == 2
    )
    for content in (
        b"",
        b"brand,name,location\n",
        b"wrong\nvalue\n",
        data.replace("900000", "nan").encode(),
        b"\xff",
        b"x" * (5 * 1024 * 1024 + 1),
    ):
        assert (
            client.post("/predict-from-csv", files={"file": ("x.csv", content)}).status_code == 422
        )


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("price", ["1 000 000", "1\u00a0000\u00a0000", "1 000 000,00"])
def test_csv_metrics_use_normalized_price(client: TestClient, raw: bool, price: str) -> None:
    import csv
    import io

    client.post("/upload-model", files={"file": ("model.zip", ridge_archive())})
    row = {"brand": "Toyota", "name": "Corolla", "location": "Москва", "price": price}
    if raw:
        row.update(
            {
                "bodyType": "Седан",
                "link": "https://moscow.drom.ru/toyota/corolla/123.html",
                "parse_date": "2023-06-01 12:00:00",
            }
        )
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    response = client.post(
        "/predict-from-csv", files={"file": ("cars.csv", stream.getvalue().encode("utf-8"))}
    )
    assert response.status_code == 200
    assert response.json()["metrics"]["mae"] == 0


def test_startup_model_and_disabled_upload(db: Session, tmp_path: Path) -> None:
    path = tmp_path / "model.zip"
    path.write_bytes(ridge_archive())
    settings = Settings(
        _env_file=None,
        database_url=str(db.get_bind().engine.url),
        model_path=path,
        enable_model_upload=False,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/model").status_code == 200
        assert (
            client.post("/upload-model", files={"file": ("model.zip", ridge_archive())}).status_code
            == 403
        )


def test_integrity_error_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import IntegrityError

    def conflict(self: Session) -> None:
        raise IntegrityError("constraint", {}, ValueError("duplicate"))

    monkeypatch.setattr(Session, "commit", conflict)
    response = client.post("/api/requests", json={"title": "Конфликт", "budget": 1000000})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "integrity_conflict"


def test_unexpected_error_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: Session, *args: object, **kwargs: object) -> None:
        raise RuntimeError("private internal details")

    monkeypatch.setattr(Session, "execute", fail)
    with TestClient(client.app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/api/health")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private" not in response.text
