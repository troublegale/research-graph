"""Disk-backed deduplication and deterministic sampling of the full source CSV."""

import hashlib
import json
import logging
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pandas as pd

from research_graph.pipelines.importer import clean_row, read_rows

logger = logging.getLogger(__name__)


def prepare_dataset(
    source: Path, output: Path, size: int = 50_000, seed: int = 42
) -> dict[str, int]:
    """Keep latest unique listings on disk; select a reproducible uniform hash sample."""
    if size < 100:
        raise ValueError("sample size must be at least 100")
    total = rejected = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="car-sample-") as temporary,
        closing(sqlite3.connect(Path(temporary) / "staging.db")) as connection,
    ):
        connection.execute(
            "CREATE TABLE sample (id TEXT PRIMARY KEY, observed TEXT, priority TEXT, payload TEXT)"
        )
        for raw in read_rows(source):
            total += 1
            try:
                row = clean_row(raw)
            except ValueError:
                rejected += 1
                continue
            payload = row.features.model_dump() | {
                "source_id": row.source_id,
                "price": row.price,
                "observed_at": row.observed_at.isoformat(),
                "link": row.link,
            }
            priority = hashlib.sha256(f"{seed}:{row.source_id}".encode()).hexdigest()
            connection.execute(
                "INSERT INTO sample VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET observed=excluded.observed, payload=excluded.payload WHERE excluded.observed > sample.observed",
                (
                    row.source_id,
                    row.observed_at.isoformat(),
                    priority,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            if total % 50_000 == 0:
                connection.commit()
                logger.info("Prepared %d raw rows; rejected %d", total, rejected)
        connection.commit()
        unique = int(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0])
        selected = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload FROM sample ORDER BY priority LIMIT ?", (size,)
            )
        ]
    if len(selected) < 100:
        raise ValueError("fewer than 100 valid unique listings")
    pd.DataFrame(selected).to_parquet(output, index=False)
    report = {
        "raw_rows": total,
        "rejected_rows": rejected,
        "unique_listings": unique,
        "selected": len(selected),
        "seed": seed,
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
