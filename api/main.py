from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
CATALOG_PATH = APP_HOME / "config" / "indicators.json"
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))

app = FastAPI(title="민생100일 지표 API", version="0.1.0")


def load_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "home": str(APP_HOME),
        "db_exists": DB_PATH.exists(),
        "catalog_exists": CATALOG_PATH.exists(),
    }


@app.get("/api/indicators/catalog")
def indicator_catalog() -> dict[str, Any]:
    return load_catalog()


@app.get("/api/indicators/latest")
def latest_indicators() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"items": [], "message": "DB not initialized"}

    sql = """
    SELECT o.indicator_id, i.name, i.panel, i.indicator_group, o.base_period,
           o.value, o.unit, o.region, o.source, o.source_ref, o.note, o.collected_at
    FROM observations o
    JOIN indicators i ON i.indicator_id = o.indicator_id
    JOIN (
        SELECT indicator_id, region, MAX(base_period) AS max_period
        FROM observations
        GROUP BY indicator_id, region
    ) latest
      ON latest.indicator_id = o.indicator_id
     AND latest.region = o.region
     AND latest.max_period = o.base_period
    ORDER BY i.dashboard_role, i.panel, i.name, o.region
    """
    with connect_db() as conn:
        rows = [dict(row) for row in conn.execute(sql)]
    return {"items": rows}


@app.get("/api/manual/credit-guarantee/latest")
def latest_credit_guarantee() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"item": None, "message": "DB not initialized"}

    sql = """
    SELECT *
    FROM manual_credit_guarantee_monthly
    ORDER BY base_month DESC
    LIMIT 1
    """
    with connect_db() as conn:
        row = conn.execute(sql).fetchone()
    return {"item": dict(row) if row else None}


@app.get("/api/manual/policy-fund/latest")
def latest_policy_fund() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"item": None, "message": "DB not initialized"}

    sql = """
    SELECT *
    FROM manual_policy_fund_monthly
    ORDER BY base_month DESC
    LIMIT 1
    """
    with connect_db() as conn:
        row = conn.execute(sql).fetchone()
    return {"item": dict(row) if row else None}
