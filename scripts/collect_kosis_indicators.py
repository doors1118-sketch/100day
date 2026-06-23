from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))
KOSIS_API_KEY = os.getenv("KOSIS_API_KEY", "").strip()

KOSIS_PARAM_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
KOSIS_REGISTERED_URL = "https://kosis.kr/openapi/statisticsData.do"


@dataclass(frozen=True)
class KosisSeriesSpec:
    indicator_id: str
    mode: str
    region: str
    unit: str
    source_ref: str
    org_id: str | None = None
    tbl_id: str | None = None
    itm_id: str | None = None
    obj_l1: str | None = None
    obj_l2: str | None = None
    prd_se: str = "M"
    recent_count: int = 6


SPECS: list[KosisSeriesSpec] = [
    KosisSeriesSpec(
        indicator_id="smallbiz_bsi_actual_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="142/DT_S0001N_005",
        org_id="142",
        tbl_id="DT_S0001N_005",
        itm_id="s0",
        obj_l1="102",
    ),
    KosisSeriesSpec(
        indicator_id="smallbiz_bsi_actual_busan",
        mode="param_average",
        region="전국/전체",
        unit="지수",
        source_ref="142/DT_S0001N_005",
        org_id="142",
        tbl_id="DT_S0001N_005",
        itm_id="s0",
        obj_l1="ALL",
    ),
    KosisSeriesSpec(
        indicator_id="smallbiz_bsi_forecast_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="142/DT_S0001N_005",
        org_id="142",
        tbl_id="DT_S0001N_005",
        itm_id="s1",
        obj_l1="102",
    ),
    KosisSeriesSpec(
        indicator_id="smallbiz_bsi_forecast_busan",
        mode="param_average",
        region="전국/전체",
        unit="지수",
        source_ref="142/DT_S0001N_005",
        org_id="142",
        tbl_id="DT_S0001N_005",
        itm_id="s1",
        obj_l1="ALL",
    ),
    KosisSeriesSpec(
        indicator_id="market_bsi_actual_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="142/DT_S0001N_006",
        org_id="142",
        tbl_id="DT_S0001N_006",
        itm_id="s0",
        obj_l1="102",
    ),
    KosisSeriesSpec(
        indicator_id="market_bsi_actual_busan",
        mode="param_average",
        region="전국/전체",
        unit="지수",
        source_ref="142/DT_S0001N_006",
        org_id="142",
        tbl_id="DT_S0001N_006",
        itm_id="s0",
        obj_l1="ALL",
    ),
    KosisSeriesSpec(
        indicator_id="market_bsi_forecast_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="142/DT_S0001N_006",
        org_id="142",
        tbl_id="DT_S0001N_006",
        itm_id="s1",
        obj_l1="102",
    ),
    KosisSeriesSpec(
        indicator_id="market_bsi_forecast_busan",
        mode="param_average",
        region="전국/전체",
        unit="지수",
        source_ref="142/DT_S0001N_006",
        org_id="142",
        tbl_id="DT_S0001N_006",
        itm_id="s1",
        obj_l1="ALL",
    ),
    KosisSeriesSpec(
        indicator_id="consumer_sentiment_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="301/DT_511Y004",
        org_id="301",
        tbl_id="DT_511Y004",
        itm_id="13103134641999",
        obj_l1="13102134641CSI_CD.FME",
        obj_l2="13102134641ORGANISATION_UNIT.Z11",
    ),
    KosisSeriesSpec(
        indicator_id="consumer_sentiment_busan",
        mode="param",
        region="전국/전체",
        unit="지수",
        source_ref="301/DT_511Y002",
        org_id="301",
        tbl_id="DT_511Y002",
        itm_id="13103134688999",
        obj_l1="13102134688CSI_CD.FME",
        obj_l2="13102134688CSI_CLF_CD.99988",
    ),
    KosisSeriesSpec(
        indicator_id="employment_rate_busan",
        mode="param",
        region="부산",
        unit="%",
        source_ref="101/DT_1DA7014S",
        org_id="101",
        tbl_id="DT_1DA7014S",
        itm_id="T90",
        obj_l1="21",
        obj_l2="0",
    ),
    KosisSeriesSpec(
        indicator_id="employment_rate_busan",
        mode="param",
        region="전국/전체",
        unit="%",
        source_ref="101/DT_1DA7014S",
        org_id="101",
        tbl_id="DT_1DA7014S",
        itm_id="T90",
        obj_l1="00",
        obj_l2="0",
    ),
    KosisSeriesSpec(
        indicator_id="unemployment_rate_busan",
        mode="param",
        region="부산",
        unit="%",
        source_ref="101/DT_1DA7014S",
        org_id="101",
        tbl_id="DT_1DA7014S",
        itm_id="T80",
        obj_l1="21",
        obj_l2="0",
    ),
    KosisSeriesSpec(
        indicator_id="unemployment_rate_busan",
        mode="param",
        region="전국/전체",
        unit="%",
        source_ref="101/DT_1DA7014S",
        org_id="101",
        tbl_id="DT_1DA7014S",
        itm_id="T80",
        obj_l1="00",
        obj_l2="0",
    ),
    KosisSeriesSpec(
        indicator_id="cpi_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="101/DT_1J22003",
        org_id="101",
        tbl_id="DT_1J22003",
        itm_id="T",
        obj_l1="T12",
    ),
    KosisSeriesSpec(
        indicator_id="cpi_busan",
        mode="param",
        region="전국/전체",
        unit="지수",
        source_ref="101/DT_1J22003",
        org_id="101",
        tbl_id="DT_1J22003",
        itm_id="T",
        obj_l1="T10",
    ),
    KosisSeriesSpec(
        indicator_id="coincident_index_busan",
        mode="param",
        region="부산",
        unit="지수",
        source_ref="202/DT_111_1",
        org_id="202",
        tbl_id="DT_111_1",
        itm_id="T1_00",
        obj_l1="DATA",
    ),
    KosisSeriesSpec(
        indicator_id="coincident_index_busan",
        mode="param",
        region="전국/전체",
        unit="지수",
        source_ref="101/DT_1C8015",
        org_id="101",
        tbl_id="DT_1C8015",
        itm_id="T1",
        obj_l1="B00",
    ),
]


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_float(value: Any) -> float:
    if value is None:
        raise ValueError("KOSIS 값이 비어 있습니다.")
    return float(str(value).replace(",", "").strip())


