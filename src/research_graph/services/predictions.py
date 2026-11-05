"""Persisted model versions and predictions, independent of transport."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from research_graph.ml.artifact import Predictor
from research_graph.models.entities import ModelVersion, PriceEstimate
from research_graph.schemas import CarFeatures


def predict_and_save(
    session: Session,
    predictor: Predictor,
    cars: list[CarFeatures],
    listing_ids: list[int | None] | None = None,
) -> list[dict[str, Any]]:
    version = session.scalar(select(ModelVersion).where(ModelVersion.version == predictor.version))
    if version is None:
        version = ModelVersion(
            version=predictor.version,
            algorithm=predictor.algorithm,
            metrics_json=json.dumps(predictor.metadata.get("test", {})),
        )
        session.add(version)
        session.flush()
    prices = predictor.predict(cars)
    results = []
    for index, (car, price) in enumerate(zip(cars, prices, strict=True)):
        estimate = PriceEstimate(
            model_version_id=version.id,
            listing_id=listing_ids[index] if listing_ids else None,
            predicted_price=price,
            features_json=car.model_dump_json(),
        )
        session.add(estimate)
        session.flush()
        results.append(
            {
                "estimate_id": estimate.id,
                "features": car.model_dump(),
                "predicted_price": round(price),
                "model_version": predictor.version,
            }
        )
    session.commit()
    return results
