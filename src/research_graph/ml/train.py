"""Compare two algorithms on validation; report final quality on untouched test data."""

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import train_test_split
from threadpoolctl import threadpool_limits

from research_graph.ml.artifact import (
    CATEGORICAL,
    FEATURES,
    Predictor,
    archive_bytes,
    feature_frame,
    ridge_features,
)
from research_graph.schemas import CarFeatures


def quality(actual: Any, predicted: Any) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(root_mean_squared_error(actual, predicted)),
    }


def train_model(
    dataset: Path, output: Path, threads: int = 6, iterations: int = 800, seed: int = 42
) -> dict[str, Any]:
    started = time.monotonic()
    frame = pd.read_parquet(dataset)
    if len(frame) < 100 or frame["source_id"].duplicated().any():
        raise ValueError("training needs at least 100 unique listings")
    cars = [
        CarFeatures.model_validate(
            {key: value if pd.notna(value) else None for key, value in row.items()}
        )
        for row in frame[FEATURES].to_dict("records")
    ]
    prices = frame["price"].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("invalid training targets")
    indices = np.arange(len(frame))
    train_idx, other_idx = train_test_split(indices, test_size=0.4, random_state=seed)
    val_idx, test_idx = train_test_split(other_idx, test_size=0.5, random_state=seed)
    vectorizer = DictVectorizer()
    ridge = Ridge(alpha=10, solver="lsqr")
    all_dicts = [ridge_features(car) for car in cars]
    with threadpool_limits(limits=threads):
        train_matrix = vectorizer.fit_transform([all_dicts[i] for i in train_idx])
        ridge.fit(train_matrix, prices[train_idx])
        ridge_val = np.maximum(
            1, ridge.predict(vectorizer.transform([all_dicts[i] for i in val_idx]))
        )
        features = feature_frame(cars)
        catboost = CatBoostRegressor(
            iterations=iterations,
            depth=6,
            learning_rate=0.06,
            loss_function="RMSE",
            eval_metric="MAE",
            random_seed=seed,
            thread_count=threads,
            used_ram_limit="4gb",
            allow_writing_files=False,
            verbose=False,
        )
        catboost.fit(
            features.iloc[train_idx],
            prices[train_idx],
            cat_features=CATEGORICAL,
            eval_set=(features.iloc[val_idx], prices[val_idx]),
            early_stopping_rounds=80,
        )
        cat_val = np.maximum(1, catboost.predict(features.iloc[val_idx], thread_count=threads))
    validation = {
        "ridge": quality(prices[val_idx], ridge_val),
        "catboost": quality(prices[val_idx], cat_val),
    }
    winner = min(validation, key=lambda key: validation[key]["mae"])
    metadata: dict[str, Any] = {
        "format_version": 1,
        "features": FEATURES,
        "algorithm": winner,
        "validation": validation,
        "seed": seed,
        "rows": {"train": len(train_idx), "validation": len(val_idx), "test": len(test_idx)},
        "threads": threads,
        "iterations": iterations,
        "period": {"min": str(frame["observed_at"].min()), "max": str(frame["observed_at"].max())},
        "limitation": "Historical asking prices; not transaction prices or current market valuation.",
    }
    if winner == "ridge":
        metadata["coefficients"] = dict(
            zip(vectorizer.get_feature_names_out().tolist(), ridge.coef_.tolist(), strict=True)
        )
        metadata["intercept"] = float(ridge.intercept_)
    predictor = Predictor(
        archive_bytes(metadata, catboost if winner == "catboost" else None), threads
    )
    predictions = predictor.predict([cars[i] for i in test_idx])
    metadata["test"] = quality(prices[test_idx], predictions)
    metadata["baseline_test"] = quality(
        prices[test_idx], np.repeat(np.median(prices[train_idx]), len(test_idx))
    )
    segments = []
    for low, high in (
        (0, 500_000),
        (500_000, 1_500_000),
        (1_500_000, 5_000_000),
        (5_000_000, float("inf")),
    ):
        mask = (prices[test_idx] >= low) & (prices[test_idx] < high)
        if mask.any():
            segments.append(
                {
                    "from": low,
                    "to": high if np.isfinite(high) else None,
                    "count": int(mask.sum()),
                    **quality(prices[test_idx][mask], np.array(predictions)[mask]),
                }
            )
    metadata["test_segments"] = segments
    metadata["elapsed_seconds"] = round(time.monotonic() - started, 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(archive_bytes(metadata, catboost if winner == "catboost" else None))
    report = {
        key: value for key, value in metadata.items() if key not in {"coefficients", "intercept"}
    }
    output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # IDs make leakage audits and exact reproduction possible without publishing raw data.
    split = {
        name: frame.iloc[values]["source_id"].astype(str).tolist()
        for name, values in (("train", train_idx), ("validation", val_idx), ("test", test_idx))
    }
    output.with_suffix(".splits.json").write_text(json.dumps(split), encoding="utf-8")
    return report
