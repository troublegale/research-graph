"""Non-executable model archives: JSON Ridge coefficients or native CatBoost."""

import hashlib
import io
import json
import math
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
from catboost import CatBoostRegressor

from research_graph.schemas import CarFeatures

CATEGORICAL = ["brand", "name", "location", "body_type", "fuel_type", "transmission"]
NUMERIC = ["year", "mileage", "power", "engine_displacement"]
FEATURES = CATEGORICAL + NUMERIC
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024


def feature_frame(cars: list[CarFeatures]) -> pd.DataFrame:
    frame = pd.DataFrame([car.model_dump() for car in cars], columns=FEATURES)
    for column in CATEGORICAL:
        frame[column] = frame[column].fillna("unknown").astype(str)
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(-1).astype(float)
    return frame


def ridge_features(car: CarFeatures) -> dict[str, float]:
    """Fixed, label-independent transforms; numeric scales avoid categorical domination."""
    raw = car.model_dump()
    result = {f"{key}={raw[key]}": 1.0 for key in CATEGORICAL}
    for key, scale in (
        ("year", 100),
        ("mileage", 100_000),
        ("power", 100),
        ("engine_displacement", 2),
    ):
        value = raw[key]
        result[key] = (
            (float(value) - 2000 if key == "year" else float(value)) / scale
            if value is not None
            else 0.0
        )
        result[f"{key}_missing"] = float(value is None)
    return result


def archive_bytes(metadata: dict[str, Any], model: CatBoostRegressor | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, allow_nan=False))
        if model is not None:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "model.cbm"
                model.save_model(str(path))
                archive.writestr("model.cbm", path.read_bytes())
    return buffer.getvalue()


class Predictor:
    """A loaded artifact; callers replace the instance atomically on upload."""

    def __init__(self, data: bytes, threads: int = 6) -> None:
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("model archive exceeds 50 MiB")
        self.threads = threads
        self.version = hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) not in (
                {"metadata.json"},
                {"metadata.json", "model.cbm"},
            ):
                raise ValueError("unexpected model archive contents")
            if sum(entry.file_size for entry in archive.infolist()) > MAX_ARCHIVE_BYTES:
                raise ValueError("uncompressed model exceeds 50 MiB")
            self.metadata: dict[str, Any] = json.loads(archive.read("metadata.json"))
            if (
                self.metadata.get("format_version") != 1
                or self.metadata.get("features") != FEATURES
            ):
                raise ValueError("unsupported model schema")
            self.algorithm = self.metadata.get("algorithm")
            self.model: CatBoostRegressor | None = None
            if self.algorithm == "catboost":
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "model.cbm"
                    path.write_bytes(archive.read("model.cbm"))
                    self.model = CatBoostRegressor()
                    self.model.load_model(str(path))
                if self.model.feature_names_ != FEATURES:
                    raise ValueError("incompatible CatBoost features")
            elif self.algorithm == "ridge":
                coefficients = self.metadata.get("coefficients")
                if (
                    not isinstance(coefficients, dict)
                    or not coefficients
                    or not all(
                        isinstance(value, (float, int)) and math.isfinite(value)
                        for value in coefficients.values()
                    )
                ):
                    raise ValueError("invalid Ridge coefficients")
                if not math.isfinite(float(self.metadata["intercept"])):
                    raise ValueError("invalid Ridge intercept")
            else:
                raise ValueError("unsupported algorithm")
        self.predict([CarFeatures(brand="validation", name="validation", location="validation")])

    def predict(self, cars: list[CarFeatures]) -> list[float]:
        if self.model is not None:
            values = self.model.predict(feature_frame(cars), thread_count=self.threads).tolist()
        else:
            coefficients = self.metadata["coefficients"]
            values = [
                float(self.metadata["intercept"])
                + sum(
                    coefficients.get(key, 0) * value for key, value in ridge_features(car).items()
                )
                for car in cars
            ]
        result = [max(1.0, float(value)) for value in values]
        if not all(math.isfinite(value) for value in result):
            raise ValueError("non-finite predictions")
        return result
