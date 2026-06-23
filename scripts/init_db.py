from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))
SCHEMA_PATH = APP_HOME / "database" / "schema.sql"
CATALOG_PATH = APP_HOME / "config" / "indicators.json"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema)
        for item in catalog["indicators"]:
            conn.execute(
                """
                INSERT INTO indicators (
                    indicator_id, name, indicator_group, panel, source, source_ref,
                    region, frequency, unit, direction, collection_method,
                    api_params_status, api_note, dashboard_role, confidence, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(indicator_id) DO UPDATE SET
                    name=excluded.name,
                    indicator_group=excluded.indicator_group,
                    panel=excluded.panel,
                    source=excluded.source,
                    source_ref=excluded.source_ref,
                    region=excluded.region,
                    frequency=excluded.frequency,
                    unit=excluded.unit,
                    direction=excluded.direction,
                    collection_method=excluded.collection_method,
                    api_params_status=excluded.api_params_status,
                    api_note=excluded.api_note,
                    dashboard_role=excluded.dashboard_role,
                    confidence=excluded.confidence,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    item["id"],
                    item["name"],
                    item["group"],
                    item["panel"],
                    item["source"],
                    item["source_ref"],
                    item["region"],
                    item["frequency"],
                    item["unit"],
                    item["direction"],
                    item["collection_method"],
                    item["api_params_status"],
                    item.get("api_note"),
                    item["dashboard_role"],
                    item["confidence"],
                ),
            )

    print(f"initialized: {DB_PATH}")


if __name__ == "__main__":
    main()

