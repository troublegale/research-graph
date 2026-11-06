"""Simultaneous first predictions share one atomically registered model version."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from research_graph.ml.artifact import Predictor
from research_graph.models.entities import ModelVersion, PriceEstimate
from research_graph.schemas import CarFeatures
from research_graph.services.predictions import predict_and_save
from tests.test_api import ridge_archive


def assert_concurrent_first_predictions(engine: Engine) -> None:
    predictor = Predictor(ridge_archive(), 1)
    barrier = Barrier(2)

    def synchronize_inserts(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.upper().startswith("INSERT INTO MODEL_VERSIONS"):
            barrier.wait(timeout=10)

    def predict() -> int:
        with Session(engine) as session:
            result = predict_and_save(
                session, predictor, [CarFeatures(brand="Toyota", name="Corolla", location="Москва")]
            )
            return int(result[0]["estimate_id"])

    event.listen(engine, "before_cursor_execute", synchronize_inserts)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(predict) for _ in range(2)]
            identities = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_inserts)
    assert len(set(identities)) == 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ModelVersion)) == 1
        assert session.scalar(select(func.count()).select_from(PriceEstimate)) == 2


def test_concurrent_first_predictions_sqlite(engine: Engine) -> None:
    assert_concurrent_first_predictions(engine)
