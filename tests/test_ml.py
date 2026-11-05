"""Reproducible sampling, model selection and non-executable artifact contracts."""

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from catboost import CatBoostRegressor

from research_graph.ml import train as training
from research_graph.ml.artifact import (
    FEATURES,
    MAX_ARCHIVE_BYTES,
    Predictor,
    archive_bytes,
    feature_frame,
)
from research_graph.ml.dataset import prepare_dataset
from research_graph.pipelines.seed import write_demo_csv
from research_graph.schemas import CarFeatures
from tests.test_api import ridge_archive


def test_sampling_latest_unique_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    write_demo_csv(source, 200)
    with source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with source.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writerow(rows[0] | {"price": "999999", "parse_date": "2023-06-02 12:00:00"})
        writer.writerow(rows[0] | {"price": "-1"})
    output = tmp_path / "sample.parquet"
    report = prepare_dataset(source, output, 200)
    assert report == {
        "raw_rows": 202,
        "rejected_rows": 1,
        "unique_listings": 200,
        "selected": 200,
        "seed": 42,
    }
    first = pd.read_parquet(output)
    assert first.loc[first.source_id == "9000000000", "price"].iloc[0] == 999999
    prepare_dataset(source, tmp_path / "again.parquet", 200)
    pd.testing.assert_frame_equal(first, pd.read_parquet(tmp_path / "again.parquet"))
    with pytest.raises(ValueError, match="at least"):
        prepare_dataset(source, output, 99)
    write_demo_csv(source, 2)
    with pytest.raises(ValueError, match="fewer"):
        prepare_dataset(source, output)


@pytest.mark.parametrize("force_ridge", [False, True])
def test_training_roundtrip_and_disjoint_splits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force_ridge: bool
) -> None:
    source = tmp_path / "source.csv"
    dataset = tmp_path / "sample.parquet"
    output = tmp_path / "model.zip"
    write_demo_csv(source, 200)
    prepare_dataset(source, dataset, 200)
    if force_ridge:
        # Force the competing algorithm's validation predictions to be poor to
        # exercise selection and serialization of both deployable model formats.
        import numpy as np

        monkeypatch.setattr(
            CatBoostRegressor, "predict", lambda self, data, **kwargs: np.ones(len(data))
        )
    report = training.train_model(dataset, output, threads=1, iterations=10)
    assert report["algorithm"] == ("ridge" if force_ridge else report["algorithm"])
    assert report["test"]["mae"] > 0
    splits = json.loads(output.with_suffix(".splits.json").read_text())
    assert not set(splits["train"]) & set(splits["test"])
    assert not set(splits["validation"]) & set(splits["test"])
    predictor = Predictor(output.read_bytes(), threads=1)
    assert predictor.predict([CarFeatures(brand="new", name="new", location="new")])[0] > 0
    frame = pd.read_parquet(dataset)
    frame.loc[1, "source_id"] = str(frame.loc[0, "source_id"])
    frame.to_parquet(dataset)
    with pytest.raises(ValueError, match="unique"):
        training.train_model(dataset, output)
    frame.loc[1, "source_id"] = "new"
    frame.loc[0, "price"] = -1
    frame.to_parquet(dataset)
    with pytest.raises(ValueError, match="targets"):
        training.train_model(dataset, output)


def test_native_catboost_roundtrip(tmp_path: Path) -> None:
    cars = [
        CarFeatures(brand="Toyota", name="Corolla", location="Москва", year=2000 + i)
        for i in range(10)
    ]
    model = CatBoostRegressor(
        iterations=2, thread_count=1, verbose=False, allow_writing_files=False
    )
    model.fit(
        feature_frame(cars), [100000 + i * 10000 for i in range(10)], cat_features=list(range(6))
    )
    archive = archive_bytes(
        {"format_version": 1, "features": FEATURES, "algorithm": "catboost"}, model
    )
    predictor = Predictor(archive, 1)
    assert len(predictor.predict(cars)) == 10


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": 2},
        {"features": []},
        {"algorithm": "pickle"},
        {"coefficients": {}},
        {"coefficients": {"x": "invalid"}},
        {"intercept": "nan"},
    ],
)
def test_reject_invalid_model_metadata(change: dict[str, Any]) -> None:
    with zipfile.ZipFile(io.BytesIO(ridge_archive())) as archive:
        metadata = json.loads(archive.read("metadata.json"))
    with pytest.raises(ValueError):
        Predictor(archive_bytes(metadata | change))


def test_reject_archive_limits_and_unknown_files() -> None:
    with pytest.raises(ValueError, match="50 MiB"):
        Predictor(b"x" * (MAX_ARCHIVE_BYTES + 1))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../model.pkl", "untrusted")
    with pytest.raises(ValueError, match="contents"):
        Predictor(buffer.getvalue())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", b"x" * (MAX_ARCHIVE_BYTES + 1))
    with pytest.raises(ValueError, match="uncompressed"):
        Predictor(buffer.getvalue())
