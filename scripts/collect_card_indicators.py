from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))

BUSAN_CARD_INDICATOR_ID = "busan_bigdatawave_card_spend_busan"
NOWCAST_MERCHANT_INDICATOR_ID = "nowcast_merchant_card_sales_busan"
NOWCAST_CREDIT_INDICATOR_ID = "nowcast_credit_card_spending_busan"

BUSAN_REGION_CODE = "26"
NOWCAST_BUSAN_REGION_CODE = "21"
NATIONAL_REGION_NAME = "전국/전체"


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def latest_busan_bigdatawave_month(client: httpx.Client) -> str:
    response = client.get(
        "https://bs.webasp.kr/api/dateRangeInfo",
        params={"region": BUSAN_REGION_CODE},
        headers={"Referer": "https://bs.webasp.kr/dashboard"},
    )
    response.raise_for_status()
    payload = response.json()
    end_ym = payload["response"]["end_ym"]
    return str(end_ym)


def previous_month(base_month: str) -> str:
    year = int(base_month[:4])
    month = int(base_month[4:])
    if month == 1:
        return f"{year - 1}12"
    return f"{year}{month - 1:02d}"


def shift_month(base_month: str, offset: int) -> str:
    year = int(base_month[:4])
    month = int(base_month[4:]) + offset
    while month <= 0:
        year -= 1
        month += 12
    while month > 12:
        year += 1
        month -= 12
    return f"{year}{month:02d}"


def recent_months(base_month: str, count: int = 6) -> list[str]:
    return [shift_month(base_month, offset) for offset in range(-(count - 1), 1)]


def fetch_busan_bigdatawave_card_spend(client: httpx.Client) -> list[dict[str, Any]]:
    base_month = latest_busan_bigdatawave_month(client)
    items = []
    for month in recent_months(base_month, 6):
        response = client.get(
            "https://bs.webasp.kr/api/dashboard/eap",
            params={"region": BUSAN_REGION_CODE, "date": month},
            headers={"Referer": "https://bs.webasp.kr/dashboard"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Big-데이터웨이브 응답 오류: {payload['error']}")

        current = float(payload["card_spend"]["current"])
        prev_month_value = float(payload["card_spend"].get("prevMonth") or 0)
        prev_year_value = float(payload["card_spend"].get("prevYear") or 0)
        mom_pct = (current - prev_month_value) / prev_month_value * 100 if prev_month_value else None
        yoy_pct = (current - prev_year_value) / prev_year_value * 100 if prev_year_value else None

        note_parts = []
        if mom_pct is not None:
            note_parts.append(f"전월 대비 {mom_pct:+.2f}%")
        if yoy_pct is not None:
            note_parts.append(f"전년 동월 대비 {yoy_pct:+.2f}%")

        items.append(
            {
                "indicator_id": BUSAN_CARD_INDICATOR_ID,
                "base_period": month,
                "value": current,
                "unit": "원",
                "source_updated_at": month,
                "note": ", ".join(note_parts) if note_parts else None,
            }
        )
    return items


def epoch_ms_to_kst_date(value: int | float) -> str:
    dt_utc = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    return dt_utc.astimezone(timezone(timedelta(hours=9))).date().isoformat()


def fetch_nowcast_indicator(
    client: httpx.Client,
    indicator_id: str,
    nowcast_id: str,
    region_code: str,
    region_name: str | None = None,
) -> list[dict[str, Any]]:
    response = client.post(
        "https://data.mods.go.kr/nowcast/listIndcrDataAjax.do",
        data={
            "indcr_id": nowcast_id,
            "val1": region_code,
            "wklId": "52",
            "mode": "",
            "initId": nowcast_id,
        },
        headers={
            "Referer": f"https://data.mods.go.kr/nowcast/main.do?initId={nowcast_id}",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError(f"Nowcast {nowcast_id} 응답에 data가 없습니다.")

    items = []
    for row in rows[-6:]:
        base_date = epoch_ms_to_kst_date(row["BASE_DT"])
        value_pct = float(row["INDCR_VL"]) * 100
        items.append(
            {
                "indicator_id": indicator_id,
                "base_period": base_date,
                "value": value_pct,
                "unit": "%",
                "source_updated_at": base_date,
                "note": "52주전 대비 변동률",
                "region": region_name,
            }
        )
    return items


def upsert_observation(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    indicator = conn.execute(
        """
        SELECT source, source_ref, region, collection_method
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
            item.get("region") or indicator["region"],
            indicator["source"],
            indicator["source_ref"],
            indicator["collection_method"],
            item.get("source_updated_at"),
            item.get("note"),
        ),
    )


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}. Run scripts/init_db.py first.")

    written = 0
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client:
        items = []
        items.extend(fetch_busan_bigdatawave_card_spend(client))
        items.extend(
            fetch_nowcast_indicator(
                client,
                NOWCAST_MERCHANT_INDICATOR_ID,
                "6",
                NOWCAST_BUSAN_REGION_CODE,
            )
        )
        items.extend(
            fetch_nowcast_indicator(
                client,
                NOWCAST_MERCHANT_INDICATOR_ID,
                "6",
                "",
                NATIONAL_REGION_NAME,
            )
        )
        items.extend(
            fetch_nowcast_indicator(
                client,
                NOWCAST_CREDIT_INDICATOR_ID,
                "1",
                NOWCAST_BUSAN_REGION_CODE,
            )
        )
        items.extend(
            fetch_nowcast_indicator(
                client,
                NOWCAST_CREDIT_INDICATOR_ID,
                "1",
                "",
                NATIONAL_REGION_NAME,
            )
        )

    with connect_db() as conn:
        for item in items:
            upsert_observation(conn, item)
            written += 1
        conn.execute(
            """
            INSERT INTO import_runs (source, source_ref, status, rows_written, finished_at, message)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                "card_indicators",
                "Big-데이터웨이브/Nowcast",
                "success",
                written,
                "부산 카드소비액, Nowcast 부산/전국 변동률, 직전기간 비교값 수집 완료",
            ),
        )

    for item in items:
        print(f"{item['indicator_id']} {item['base_period']} {item['value']:.4f}{item['unit']}")


if __name__ == "__main__":
    main()