def normalize_period(value: Any) -> str:
    return str(value).replace(".", "").replace("-", "").strip()


def kosis_get(client: httpx.Client, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("err"):
        raise RuntimeError(f"KOSIS 오류 {payload.get('err')}: {payload.get('errMsg')}")
    if not isinstance(payload, list):
        raise RuntimeError(f"KOSIS 응답 형식 오류: {str(payload)[:200]}")
    return payload


def fetch_series(client: httpx.Client, spec: KosisSeriesSpec) -> list[dict[str, Any]]:
    common = {
        "method": "getList",
        "apiKey": KOSIS_API_KEY,
        "format": "json",
        "jsonVD": "Y",
        "prdSe": spec.prd_se,
        "newEstPrdCnt": str(spec.recent_count),
    }
    if spec.mode in ["param", "param_average"]:
        rows = kosis_get(
            client,
            KOSIS_PARAM_URL,
            {
                **common,
                "orgId": spec.org_id,
                "tblId": spec.tbl_id,
                "itmId": spec.itm_id,
                "objL1": spec.obj_l1,
                "objL2": spec.obj_l2 or "",
                "objL3": "",
                "objL4": "",
                "objL5": "",
                "objL6": "",
                "objL7": "",
                "objL8": "",
            },
        )
    else:
        raise ValueError(f"지원하지 않는 KOSIS 수집 mode: {spec.mode}")

    if spec.mode == "param_average":
        period_values: dict[str, list[float]] = {}
        for row in rows:
            period_values.setdefault(normalize_period(row.get("PRD_DE")), []).append(parse_float(row.get("DT")))
        items = []
        for period in sorted(period_values)[-spec.recent_count:]:
            values = period_values[period]
            items.append(
                {
                    "indicator_id": spec.indicator_id,
                    "base_period": period,
                    "value": sum(values) / len(values),
                    "unit": spec.unit,
                    "region": spec.region,
                    "source_ref": spec.source_ref,
                    "source_updated_at": period,
                    "note": "17개 시도 단순평균",
                }
            )
        return items

    items = []
    for row in sorted(rows, key=lambda item: normalize_period(item.get("PRD_DE")))[-spec.recent_count:]:
        items.append(
            {
                "indicator_id": spec.indicator_id,
                "base_period": normalize_period(row.get("PRD_DE")),
                "value": parse_float(row.get("DT")),
                "unit": spec.unit,
                "region": spec.region,
                "source_ref": spec.source_ref,
                "source_updated_at": normalize_period(row.get("PRD_DE")),
                "note": row.get("ITM_NM") or row.get("C1_NM") or row.get("TBL_NM"),
            }
        )
    return items


def upsert_observation(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    indicator = conn.execute(
        """
        SELECT source, source_ref, collection_method
        FROM indicators
        WHERE indicator_id = ?
        """,
        (item["indicator_id"],),
    ).fetchone()
    if indicator is None:
        raise RuntimeError(f"지표 카탈로그에 없는 indicator_id: {item['indicator_id']}")

    conn.execute(
        """
        INSERT INTO observations (
            indicator_id, base_period, value, unit, region, source, source_ref,
            collection_method, source_updated_at, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(indicator_id, base_period, region) DO UPDATE SET
            value=excluded.value,
            unit=excluded.unit,
            source=excluded.source,
            source_ref=excluded.source_ref,
            collection_method=excluded.collection_method,
            source_updated_at=excluded.source_updated_at,
            note=excluded.note,
            collected_at=CURRENT_TIMESTAMP
        """,
        (
            item["indicator_id"],
            item["base_period"],
            item["value"],
            item["unit"],
            item["region"],
            indicator["source"],
            item.get("source_ref") or indicator["source_ref"],
            indicator["collection_method"],
            item.get("source_updated_at"),
            item.get("note"),
        ),
    )


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}. Run scripts/init_db.py first.")
    if not KOSIS_API_KEY:
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO import_runs (source, source_ref, status, rows_written, finished_at, message)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    "kosis_indicators",
                    "KOSIS OpenAPI",
                    "skipped",
                    0,
                    "KOSIS_API_KEY 환경변수가 없어 KOSIS 수집을 건너뜀",
                ),
            )
        raise SystemExit("KOSIS_API_KEY 환경변수가 없습니다. KOSIS OpenAPI 인증키를 설정해야 합니다.")

    written = 0
    failures = []
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client, connect_db() as conn:
        for spec in SPECS:
            try:
                for item in fetch_series(client, spec):
                    upsert_observation(conn, item)
                    written += 1
                    print(f"{item['indicator_id']} {item['region']} {item['base_period']} {item['value']:.4f}{item['unit']}")
            except Exception as exc:
                failures.append(f"{spec.indicator_id}/{spec.region}: {exc}")

        status = "partial_success" if failures else "success"
        conn.execute(
            """
            INSERT INTO import_runs (source, source_ref, status, rows_written, finished_at, message)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                "kosis_indicators",
                "KOSIS OpenAPI",
                status,
                written,
                "\n".join(failures) if failures else "KOSIS 핵심지표 수집 완료",
            ),
        )

    if failures:
        print("KOSIS 수집 일부 실패:")
        for failure in failures:
            print(f"- {failure}")
    print(f"written={written}")


if __name__ == "__main__":
    main()
