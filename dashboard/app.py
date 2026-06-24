from __future__ import annotations

import html
import hashlib
import json
import math
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
CATALOG_PATH = APP_HOME / "config" / "indicators.json"
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))
MINSAENG_START_DATE = date(2026, 7, 1)
MINSAENG_TOTAL_DAYS = 100


st.set_page_config(
    page_title="100일의 변화 시민과 함께 더 나은 부산으로",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(ttl=300)
def load_catalog() -> pd.DataFrame:
    with CATALOG_PATH.open("r", encoding="utf-8") as fp:
        catalog = json.load(fp)
    return pd.DataFrame(catalog["indicators"])


@st.cache_data(ttl=300)
def load_observations() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    sql = """
    SELECT o.indicator_id, i.name, i.panel, i.dashboard_role, i.direction,
           o.base_period, o.value, o.unit, o.region, o.source, o.source_ref,
           o.note, o.collected_at
    FROM observations o
    JOIN indicators i ON i.indicator_id = o.indicator_id
    ORDER BY o.indicator_id, o.region, o.base_period
    """
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn)


@st.cache_data(ttl=300)
def load_manual_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():
        return pd.DataFrame(), pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        credit = pd.read_sql_query(
            "SELECT * FROM manual_credit_guarantee_monthly ORDER BY base_month DESC",
            conn,
        )
        policy = pd.read_sql_query(
            "SELECT * FROM manual_policy_fund_monthly ORDER BY base_month DESC",
            conn,
        )
    return credit, policy


@st.cache_data(ttl=300)
def load_import_runs() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT source, source_ref, status, rows_written, started_at, finished_at, message
            FROM import_runs
            ORDER BY import_run_id DESC
            LIMIT 10
            """,
            conn,
        )


@dataclass
class Card:
    title: str
    group: str
    value: str
    period: str
    source: str
    unit: str = ""
    value_detail: str | None = None
    previous_label: str = "전월 대비"
    previous_value: str | None = None
    previous_tone: str = "neutral"
    benchmark_label: str = "기준 비교"
    benchmark_value: str | None = None
    benchmark_tone: str = "neutral"
    note: str | None = None
    confidence: str | None = None
    empty: bool = False
    bar_pct: float = 0
    bar_left: str = ""
    bar_right: str = ""
    chart_points: list[tuple[str, float]] = field(default_factory=list)
    chart_points_alt: list[tuple[str, float]] = field(default_factory=list)
    chart_alt_label: str = ""
    description: str = ""


@dataclass(frozen=True)
class EmergencyProject:
    project_id: str
    number: int
    title: str
    field: str
    department: str
    budget: str
    feature: str
    milestone: str
    status: str = "착수 전"
    progress_pct: int = 0
    latest_update: str = "부서 일일 입력 대기"
    issue: str = "입력 전"


EMERGENCY_PROJECTS: list[EmergencyProject] = [
    EmergencyProject(
        "P001",
        1,
        "영세 화물차주·택배 종사자 특별 지원",
        "비용 절감",
        "트라이포트기획과·일자리노동과",
        "578.3억원",
        "유가연동보조금, 화물자동차 보험료, 배달종사자 산재보험료 지원",
        "2026.7. 세부계획 수립, 2026.9. 추경 확보 후 지원",
    ),
    EmergencyProject(
        "P002",
        2,
        "소상공인 에너지 바우처 지급",
        "비용 절감",
        "중소상공인지원과",
        "840억원",
        "연매출 10억원 이하 소상공인 대상 업체당 30만원 바우처",
        "2026.9. 추경 확보, 2026.10. 이후 지급",
    ),
    EmergencyProject(
        "P003",
        3,
        "공공요금 동결·지방세 부담 완화",
        "비용 절감",
        "경제정책과·세정운영담당관",
        "비예산",
        "시 관리 공공요금 동결과 지방세 기한연장·징수유예 등 세정지원",
        "2026.7. 지방세 세정지원 제도 홍보",
    ),
    EmergencyProject(
        "P004",
        4,
        "카드수수료 부담 제로화·공공배달 활성화",
        "구조 개선",
        "중소상공인지원과",
        "174.5억원",
        "동백전 QR 확대, 카드수수료 감면, 공공배달·QR 소비활력 쿠폰",
        "2026.9. 추경 확보 후 QR 확대와 쿠폰 지원",
    ),
    EmergencyProject(
        "P005",
        5,
        "소상공인 특별 민생금융 지원",
        "금융 지원",
        "경제정책과·부산신용보증재단",
        "1조 2,000억원",
        "부산 소재 소상공인 대상 보증·전환보증·담보대출 등 정책금융",
        "2026.9. MOU 체결, 자금지원 공고 및 접수",
    ),
    EmergencyProject(
        "P006",
        6,
        "동백전 캐시백 15% 한시 상향",
        "수요 회복",
        "경제정책과",
        "600억원",
        "동백전 캐시백률 최대 15% 한시 상향 및 특화 캐시백 운영",
        "2026.9. 캐시백 정책 발표, 2026.9.~12. 적용",
    ),
    EmergencyProject(
        "P007",
        7,
        "1만원 임대료 빈 점포 활용 민생상권 회복",
        "상권 활성화",
        "중소상공인지원과",
        "4억원",
        "빈 점포 임차·인테리어·운영비 지원을 통한 생활상권 회복",
        "세부 추진계획 보완 필요",
    ),
    EmergencyProject(
        "P008",
        8,
        "공공근로형 민생지킴이 운영·공공일자리 확대",
        "안전망",
        "일자리노동과·노인복지과·장애인복지과",
        "120.7억원",
        "민생지킴이 500명과 노인·신중년·장애인 공공일자리 확대",
        "2026.9. 사업비 교부 및 참여자 선발",
    ),
    EmergencyProject(
        "P009",
        9,
        "소상공인 파산·회생 원스톱 100일 프로젝트",
        "안전망",
        "중소상공인지원과·경제정책과",
        "3억원",
        "찾아가는 상담부터 회생 신청과 연계사업 접수까지 원스톱 지원",
        "2026.8. TF 구성·MOU 체결, 2026.9.~12. 희망버스 운영",
    ),
    EmergencyProject(
        "P010",
        10,
        "민생금융범죄 특별사법경찰제도 조속 도입",
        "안전망",
        "특별사법경찰과",
        "비예산",
        "불법사금융·불법고금리·불법추심 등 민생경제 범죄 수사체계 구축",
        "2026.7. TF 신설, 2026.9. 민생경제수사팀 신설 추진",
    ),
]


def safe_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


METRIC_DESCRIPTIONS = {
    "smallbiz_bsi_actual_busan": "부산 소상공인이 현재 경기를 어떻게 체감하는지 나타내는 지수입니다. 100을 기준으로 높을수록 경기를 좋게 보는 응답이 많고, 낮을수록 어렵게 보는 응답이 많다는 의미입니다.",
    "smallbiz_bsi_forecast_busan": "부산 소상공인이 다음 기간의 경기를 어떻게 전망하는지 나타내는 지수입니다. 100을 기준으로 높을수록 향후 경기를 긍정적으로 보는 응답이 많다는 의미입니다.",
    "market_bsi_actual_busan": "부산 전통시장 상인이 현재 시장 경기를 어떻게 체감하는지 나타내는 지수입니다. 값이 높을수록 전통시장 경기 인식이 개선된 것으로 해석합니다.",
    "market_bsi_forecast_busan": "부산 전통시장 상인이 다음 기간의 시장 경기를 어떻게 전망하는지 나타내는 지수입니다. 향후 매출과 방문객 흐름에 대한 기대를 보는 보조 지표입니다.",
    "consumer_sentiment_busan": "부산 소비자가 경기, 생활형편, 소비지출 등을 종합적으로 어떻게 인식하는지 보여주는 심리지수입니다. 100보다 높으면 장기평균보다 낙관적, 낮으면 비관적인 상태로 해석합니다.",
    "busan_bigdatawave_card_spend_busan": "부산 지역 신용카드 소비액 규모를 보여주는 지표입니다. 지역 내 소비 흐름과 상권 매출 분위기를 월별로 파악하기 위한 대체 소비 지표입니다.",
    "nowcast_credit_card_spending_busan": "부산 신용카드 이용금액이 기준 기간 대비 얼마나 변했는지 나타내는 변동률 지표입니다. 카드 소비의 최근 방향성을 빠르게 확인하는 데 사용합니다.",
    "nowcast_merchant_card_sales_busan": "부산 가맹점 카드매출액이 기준 기간 대비 얼마나 변했는지 나타내는 변동률 지표입니다. 지역 상점 매출 흐름을 보는 소비·상권 보조 지표입니다.",
    "coincident_index_busan": "부산 지역의 현재 경기 흐름을 종합해 나타내는 경기종합지수입니다. 생산, 소비, 고용 등 여러 경제활동 지표를 묶어 지역경기의 현재 국면을 파악하는 데 사용합니다.",
    "employment_rate_busan": "부산의 만 15세 이상 인구 중 취업자가 차지하는 비율입니다. 지역 노동시장 참여와 일자리 상황을 보는 기본 지표입니다.",
    "unemployment_rate_busan": "부산 경제활동인구 중 실업자가 차지하는 비율입니다. 값이 높아지면 일자리를 찾지만 취업하지 못한 인구 비중이 커졌다는 의미입니다.",
    "cpi_busan": "부산 소비자가 구입하는 상품과 서비스의 가격 변화를 종합한 물가지수입니다. 생활물가 부담과 구매력 변화를 판단하는 기본 지표입니다.",
}


def metric_description(catalog_row: pd.Series) -> str:
    indicator_id = str(catalog_row.get("id", ""))
    if indicator_id in METRIC_DESCRIPTIONS:
        return METRIC_DESCRIPTIONS[indicator_id]
    name = str(catalog_row.get("name", "해당 지표"))
    return f"{name}의 변화 추이를 통해 부산 지역 경제 상황을 확인하는 지표입니다."


def is_missing(value: Any) -> bool:
    return value is None or pd.isna(value)


def minsaeng_countdown(today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    elapsed_days = (today - MINSAENG_START_DATE).days
    if elapsed_days < 0:
        remaining_days = MINSAENG_TOTAL_DAYS
        status = "시작 기준"
    elif elapsed_days >= MINSAENG_TOTAL_DAYS:
        remaining_days = 0
        status = "종료"
    else:
        remaining_days = MINSAENG_TOTAL_DAYS - elapsed_days
        status = "진행 중"
    label = "D-DAY" if remaining_days == 0 else f"D-{remaining_days}"
    return label, status


def countdown_html(label: str) -> str:
    if label == "D-DAY":
        return '<strong><span class="latin-d">D</span>-DAY</strong>'
    if label.startswith("D-"):
        return f'<strong><span class="latin-d">D</span>{safe_text(label[1:])}</strong>'
    return f"<strong>{safe_text(label)}</strong>"


def format_period(value: Any) -> str:
    if is_missing(value):
        return "기준월 없음"
    text = str(value)
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}.{text[4:]}"
    if len(text) >= 7 and text[4] in ["-", "."]:
        return f"{text[:4]}.{text[5:7]}"
    return text


def format_value(value: Any, unit: str) -> str:
    if is_missing(value):
        return "자료대기"
    number = float(value)
    if unit == "원":
        return f"{number / 100_000_000:,.1f}억원"
    if unit == "백만원":
        return f"{number / 100:,.1f}억원"
    if unit == "%":
        return f"{number:,.1f}%"
    if unit == "건":
        return f"{number:,.0f}건"
    if unit in ["지수", "변동률"]:
        return f"{number:,.1f}"
    return f"{number:,.1f}"


def format_won_compact(value: Any) -> str:
    if is_missing(value):
        return "자료대기"
    number = float(value) / 100_000_000
    if number.is_integer():
        return f"{number:,.0f}억원"
    return f"{number:,.1f}억원"


def format_metric_number(value: Any, unit: str) -> str:
    if is_missing(value):
        return "자료대기"
    number = float(value)
    if unit == "원":
        return f"{number / 100_000_000:,.1f}"
    if unit == "백만원":
        return f"{number / 100:,.1f}"
    if unit == "건":
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def format_chart_value(value: float) -> str:
    abs_value = abs(float(value))
    if abs_value >= 100_000_000:
        return f"{float(value) / 100_000_000:,.0f}"
    if abs_value >= 100:
        return f"{float(value):,.0f}"
    return f"{float(value):,.1f}"


def short_period_label(label: str) -> str:
    text = str(label)
    if "-" in text:
        parts = text.split("-")
        if len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"
        return text[-5:].replace("-", ".")
    if "." in text:
        month = text.split(".")[-1]
        if month.isdigit():
            return f"{int(month)}월"
        return text[-5:]
    if len(text) == 6 and text.isdigit():
        return f"{int(text[4:6])}월"
    return text[-5:]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def unit_label(unit: str) -> str:
    if unit == "원":
        return "억원"
    if unit == "백만원":
        return "억원"
    if unit == "변동률":
        return "%"
    return unit


KOSIS_SOURCE_NAMES = {
    "142/DT_S0001N_005": "소상공인 경기동향조사",
    "142/DT_S0001N_006": "전통시장 경기동향조사",
    "301/DT_511Y004": "지역 소비자심리지수",
    "301/DT_511Y002": "소비자심리지수",
    "101/DT_1DA7014S": "경제활동인구조사",
    "101/DT_1J22003": "소비자물가조사",
    "202/DT_111_1": "지역경기종합지수",
}


def source_label(source: Any, source_ref: Any = None) -> str:
    source_text = "" if source is None or pd.isna(source) else str(source).strip()
    ref_text = "" if source_ref is None or pd.isna(source_ref) else str(source_ref).strip()
    if source_text.upper().startswith("KOSIS"):
        source_name = KOSIS_SOURCE_NAMES.get(ref_text)
        if source_name:
            return f"국가데이터처[{source_name}]"
        return "국가데이터처"
    if "bs.webasp.kr/api/dashboard/eap" in ref_text or "Big-데이터웨이브" in source_text:
        return "부산광역시 빅데이터"
    if "통계데이터센터" in source_text:
        return "국가데이터처 통계데이터센터"
    if ref_text and ref_text not in ["manual", source_text]:
        return f"{source_text}, [{ref_text}]"
    return source_text


def bar_scale(value: Any, unit: str) -> tuple[float, str, str]:
    if is_missing(value):
        return 0, "입력 전", "자료대기"
    number = float(value)
    if unit == "%":
        return clamp(number, 0, 100), "0", "100"
    if unit == "지수":
        return clamp(number / 150 * 100, 0, 100), "0", "150"
    if unit == "변동률":
        return clamp((number + 20) / 40 * 100, 0, 100), "-20", "+20"
    return 74, "최근", "부산"


def format_delta(current: Any, previous: Any, unit: str) -> tuple[str | None, float | None]:
    if is_missing(current) or is_missing(previous):
        return None, None
    current_num = float(current)
    previous_num = float(previous)
    gap = current_num - previous_num
    if unit in ["%", "지수", "변동률"]:
        suffix = "%p" if unit in ["%", "변동률"] else "p"
        return f"{gap:+,.1f}{suffix}", gap
    if previous_num == 0:
        return None, None
    return f"{gap / previous_num * 100:+,.1f}%", gap


def format_benchmark(current: Any, benchmark: Any, unit: str) -> tuple[str | None, float | None]:
    if is_missing(current) or is_missing(benchmark):
        return None, None
    gap = float(current) - float(benchmark)
    if unit == "원":
        return f"전국 {format_value(benchmark, unit)}({gap / 100_000_000:+,.1f}억원)", gap
    if unit == "백만원":
        return f"전국 {format_value(benchmark, unit)}({gap / 100:+,.1f}억원)", gap
    suffix = "%p" if unit in ["%", "변동률"] else "P"
    return f"전국 {format_value(benchmark, unit)}({gap:+,.1f}{suffix})", gap


def tone_from_gap(gap: float | None, direction: str) -> str:
    if gap is None or abs(gap) < 0.000001:
        return "neutral"
    if direction == "lower_is_better":
        return "positive" if gap < 0 else "negative"
    if direction == "higher_is_better":
        return "positive" if gap > 0 else "negative"
    return "positive" if gap > 0 else "negative"


def latest_for_indicator(observations: pd.DataFrame, indicator_id: str) -> pd.Series | None:
    if observations.empty:
        return None
    rows = observations[observations["indicator_id"].eq(indicator_id)]
    busan_rows = rows[rows["region"].astype(str).str.contains("부산", na=False)]
    if busan_rows.empty:
        return None
    return busan_rows.sort_values("base_period").iloc[-1]


def previous_for_indicator(
    observations: pd.DataFrame,
    indicator_id: str,
    region: str,
    base_period: str,
) -> pd.Series | None:
    rows = observations[
        observations["indicator_id"].eq(indicator_id)
        & observations["region"].eq(region)
        & observations["base_period"].lt(base_period)
    ].sort_values("base_period")
    if rows.empty:
        return None
    return rows.iloc[-1]


def benchmark_for_indicator(
    observations: pd.DataFrame,
    indicator_id: str,
    base_period: str,
) -> pd.Series | None:
    rows = observations[
        observations["indicator_id"].eq(indicator_id)
        & observations["base_period"].eq(base_period)
        & observations["region"].astype(str).str.contains("전국|전체", regex=True, na=False)
    ]
    if rows.empty:
        return None
    return rows.iloc[-1]


def recent_points_for_indicator(observations: pd.DataFrame, indicator_id: str, region: str) -> list[tuple[str, float]]:
    rows = observations[
        observations["indicator_id"].eq(indicator_id)
        & observations["region"].eq(region)
    ].sort_values("base_period")
    rows = rows.tail(6)
    points: list[tuple[str, float]] = []
    for _, row in rows.iterrows():
        if not is_missing(row["value"]):
            points.append((format_period(row["base_period"]), float(row["value"])))
    return points


def recent_manual_points(rows: pd.DataFrame, value_column: str) -> list[tuple[str, float]]:
    if rows.empty:
        return []
    valid_rows = rows[rows[value_column].notna()].sort_values("base_month").tail(6)
    points: list[tuple[str, float]] = []
    for _, row in valid_rows.iterrows():
        points.append((format_period(row["base_month"]), float(row[value_column])))
    return points


def policy_monthly_amounts(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty or "cumulative_support_amount_krw" not in rows.columns:
        return pd.DataFrame(columns=["base_month", "monthly_support_amount_krw"])
    valid_rows = rows[rows["cumulative_support_amount_krw"].notna()].sort_values("base_month").copy()
    if valid_rows.empty:
        return pd.DataFrame(columns=["base_month", "monthly_support_amount_krw"])

    amounts: list[float] = []
    previous_cumulative: float | None = None
    for _, row in valid_rows.iterrows():
        current_cumulative = float(row["cumulative_support_amount_krw"])
        if previous_cumulative is None or current_cumulative < previous_cumulative:
            monthly_amount = current_cumulative
        else:
            monthly_amount = current_cumulative - previous_cumulative
        amounts.append(monthly_amount)
        previous_cumulative = current_cumulative
    valid_rows["monthly_support_amount_krw"] = amounts
    return valid_rows


def recent_policy_monthly_points(rows: pd.DataFrame) -> list[tuple[str, float]]:
    monthly_rows = policy_monthly_amounts(rows).tail(6)
    return [
        (format_period(row["base_month"]), float(row["monthly_support_amount_krw"]))
        for _, row in monthly_rows.iterrows()
    ]


def latest_policy_monthly_amount(rows: pd.DataFrame) -> tuple[float | None, str | None, str]:
    monthly_rows = policy_monthly_amounts(rows)
    if monthly_rows.empty:
        return None, None, "neutral"
    latest_amount = float(monthly_rows.iloc[-1]["monthly_support_amount_krw"])
    if len(monthly_rows) < 2:
        return latest_amount, None, "neutral"
    previous_amount = float(monthly_rows.iloc[-2]["monthly_support_amount_krw"])
    delta_text, gap = format_delta(latest_amount, previous_amount, "원")
    return latest_amount, delta_text, tone_from_gap(gap, "higher_is_better")


def sparkline_svg(
    points: list[tuple[str, float]],
    alt_points: list[tuple[str, float]] | None = None,
    alt_label: str = "",
) -> str:
    alt_points = alt_points or []
    if not points:
        return """
        <div class="spark-empty">
          <span>최근 추이 데이터 없음</span>
        </div>
        """
    if len(points) < 2:
        return f"""
        <div class="spark-empty">
          <span>{safe_text(points[0][0])} 1개 지점 · 추이 산출 불가</span>
        </div>
        """

    values = [value for _, value in points] + [value for _, value in alt_points]
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        min_v -= 1
        max_v += 1

    def build_coords(data: list[tuple[str, float]]) -> list[tuple[str, float, float, float]]:
        coords: list[tuple[str, float, float, float]] = []
        denominator = max(1, len(data) - 1)
        for idx, (label, value) in enumerate(data):
            x_pct = 5 + idx * (90 / denominator)
            y_pct = 18 + ((max_v - value) / (max_v - min_v) * 50)
            coords.append((label, value, x_pct, y_pct))
        return coords

    def build_segments(coords: list[tuple[str, float, float, float]], css_class: str) -> list[str]:
        segments: list[str] = []
        for idx in range(len(coords) - 1):
            _, _, x1, y1 = coords[idx]
            _, _, x2, y2 = coords[idx + 1]
            dx = x2 - x1
            dy = y2 - y1
            visual_ratio = 0.34
            width_pct = (dx**2 + (dy * visual_ratio) ** 2) ** 0.5
            angle = math.degrees(math.atan2(dy * visual_ratio, dx))
            segments.append(
                f'<span class="spark-line-segment {css_class}" style="left:{x1:.2f}%; top:{y1:.2f}%; width:{width_pct:.2f}%; transform: rotate({angle:.2f}deg);"></span>'
            )
        return segments

    coords = build_coords(points)
    alt_coords = build_coords(alt_points) if alt_points else []

    segments = build_segments(coords, "primary")
    alt_segments = build_segments(alt_coords, "secondary") if alt_coords else []

    dots = []
    for label, value, x_pct, y_pct in coords:
        dots.append(
            f"""
            <span class="spark-dot primary" style="left:{x_pct:.2f}%; top:{y_pct:.2f}%;" title="{safe_text(label)}: {value:,.1f}"></span>
            <span class="spark-x-label" style="left:{x_pct:.2f}%;">{safe_text(short_period_label(label))}</span>
            """
        )

    alt_dots = []
    for label, value, x_pct, y_pct in alt_coords:
        alt_dots.append(
            f"""
            <span class="spark-dot secondary" style="left:{x_pct:.2f}%; top:{y_pct:.2f}%;" title="{safe_text(label)} {safe_text(alt_label)}: {value:,.1f}"></span>
            """
        )

    legend_html = ""
    if alt_points:
        legend_html = f"""
        <div class="spark-legend">
          <span><i class="primary"></i>일반</span>
          <span><i class="secondary"></i>{safe_text(alt_label or "QR")}</span>
        </div>
        """

    return f"""
    <div class="sparkline-wrap">
      {legend_html}
      <div class="spark-line-chart" role="img" aria-label="최근 추이">
        {''.join(segments)}
        {''.join(alt_segments)}
        {''.join(dots)}
        {''.join(alt_dots)}
      </div>
    </div>
    """


def make_observation_card(
    observations: pd.DataFrame,
    catalog_row: pd.Series,
    group: str | None = None,
) -> Card:
    latest = latest_for_indicator(observations, catalog_row["id"])
    if latest is None:
        return Card(
            title=str(catalog_row["name"]),
            group=group or str(catalog_row["panel"]),
            value="자료대기",
            period=str(catalog_row["frequency"]),
            source=source_label(catalog_row["source"], catalog_row["source_ref"]),
            confidence=str(catalog_row.get("confidence", "")),
            note="부산 관측값이 아직 DB에 적재되지 않음",
            empty=True,
            bar_pct=0,
            bar_left="입력 전",
            bar_right="자료대기",
            description=metric_description(catalog_row),
        )

    previous = previous_for_indicator(
        observations,
        str(catalog_row["id"]),
        str(latest["region"]),
        str(latest["base_period"]),
    )
    benchmark = benchmark_for_indicator(observations, str(catalog_row["id"]), str(latest["base_period"]))
    delta_text, delta_gap = (None, None)
    if previous is not None:
        delta_text, delta_gap = format_delta(latest["value"], previous["value"], latest["unit"])
    benchmark_text, benchmark_gap = (None, None)
    if benchmark is not None and str(benchmark["region"]) != str(latest["region"]):
        benchmark_text, benchmark_gap = format_benchmark(latest["value"], benchmark["value"], latest["unit"])
    bar_pct, bar_left, bar_right = bar_scale(latest["value"], str(latest["unit"]))
    chart_points = recent_points_for_indicator(
        observations,
        str(catalog_row["id"]),
        str(latest["region"]),
    )

    return Card(
        title=str(catalog_row["name"]),
        group=group or str(catalog_row["panel"]),
        value=format_metric_number(latest["value"], latest["unit"]),
        period=format_period(latest["base_period"]),
        source=source_label(latest["source"], latest["source_ref"]),
        unit=unit_label(str(latest["unit"])),
        previous_value=delta_text,
        previous_tone=tone_from_gap(delta_gap, str(catalog_row["direction"])),
        benchmark_value=benchmark_text,
        benchmark_tone=tone_from_gap(benchmark_gap, str(catalog_row["direction"])),
        note=str(latest["note"]) if not is_missing(latest["note"]) else None,
        confidence=str(catalog_row.get("confidence", "")),
        bar_pct=bar_pct,
        bar_left=bar_left,
        bar_right=bar_right,
        chart_points=chart_points,
        description=metric_description(catalog_row),
    )


def manual_delta(rows: pd.DataFrame, value_column: str, unit: str) -> tuple[str | None, str]:
    if rows.empty or len(rows) < 2:
        return None, "neutral"
    latest = rows.iloc[0][value_column]
    previous = rows.iloc[1][value_column]
    delta_text, gap = format_delta(latest, previous, unit)
    return delta_text, tone_from_gap(gap, "higher_is_better")


def make_manual_cards(credit_df: pd.DataFrame, policy_df: pd.DataFrame) -> list[Card]:
    cards: list[Card] = []
    if credit_df.empty:
        cards.append(
            Card(
                title="부산 소상공인 신용보증 월별 공급액",
                group="소상공인 자금 지원",
                value="자료대기",
                period="월",
                source="부산신용보증재단 제공자료",
                empty=True,
                unit="억원",
                bar_pct=0,
                bar_left="입력 전",
                bar_right="자료대기",
                chart_points=[],
                description="부산 소상공인이 금융기관 대출을 받을 수 있도록 부산신용보증재단이 보증한 월별 공급액입니다. 지역 소상공인 정책금융 지원 규모를 보는 지표입니다.",
            )
        )
    else:
        latest = credit_df.iloc[0]
        delta_text, delta_tone = manual_delta(credit_df, "guarantee_supply_amount_krw", "원")
        bar_pct, bar_left, bar_right = bar_scale(latest.get("guarantee_supply_amount_krw"), "원")
        note_parts = []
        if not is_missing(latest.get("guarantee_supply_count")):
            note_parts.append(f"공급건수 {format_value(latest['guarantee_supply_count'], '건')}")
        if not is_missing(latest.get("guarantee_balance_krw")):
            note_parts.append(f"보증잔액 {format_value(latest['guarantee_balance_krw'], '원')}")
        cards.append(
            Card(
                title="부산 소상공인 신용보증 월별 공급액",
                group="소상공인 자금 지원",
                value=format_metric_number(latest.get("guarantee_supply_amount_krw"), "원"),
                period=format_period(latest.get("base_month")),
                source=str(latest.get("source_org") or "부산신용보증재단 제공자료"),
                unit="억원",
                previous_value=delta_text,
                previous_tone=delta_tone,
                benchmark_label="기준 비교",
                benchmark_value="전국 비교 없음 · 기관 월별 제공자료",
                note=" · ".join(note_parts) if note_parts else "금액 입력 전에는 자료대기로 표시",
                confidence="중간",
                empty=is_missing(latest.get("guarantee_supply_amount_krw")),
                bar_pct=bar_pct,
                bar_left=bar_left,
                bar_right=bar_right,
                chart_points=recent_manual_points(credit_df, "guarantee_supply_amount_krw"),
                description="부산 소상공인이 금융기관 대출을 받을 수 있도록 부산신용보증재단이 보증한 월별 공급액입니다. 지역 소상공인 정책금융 지원 규모를 보는 지표입니다.",
            )
        )

    if policy_df.empty:
        cards.append(
            Card(
                title="부산 소상공인 특별자금 월별공급액",
                group="소상공인 자금 지원",
                value="자료대기",
                period="월",
                source="부산신용보증재단",
                empty=True,
                unit="억원",
                bar_pct=0,
                bar_left="입력 전",
                bar_right="자료대기",
                chart_points=[],
                description="부산 소상공인 특별자금의 월별 공급 규모입니다. 기관 제공자료의 누계지원액을 기준으로 1월은 누계값, 2월 이후는 당월 누계지원액에서 전월 누계지원액을 차감해 산출합니다.",
            )
        )
    else:
        latest = policy_df.iloc[0]
        latest_monthly_amount, delta_text, delta_tone = latest_policy_monthly_amount(policy_df)
        cumulative_amount = latest.get("cumulative_support_amount_krw")
        bar_pct, bar_left, bar_right = bar_scale(latest_monthly_amount, "원")
        benchmark_parts = []
        benchmark_parts.append(f"총계획 {format_won_compact(latest.get('total_plan_amount_krw'))}")
        if not is_missing(latest.get("execution_rate_pct")):
            benchmark_parts.append(f"집행률 {format_value(latest.get('execution_rate_pct'), '%')}")
        cards.append(
            Card(
                title="부산 소상공인 특별자금 월별공급액",
                group="소상공인 자금 지원",
                value=format_metric_number(latest_monthly_amount, "원"),
                period=format_period(latest.get("base_month")),
                source="부산신용보증재단",
                unit="억원",
                previous_value=delta_text,
                previous_tone=delta_tone,
                benchmark_label="기준 비교",
                benchmark_value=" · ".join(benchmark_parts),
                note=f"누계 공급액 {format_won_compact(cumulative_amount)} 기준으로 월별 공급액 산출",
                confidence="중간",
                empty=is_missing(latest_monthly_amount),
                bar_pct=bar_pct,
                bar_left=bar_left,
                bar_right=bar_right,
                chart_points=recent_policy_monthly_points(policy_df),
                description="부산 소상공인 특별자금의 월별 공급 규모입니다. 기관 제공자료의 누계지원액을 기준으로 1월은 누계값, 2월 이후는 당월 누계지원액에서 전월 누계지원액을 차감해 산출합니다.",
            )
        )
    return cards


DONGBAEK_MERCHANT_ROWS: list[tuple[str, int, int]] = [
    ("2026.01", 156_606, 32_448),
    ("2026.02", 159_134, 33_355),
    ("2026.03", 161_999, 34_559),
    ("2026.04", 163_775, 36_054),
    ("2026.05", 160_714, 36_013),
    ("2026.06", 161_636, 36_679),
]


def make_dongbaek_card() -> Card:
    latest_period, latest_general, latest_qr = DONGBAEK_MERCHANT_ROWS[-1]
    _, previous_general, previous_qr = DONGBAEK_MERCHANT_ROWS[-2]
    general_delta = latest_general - previous_general
    qr_delta = latest_qr - previous_qr
    delta_tone = "positive" if general_delta >= 0 and qr_delta >= 0 else "negative"
    return Card(
        title="동백전 가맹점 수(QR)",
        group="소비·상권",
        value=f"{latest_general:,}({latest_qr:,})",
        period=latest_period,
        source="부산광역시 동백전 운영자료",
        unit="개소",
        previous_value=f"일반 {general_delta:+,}개 · QR {qr_delta:+,}개",
        previous_tone=delta_tone,
        benchmark_label="기준 비교",
        benchmark_value="전국 비교 없음",
        benchmark_tone="neutral",
        chart_points=[(period, float(general)) for period, general, _ in DONGBAEK_MERCHANT_ROWS],
        chart_points_alt=[(period, float(qr)) for period, _, qr in DONGBAEK_MERCHANT_ROWS],
        chart_alt_label="QR",
        confidence="중간",
        description="동백전 가맹점을 일반 가맹점과 QR 가맹점으로 구분한 수동 입력 지표입니다. 일반과 QR을 합산하지 않고 각각 표기합니다.",
    )


def render_badge(label: str, value: str | None, tone: str) -> str:
    if not value:
        value = "비교값 없음"
        tone = "neutral"
    return f"""
    <tr class="{tone}">
      <th>{safe_text(label)}</th>
      <td>{safe_text(value)}</td>
    </tr>
    """


def category_icon(group: str) -> tuple[str, str]:
    group_text = str(group)
    if "자금" in group_text:
        return "funding", ""
    if "경기체감" in group_text or "전통시장" in group_text:
        return "sentiment", ""
    if "소비" in group_text or "카드" in group_text:
        return "card", ""
    if "고용" in group_text or "물가" in group_text:
        return "work", ""
    if "지역경기" in group_text or "지역" in group_text:
        return "region", ""
    return "default", ""


def render_metric_value(card: Card) -> str:
    if card.title == "동백전 가맹점 수(QR)" and "(" in card.value and card.value.endswith(")"):
        main, suffix = card.value.split("(", 1)
        return (
            '<strong class="metric-value-combo">'
            f"<b>{safe_text(main)}</b>"
            f"<small>({safe_text(suffix)}</small>"
            "</strong>"
        )
    return f"<strong>{safe_text(card.value)}</strong>"


def render_card(card: Card) -> str:
    empty_class = " empty" if card.empty else ""
    chart_html = sparkline_svg(card.chart_points, card.chart_points_alt, card.chart_alt_label)
    icon_type, icon_html = category_icon(card.group)
    detail_class = " has-detail" if card.value_detail else ""
    value_detail_html = (
        f'<em class="metric-value-detail">{safe_text(card.value_detail)}</em>'
        if card.value_detail
        else ""
    )
    value_html = render_metric_value(card)
    info_id = "metric-info-" + hashlib.sha1(
        f"{card.group}|{card.title}|{card.period}".encode("utf-8")
    ).hexdigest()[:12]
    return f"""
        <article class="indicator-card dashboard-card hero-card card-theme-{icon_type}{empty_class}">
          <div class="metric-head">
            <div class="metric-category">
              <span class="category-icon category-icon-{icon_type}" aria-hidden="true">{safe_text(icon_html)}</span>
              <span>{safe_text(card.group)}</span>
            </div>
            <div class="metric-info">
              <input class="metric-info-toggle" type="checkbox" id="{info_id}" />
              <label class="metric-info-button" for="{info_id}" aria-label="지표 설명 보기">!</label>
              <div class="metric-info-panel">
                <label class="metric-info-close" for="{info_id}" aria-label="설명 닫기">×</label>
                <p>{safe_text(card.description or card.note or "해당 지표의 정의와 수집 기준을 확인 중입니다.")}</p>
              </div>
            </div>
          </div>
          <h3>{safe_text(card.title)}</h3>
          <div class="metric-unit">단위 : {safe_text(card.unit or '값')}</div>
          <div class="metric-value-wrap{detail_class}">
            {value_html}
            {value_detail_html}
            <span>{safe_text(card.period)}</span>
          </div>
          <div class="compare-title">비교표</div>
          <table class="compare-table">
            <tbody>
              {render_badge(card.previous_label, card.previous_value, card.previous_tone)}
              {render_badge(card.benchmark_label, card.benchmark_value, card.benchmark_tone)}
            </tbody>
          </table>
          <div class="trend-title">최근 추이</div>
          <div class="trend-box">
            {chart_html}
          </div>
          <div class="metric-source">
            <span>출처: {safe_text(card.source)}</span>
          </div>
        </article>
        """


def render_card_grid(cards: list[Card], columns: int = 3) -> None:
    cards_html = "\n".join(render_card(card) for card in cards)
    st.html(
        f'<div class="cards-grid cards-grid-{columns} notranslate" translate="no" lang="ko">'
        f"{cards_html}</div>"
    )


def active_view() -> str:
    raw_view = st.query_params.get("view", "economy")
    if isinstance(raw_view, list):
        raw_view = raw_view[0] if raw_view else "economy"
    return raw_view if raw_view in {"economy", "check"} else "economy"


def nav_class(view: str, current_view: str, base_class: str) -> str:
    classes = [base_class]
    if view == current_view:
        classes.append("active")
    return " ".join(classes)


def render_project_card(project: EmergencyProject) -> str:
    return f"""
      <article class="project-card">
        <div class="project-card-top">
          <div>
            <div class="project-card-head">
              <span class="project-number">{project.number:02d}</span>
              <span class="project-field">{safe_text(project.field)}</span>
            </div>
            <h3>{safe_text(project.title)}</h3>
          </div>
          <div class="project-ring" style="--pct:{project.progress_pct};">
            <span>{project.progress_pct}%</span>
          </div>
        </div>
        <dl class="project-meta">
          <div>
            <dt>소관부서</dt>
            <dd>{safe_text(project.department)}</dd>
          </div>
          <div>
            <dt>소요예산</dt>
            <dd>{safe_text(project.budget)}</dd>
          </div>
        </dl>
        <p class="project-feature">{safe_text(project.feature)}</p>
        <div class="project-stage">
          <span class="is-current">계획 중</span>
          <span>예산 작업중</span>
          <span>집행중</span>
          <span>완료</span>
        </div>
        <div class="project-check-row">
          <strong>{safe_text(project.status)}</strong>
          <span>{safe_text(project.latest_update)}</span>
        </div>
        <div class="project-milestone">
          <span>추진계획</span>
          <strong>{safe_text(project.milestone)}</strong>
        </div>
      </article>
    """


def render_project_dashboard(projects: list[EmergencyProject]) -> None:
    budget_projects = [project for project in projects if project.budget != "비예산"]
    html_cards = "\n".join(render_project_card(project) for project in projects)
    st.html(
        f"""
        <section class="project-board notranslate" translate="no" lang="ko">
          <div class="project-board-head">
            <div>
              <span class="project-kicker">매일 부산광역시장 직접 점검</span>
              <h2>민생100일 비상대책 추진상황</h2>
            </div>
          </div>
          <div class="project-summary">
            <div>
              <span>관리사업</span>
              <strong>{len(projects)}개</strong>
            </div>
            <div>
              <span>총 사업규모</span>
              <strong>1조 4,320.5억원</strong>
            </div>
            <div>
              <span>예산사업</span>
              <strong>{len(budget_projects)}개</strong>
            </div>
            <div>
              <span>일일 입력</span>
              <strong>부서 계정 방식</strong>
            </div>
          </div>
          <div class="project-flow">
            <span>담당부서 일일 입력</span>
            <i></i>
            <span>사업별 상태 갱신</span>
            <i></i>
            <span>부산광역시장 일일 점검</span>
          </div>
          <div class="project-grid">
            {html_cards}
          </div>
          <div class="project-source">
            출처: 부산 민생 100일 비상조치 사업 규모(2026.6.22), 부산 민생 100일 비상조치 계획(안)(2026.6.22)
          </div>
        </section>
        """
    )


def render_trend_chart(observations: pd.DataFrame, indicator_ids: list[str], title: str) -> None:
    chart_rows = observations[
        observations["indicator_id"].isin(indicator_ids)
        & observations["region"].astype(str).str.contains("부산", na=False)
    ].copy()
    if chart_rows.empty:
        st.info(f"{title} 추이 자료가 없습니다.")
        return
    chart_rows["label"] = chart_rows["name"].astype(str).str.replace("부산 ", "", regex=False)
    chart_rows = chart_rows.sort_values("base_period")
    pivot = chart_rows.pivot_table(
        index="base_period",
        columns="label",
        values="value",
        aggfunc="last",
    )
    st.line_chart(pivot, height=260)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #1d2730;
          --muted: #667280;
          --line: #d8e0e7;
          --panel: #ffffff;
          --soft: #f4f7fa;
          --navy: #234260;
          --blue: #2f6fbd;
          --teal: #167c80;
          --amber: #b6791c;
          --red: #b9473f;
          --font-kr: "Malgun Gothic", "맑은 고딕", "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
          --font-latin: Arial, Helvetica, sans-serif;
        }

        html,
        body,
        .stApp,
        div[data-testid="stAppViewContainer"],
        .top-board-header,
        .dashboard-grid-head,
        .cards-grid {
          font-family: var(--font-kr);
          font-synthesis-weight: none;
          text-rendering: geometricPrecision;
          -webkit-font-smoothing: antialiased;
        }

        .block-container {
          max-width: none;
          padding-top: 0;
          padding-bottom: 56px;
          padding-left: 0;
          padding-right: 0;
        }

        #MainMenu, footer {
          visibility: hidden;
        }

        div[data-testid="stHeader"] {
          display: none !important;
        }

        header[data-testid="stHeader"],
        .stAppHeader {
          display: none !important;
          height: 0 !important;
        }

        section[data-testid="stMain"] > div,
        div[data-testid="stAppViewBlockContainer"] {
          padding-top: 0 !important;
        }

        div[data-testid="stToolbar"],
        div[data-testid="stDecoration"],
        div[data-testid="stStatusWidget"],
        div[data-testid="stDeployButton"] {
          display: none !important;
        }

        div[data-testid="stVerticalBlock"] {
          gap: 1rem;
        }

        .main .block-container > div,
        div[data-testid="stAppViewContainer"] .block-container > div {
          max-width: none;
        }

        .element-container,
        div[data-testid="stHorizontalBlock"],
        div[data-testid="stDataFrameResizable"] {
          max-width: 1680px;
          margin-left: auto;
          margin-right: auto;
        }

        div[data-testid="stHorizontalBlock"] {
          width: calc(100% - 72px);
        }

        .top-board-header {
          width: 100%;
          background: #06052a;
          color: #fff;
          margin: 0 0 28px;
        }

        .top-board-inner {
          width: 100%;
          min-height: 104px;
          margin: 0 auto;
          padding: 0 48px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 24px;
          box-sizing: border-box;
        }

        .board-logo {
          display: flex;
          flex-direction: column;
          gap: 5px;
          min-width: 520px;
          transform: translateY(-4px);
        }

        .board-logo strong {
          color: #fff;
          font-size: 28px;
          font-weight: 900;
          line-height: 1.05;
          letter-spacing: 0;
          text-shadow: none;
        }

        .board-logo span {
          color: #ff4c94;
          font-size: 17px;
          font-weight: 900;
          line-height: 1;
        }

        .top-nav {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 22px;
          flex: 1;
          transform: translateY(8px);
        }

        .nav-item {
          color: #fff;
          font-size: 18px;
          font-weight: 700;
          white-space: nowrap;
          text-shadow: none;
          text-decoration: none;
          cursor: pointer;
          transition: transform 0.16s ease, filter 0.16s ease;
        }

        .nav-item:link,
        .nav-item:visited,
        .nav-item:active,
        .nav-item * {
          color: #fff;
          text-decoration: none !important;
        }

        .nav-item:hover {
          color: #fff;
          text-decoration: none !important;
          filter: brightness(1.08);
          transform: translateY(-1px);
        }

        .nav-item.active,
        .nav-item.nav-economy {
          min-width: 232px;
          height: 48px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 999px;
          background: linear-gradient(90deg, #43a047 0%, #4869c9 100%);
          border: 2px solid rgba(255, 255, 255, 0.45);
          box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
        }

        .nav-item.nav-check {
          min-width: 278px;
          height: 48px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 0 22px;
          border-radius: 999px;
          background: linear-gradient(90deg, #e34d5f 0%, #f59e0b 100%);
          border: 2px solid rgba(255, 255, 255, 0.42);
          box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
        }

        .nav-title {
          display: inline-block;
          white-space: nowrap;
        }

        .top-tools {
          display: flex;
          align-items: center;
          gap: 14px;
        }

        .lang-chip {
          width: 52px;
          height: 32px;
          border: 1px solid #fff;
          border-radius: 999px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          font-size: 15px;
          font-weight: 700;
        }

        .hamburger {
          width: 32px;
          height: 22px;
          position: relative;
        }

        .hamburger::before,
        .hamburger::after,
        .hamburger span {
          content: "";
          position: absolute;
          left: 0;
          width: 32px;
          height: 3px;
          background: #fff;
          border-radius: 2px;
        }

        .hamburger::before { top: 0; }
        .hamburger span { top: 9px; }
        .hamburger::after { bottom: 0; }

        .dashboard-summary {
          display: none;
        }

        .project-board {
          max-width: 1680px;
          margin: 0 auto 54px;
          padding: 0 36px 36px;
        }

        .project-board-head {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 28px;
          padding: 22px 0 6px;
        }

        .project-kicker {
          display: inline-block;
          margin-bottom: 8px;
          color: #e34d5f;
          font-size: 16px;
          font-weight: 900;
        }

        .project-board-head h2 {
          margin: 0;
          color: #081521;
          font-size: 32px;
          font-weight: 900;
          letter-spacing: 0;
        }

        .project-summary {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 16px;
          margin: 18px 0 18px;
        }

        .project-summary div {
          min-height: 92px;
          padding: 18px 20px;
          border-radius: 18px;
          background: linear-gradient(135deg, #111f55 0%, #265b9e 100%);
          color: #fff;
          box-shadow: 0 14px 28px rgba(11, 23, 51, 0.12);
          box-sizing: border-box;
        }

        .project-summary span {
          display: block;
          margin-bottom: 8px;
          color: rgba(255, 255, 255, 0.72);
          font-size: 14px;
          font-weight: 800;
        }

        .project-summary strong {
          display: block;
          font-size: 24px;
          font-weight: 900;
          line-height: 1.15;
        }

        .project-flow {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 0 0 22px;
          color: #203040;
          font-size: 15px;
          font-weight: 900;
        }

        .project-flow span {
          padding: 9px 14px;
          border-radius: 999px;
          background: #eef3f8;
          border: 1px solid #d8e0e7;
        }

        .project-flow i {
          width: 34px;
          height: 2px;
          background: #a9b8c7;
          position: relative;
        }

        .project-flow i::after {
          content: "";
          position: absolute;
          right: -1px;
          top: -4px;
          width: 8px;
          height: 8px;
          border-right: 2px solid #a9b8c7;
          border-top: 2px solid #a9b8c7;
          transform: rotate(45deg);
        }

        .project-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 20px;
        }

        .project-card {
          min-height: 336px;
          padding: 24px;
          border-radius: 20px;
          background:
            radial-gradient(circle at 90% 10%, rgba(255, 255, 255, 0.18), transparent 30%),
            linear-gradient(145deg, #22338f 0%, #15296e 48%, #163e7a 100%);
          color: #fff;
          box-shadow: 0 18px 36px rgba(7, 18, 45, 0.17);
          box-sizing: border-box;
        }

        .project-card:nth-child(4n+2) {
          background:
            radial-gradient(circle at 90% 10%, rgba(255, 255, 255, 0.18), transparent 30%),
            linear-gradient(145deg, #0d7f7c 0%, #176379 50%, #194c89 100%);
        }

        .project-card:nth-child(4n+3) {
          background:
            radial-gradient(circle at 90% 10%, rgba(255, 255, 255, 0.18), transparent 30%),
            linear-gradient(145deg, #b33b65 0%, #8f3c88 42%, #284894 100%);
        }

        .project-card:nth-child(4n) {
          background:
            radial-gradient(circle at 90% 10%, rgba(255, 255, 255, 0.18), transparent 30%),
            linear-gradient(145deg, #315f88 0%, #22557b 46%, #11415f 100%);
        }

        .project-card-top {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 96px;
          align-items: start;
          gap: 18px;
          margin-bottom: 18px;
        }

        .project-card-head {
          display: inline-flex;
          align-items: center;
          gap: 9px;
          margin-bottom: 12px;
        }

        .project-number {
          width: 42px;
          height: 42px;
          border-radius: 999px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: rgba(255, 255, 255, 0.18);
          border: 1px solid rgba(255, 255, 255, 0.3);
          color: #fff;
          font-size: 17px;
          font-weight: 900;
        }

        .project-card h3 {
          min-height: 64px;
          margin: 0;
          color: #fff;
          font-size: 26px;
          font-weight: 900;
          line-height: 1.24;
          word-break: keep-all;
        }

        .project-field {
          display: inline-flex;
          padding: 7px 12px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.14);
          color: rgba(255, 255, 255, 0.86);
          font-size: 13px;
          font-weight: 900;
        }

        .project-ring {
          width: 88px;
          height: 88px;
          border-radius: 999px;
          display: flex;
          align-items: center;
          justify-content: center;
          justify-self: end;
          background:
            radial-gradient(circle, rgba(15, 30, 70, 0.9) 0 50%, transparent 51%),
            conic-gradient(#3eeadf calc(var(--pct) * 1%), rgba(255,255,255,0.22) 0);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.18);
        }

        .project-ring span {
          color: #fff;
          font-size: 20px;
          font-weight: 900;
        }

        .project-meta {
          display: grid;
          grid-template-columns: minmax(0, 1.35fr) minmax(160px, 0.65fr);
          gap: 10px;
          margin: 0 0 15px;
        }

        .project-meta div {
          padding: 13px 14px;
          border-radius: 12px;
          background: rgba(255, 255, 255, 0.12);
        }

        .project-meta dt {
          margin: 0 0 6px;
          color: rgba(255, 255, 255, 0.72);
          font-size: 12px;
          font-weight: 800;
        }

        .project-meta dd {
          margin: 0;
          color: #fff;
          font-size: 15px;
          font-weight: 900;
          line-height: 1.3;
          word-break: keep-all;
        }

        .project-feature {
          min-height: 48px;
          margin: 0 0 15px;
          color: rgba(255, 255, 255, 0.9);
          font-size: 15px;
          font-weight: 750;
          line-height: 1.45;
          word-break: keep-all;
        }

        .project-stage {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 8px;
          margin: 0 0 14px;
        }

        .project-stage span {
          min-height: 34px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.12);
          color: rgba(255, 255, 255, 0.76);
          font-size: 13px;
          font-weight: 900;
        }

        .project-stage span.is-current {
          background: #3eeadf;
          color: #062236;
        }

        .project-check-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin: 0 0 14px;
          padding: 12px 14px;
          border-radius: 12px;
          background: rgba(255, 255, 255, 0.12);
          color: #fff;
        }

        .project-check-row strong {
          font-size: 17px;
          font-weight: 900;
          white-space: nowrap;
        }

        .project-check-row span {
          color: rgba(255, 255, 255, 0.78);
          font-size: 13px;
          font-weight: 850;
          text-align: right;
        }

        .project-milestone {
          padding-top: 14px;
          border-top: 1px solid rgba(255, 255, 255, 0.2);
        }

        .project-milestone span {
          display: block;
          margin-bottom: 6px;
          color: rgba(255, 255, 255, 0.68);
          font-size: 12px;
          font-weight: 900;
        }

        .project-milestone strong {
          display: block;
          color: #fff;
          font-size: 14px;
          font-weight: 850;
          line-height: 1.42;
          word-break: keep-all;
        }

        .project-source {
          margin: 20px 0 0;
          color: #627181;
          font-size: 13px;
          font-weight: 800;
        }

        .status-strip {
          display: none;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
          margin: 10px 0 18px;
        }

        .status-tile {
          border: 1px solid var(--line);
          border-radius: 8px;
          background: var(--panel);
          padding: 13px 15px;
        }

        .status-tile span {
          display: block;
          color: var(--muted);
          font-size: 12px;
          font-weight: 700;
          margin-bottom: 5px;
        }

        .status-tile strong {
          color: var(--ink);
          font-size: 19px;
          line-height: 1.2;
        }

        .section-title {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 12px;
          width: calc(100% - 72px);
          max-width: 1680px;
          margin: 26px auto 10px;
          border-bottom: 1px solid var(--line);
          padding-bottom: 10px;
        }

        .section-title h2 {
          color: var(--ink);
          font-size: 20px;
          font-weight: 700;
          line-height: 1.3;
          margin: 0;
          letter-spacing: 0;
        }

        .section-title p {
          color: var(--muted);
          font-size: 13px;
          margin: 0;
          text-align: right;
        }

        .dashboard-grid-head {
          width: calc(100% - 72px);
          max-width: 1680px;
          margin: 20px auto 10px;
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 16px;
          border-bottom: 1px solid var(--line);
          padding-bottom: 12px;
        }

        .grid-title {
          display: flex;
          align-items: baseline;
          gap: 14px;
        }

        .grid-title strong {
          color: var(--ink);
          font-size: 24px;
          font-weight: 800;
          letter-spacing: 0;
        }

        .grid-title span {
          color: var(--muted);
          font-size: 13px;
          font-weight: 750;
        }

        .section-right {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 14px;
        }

        .d-day-panel {
          display: inline-flex;
          align-items: center;
          gap: 12px;
          min-width: 160px;
          height: 56px;
          padding: 0 18px;
          border-radius: 16px;
          background: #ffd91a;
          color: #111;
          box-shadow: 0 5px 0 #e1b800, 0 12px 24px rgba(0, 0, 0, 0.12);
        }

        .d-day-hourglass {
          position: relative;
          width: 24px;
          height: 32px;
          flex: 0 0 auto;
        }

        .d-day-hourglass::before,
        .d-day-hourglass::after {
          content: "";
          position: absolute;
          left: 2px;
          width: 20px;
          height: 14px;
          border-left: 3px solid #111;
          border-right: 3px solid #111;
          box-sizing: border-box;
        }

        .d-day-hourglass::before {
          top: 1px;
          border-top: 3px solid #111;
          clip-path: polygon(0 0, 100% 0, 50% 100%);
          background: rgba(0, 0, 0, 0.10);
        }

        .d-day-hourglass::after {
          bottom: 1px;
          border-bottom: 3px solid #111;
          clip-path: polygon(50% 0, 100% 100%, 0 100%);
          background: rgba(0, 0, 0, 0.20);
        }

        .d-day-text {
          display: inline-flex;
          align-items: center;
          line-height: 1.05;
        }

        .d-day-text strong {
          color: #111;
          font-size: 30px;
          font-weight: 800;
          letter-spacing: 0;
          white-space: nowrap;
        }

        .latin-d {
          font-family: var(--font-latin);
          font-weight: 800;
        }

        .cards-grid {
          width: calc(100% - 72px);
          max-width: 1680px;
          margin: 0 auto 30px;
          display: grid;
          gap: 18px;
        }

        .cards-grid-3 {
          grid-template-columns: repeat(3, minmax(360px, 1fr));
          overflow-x: auto;
          padding-bottom: 6px;
        }

        .indicator-card {
          position: relative;
          min-height: 438px;
          border: 1px solid #d4d4d4;
          border-radius: 14px;
          background: var(--panel);
          padding: 26px 28px 22px;
          box-shadow: 0 3px 9px rgba(0, 0, 0, 0.10);
          margin-bottom: 18px;
        }

        .indicator-card.empty {
          background: #fff;
        }

        .indicator-card.hero-card {
          border: 0;
          color: #fff;
          box-shadow: 0 12px 24px rgba(24, 33, 68, 0.18);
          overflow: hidden;
        }

        .indicator-card.hero-card::before {
          content: "";
          position: absolute;
          inset: 0;
          background:
            radial-gradient(circle at 85% 12%, rgba(255,255,255,0.18), transparent 24%),
            linear-gradient(135deg, rgba(255,255,255,0.12), transparent 44%);
          pointer-events: none;
        }

        .indicator-card.hero-card > * {
          position: relative;
          z-index: 1;
        }

        .indicator-card.hero-card.card-theme-funding {
          background: linear-gradient(135deg, #3340a0 0%, #263184 100%);
        }

        .indicator-card.hero-card.card-theme-sentiment {
          background: linear-gradient(135deg, #127b72 0%, #1d4e89 100%);
        }

        .indicator-card.hero-card.card-theme-card {
          background: linear-gradient(135deg, #1f67a8 0%, #234282 100%);
        }

        .indicator-card.hero-card.card-theme-work {
          background: linear-gradient(135deg, #9a4d35 0%, #75324f 100%);
        }

        .indicator-card.hero-card.card-theme-region {
          background: linear-gradient(135deg, #5554b8 0%, #2d367d 100%);
        }

        .indicator-card.hero-card.card-theme-default {
          background: linear-gradient(135deg, #334155 0%, #1f2937 100%);
        }

        .metric-head {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 10px;
          position: relative;
          z-index: 80;
        }

        .metric-category {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          color: #59636e;
          font-size: 17px;
          font-weight: 700;
          white-space: normal;
          word-break: keep-all;
        }

        .category-icon {
          position: relative;
          width: 30px;
          height: 30px;
          border-radius: 50%;
          background: #d84d7f;
          color: #fff;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          flex: 0 0 auto;
          box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.14);
        }

        .category-icon::before,
        .category-icon::after {
          content: "";
          position: absolute;
          box-sizing: border-box;
        }

        .category-icon-funding {
          background: #d84d7f;
        }

        .category-icon-funding::before {
          content: "₩";
          left: 5px;
          top: 6px;
          color: #fff;
          font-family: var(--font-kr);
          font-size: 12px;
          font-weight: 800;
          line-height: 1;
        }

        .category-icon-funding::after {
          right: 5px;
          bottom: 6px;
          width: 9px;
          height: 9px;
          background:
            linear-gradient(#fff, #fff) 0 5px / 2px 4px no-repeat,
            linear-gradient(#fff, #fff) 4px 2px / 2px 7px no-repeat,
            linear-gradient(#fff, #fff) 8px 0 / 2px 9px no-repeat;
        }

        .category-icon-sentiment {
          background:
            radial-gradient(circle at 50% 67%, #fff 0 2px, transparent 2.5px),
            #57b861;
        }

        .category-icon-sentiment::before {
          left: 7px;
          top: 8px;
          width: 16px;
          height: 10px;
          border: 2px solid #fff;
          border-bottom: 0;
          border-radius: 16px 16px 0 0;
        }

        .category-icon-sentiment::after {
          left: 14px;
          top: 17px;
          width: 9px;
          height: 2px;
          border-radius: 999px;
          background: #fff;
          transform: rotate(-36deg);
          transform-origin: left center;
        }

        .category-icon-card {
          background: #397dd1;
        }

        .category-icon-card::before {
          left: 6px;
          top: 8px;
          width: 18px;
          height: 13px;
          border: 2px solid #fff;
          border-radius: 3px;
        }

        .category-icon-card::after {
          left: 8px;
          top: 12px;
          width: 14px;
          height: 2px;
          background: #fff;
        }

        .category-icon-work {
          background: #d46a38;
        }

        .category-icon-work::before {
          left: 6px;
          top: 10px;
          width: 18px;
          height: 12px;
          border: 2px solid #fff;
          border-radius: 3px;
        }

        .category-icon-work::after {
          left: 11px;
          top: 7px;
          width: 8px;
          height: 5px;
          border: 2px solid #fff;
          border-bottom: 0;
          border-radius: 3px 3px 0 0;
        }

        .category-icon-region {
          background: #6667c8;
        }

        .category-icon-region::before {
          left: 7px;
          top: 8px;
          width: 16px;
          height: 12px;
          border-left: 2px solid #fff;
          border-bottom: 2px solid #fff;
        }

        .category-icon-region::after {
          left: 9px;
          top: 10px;
          width: 13px;
          height: 8px;
          border-top: 2px solid #fff;
          border-right: 2px solid #fff;
          transform: skew(-28deg) rotate(-10deg);
        }

        .category-icon-default {
          background: #6b7280;
        }

        .category-icon-default::before {
          left: 9px;
          top: 9px;
          width: 12px;
          height: 12px;
          border: 2px solid #fff;
          border-radius: 50%;
        }

        .metric-info {
          position: static;
          flex: 0 0 auto;
        }

        .metric-info-toggle {
          position: absolute;
          width: 1px;
          height: 1px;
          opacity: 0;
          pointer-events: none;
        }

        .metric-info-button {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 38px;
          height: 38px;
          border: 0;
          border-radius: 50%;
          background: #b9cbed;
          color: #fff;
          font-size: 22px;
          font-weight: 800;
          line-height: 1;
          cursor: pointer;
          user-select: none;
        }

        .metric-info-toggle:checked + .metric-info-button {
          background: #8fb0e8;
          box-shadow: 0 0 0 2px #111 inset;
        }

        .metric-info-panel {
          display: none;
          position: absolute;
          left: 28px;
          right: 28px;
          top: 76px;
          z-index: 120;
          min-height: 120px;
          border: 1px solid rgba(16, 24, 40, 0.14);
          border-radius: 10px;
          background: #ffffff;
          color: #111;
          padding: 22px 48px 22px 24px;
          box-shadow: 0 18px 42px rgba(0, 0, 0, 0.28);
        }

        .metric-info-toggle:checked ~ .metric-info-panel {
          display: block;
        }

        .indicator-card:has(.metric-info-toggle:checked) .metric-value-wrap {
          visibility: hidden;
        }

        .metric-info-close {
          position: absolute;
          top: 14px;
          right: 14px;
          border: 0;
          background: transparent;
          color: #1f2a44;
          font-size: 28px;
          line-height: 1;
          cursor: pointer;
          user-select: none;
        }

        .metric-info-panel p {
          color: #111;
          font-size: 15px;
          font-weight: 650;
          line-height: 1.45;
          margin: 0;
          word-break: keep-all;
        }

        .indicator-card h3 {
          color: #1f2328;
          min-height: 38px;
          font-size: clamp(22px, 2vw, 26px);
          font-weight: 800;
          line-height: 1.2;
          letter-spacing: 0;
          margin: 0 0 4px;
          word-break: keep-all;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: clip;
        }

        .metric-unit {
          color: #000;
          font-size: 16px;
          font-weight: 750;
          margin-bottom: 16px;
        }

        .metric-value-wrap {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 92px;
          margin: 6px 0 14px;
        }

        .metric-value-wrap strong {
          color: #2f80ed;
          font-size: clamp(34px, 4vw, 52px);
          font-weight: 800;
          line-height: 1.05;
          letter-spacing: 0;
          text-align: center;
          white-space: nowrap;
        }

        .metric-value-combo {
          display: inline-flex;
          align-items: baseline;
          justify-content: center;
          gap: 0;
        }

        .metric-value-combo b {
          color: inherit;
          font: inherit;
          letter-spacing: inherit;
          line-height: inherit;
          white-space: nowrap;
        }

        .metric-value-combo small {
          color: inherit;
          font-size: 0.58em;
          font-weight: 850;
          line-height: 1;
          white-space: nowrap;
        }

        .metric-value-wrap.has-detail strong {
          font-size: clamp(28px, 3.2vw, 46px);
        }

        .metric-value-detail {
          display: block;
          color: #2f80ed;
          font-size: clamp(20px, 2.1vw, 28px);
          font-style: normal;
          font-weight: 850;
          line-height: 1.1;
          margin-top: 6px;
          text-align: center;
          white-space: nowrap;
        }

        .metric-value-wrap span {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          height: 32px;
          padding: 0 18px;
          border-radius: 999px;
          background: #eef1f6;
          color: #6c7786;
          font-size: 18px;
          font-weight: 800;
          margin-top: 8px;
        }

        .compare-title,
        .trend-title {
          color: #1f2328;
          font-size: 14px;
          font-weight: 800;
          margin: 12px 0 7px;
        }

        .compare-table {
          width: 100%;
          border-collapse: collapse;
          table-layout: fixed;
          border-top: 1px solid #dfe4ea;
          border-bottom: 1px solid #dfe4ea;
          margin-bottom: 12px;
        }

        .compare-table tr + tr {
          border-top: 1px solid #edf0f3;
        }

        .compare-table th,
        .compare-table td {
          padding: 8px 6px;
          font-size: 13px;
          line-height: 1.35;
          vertical-align: top;
        }

        .compare-table th {
          width: 30%;
          color: #697381;
          text-align: left;
          font-weight: 700;
          white-space: nowrap;
        }

        .compare-table td {
          color: #111;
          font-weight: 700;
          white-space: nowrap;
        }

        .compare-table tr.positive td {
          color: #0d8b72;
        }

        .compare-table tr.negative td {
          color: #c7423a;
        }

        .trend-box {
          height: 156px;
          border-radius: 8px;
        }

        .sparkline-wrap {
          height: 156px;
          padding: 8px 8px 0;
          box-sizing: border-box;
        }

        .spark-legend {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          height: 18px;
          color: rgba(255, 255, 255, 0.78);
          font-size: 11px;
          font-weight: 800;
          line-height: 1;
          margin-bottom: 2px;
        }

        .spark-legend span {
          display: inline-flex;
          align-items: center;
          gap: 5px;
        }

        .spark-legend i {
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: #35dbe8;
        }

        .spark-legend i.secondary {
          background: #f6dc55;
        }

        .sparkline-caption {
          color: #6d7785;
          font-size: 12px;
          font-weight: 800;
          line-height: 1.2;
          margin-bottom: 2px;
          text-align: right;
        }

        .spark-line-chart {
          position: relative;
          height: 124px;
          padding: 0 8px 22px;
          box-sizing: border-box;
          overflow: hidden;
          border-bottom: 2px solid #9aa2ad;
        }

        .spark-line-segment {
          position: absolute;
          height: 4px;
          border-radius: 999px;
          background: #35dbe8;
          transform-origin: left center;
          box-shadow: 0 0 10px rgba(53, 219, 232, 0.30);
        }

        .spark-line-segment.secondary {
          height: 3px;
          background: #f6dc55;
          box-shadow: 0 0 10px rgba(246, 220, 85, 0.30);
        }

        .spark-dot {
          position: absolute;
          width: 11px;
          height: 11px;
          border-radius: 50%;
          background: #35dbe8;
          border: 2px solid #fff;
          transform: translate(-50%, -50%);
          box-sizing: border-box;
          box-shadow: 0 0 0 1px rgba(53, 219, 232, 0.50);
        }

        .spark-dot.secondary {
          width: 9px;
          height: 9px;
          background: #f6dc55;
          box-shadow: 0 0 0 1px rgba(246, 220, 85, 0.50);
        }

        .spark-value-label {
          position: absolute;
          transform: translateX(-50%);
          color: #253141;
          font-size: 10px;
          font-weight: 850;
          white-space: nowrap;
        }

        .spark-x-label {
          position: absolute;
          bottom: 3px;
          transform: translateX(-50%);
          color: #747d89;
          font-size: 10px;
          font-weight: 750;
          white-space: nowrap;
        }

        .spark-bars {
          position: relative;
          height: 124px;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(24px, 1fr));
          align-items: end;
          gap: 8px;
          padding: 8px 8px 22px;
          box-sizing: border-box;
          border-bottom: 2px solid #9aa2ad;
        }

        .spark-bar-item {
          position: relative;
          height: 100%;
          display: flex;
          align-items: end;
          justify-content: center;
        }

        .spark-bar {
          width: 100%;
          max-width: 32px;
          min-height: 8px;
          border-radius: 999px 999px 4px 4px;
          background: linear-gradient(180deg, #d6ff7a 0%, #8fdc39 100%);
          box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.55) inset;
        }

        .spark-bar-label {
          position: absolute;
          left: 50%;
          bottom: -20px;
          transform: translateX(-50%);
          color: #747d89;
          font-size: 10px;
          font-weight: 750;
          white-space: nowrap;
        }

        .sparkline {
          width: 100%;
          height: 128px;
          display: block;
        }

        .spark-axis {
          stroke: #9aa2ad;
          stroke-width: 1.5;
        }

        .spark-area {
          fill: #dff5bf;
          opacity: 0.9;
        }

        .spark-line {
          fill: none;
          stroke: #9bd94d;
          stroke-width: 3;
          stroke-linecap: round;
          stroke-linejoin: round;
        }

        .spark-dots circle {
          fill: #9bd94d;
          stroke: #fff;
          stroke-width: 2;
        }

        .spark-labels text {
          fill: #747d89;
          font-size: 13px;
          font-weight: 750;
        }

        .spark-empty {
          height: 118px;
          border-bottom: 2px solid #a9b0ba;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #8a94a3;
          font-size: 13px;
          font-weight: 800;
        }

        .metric-source {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #111;
          font-size: 13px;
          font-weight: 750;
          line-height: 1.45;
          margin-top: 8px;
          word-break: keep-all;
        }

        .metric-source::before {
          content: "";
          width: 18px;
          height: 18px;
          border: 2px solid #b7bdc6;
          border-radius: 4px;
          transform: rotate(-35deg);
          flex: 0 0 auto;
        }

        .hero-card .metric-category,
        .hero-card h3,
        .hero-card .metric-unit,
        .hero-card .compare-title,
        .hero-card .trend-title,
        .hero-card .metric-source {
          color: #fff;
        }

        .hero-card .metric-category {
          opacity: 0.9;
        }

        .hero-card h3 {
          font-size: clamp(22px, 1.55vw, 28px);
          text-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
        }

        .hero-card .metric-value-wrap strong {
          color: #fff;
          font-size: clamp(40px, 4.2vw, 58px);
          text-shadow: 0 3px 10px rgba(0, 0, 0, 0.18);
        }

        .hero-card .metric-value-wrap.has-detail strong {
          font-size: clamp(30px, 3.2vw, 44px);
        }

        .hero-card .metric-value-detail {
          color: rgba(255, 255, 255, 0.92);
          text-shadow: 0 2px 8px rgba(0, 0, 0, 0.16);
        }

        .hero-card .metric-value-wrap span {
          background: rgba(255, 255, 255, 0.18);
          color: rgba(255, 255, 255, 0.92);
        }

        .hero-card .compare-table {
          border-top-color: rgba(255, 255, 255, 0.24);
          border-bottom-color: rgba(255, 255, 255, 0.24);
          background: rgba(255, 255, 255, 0.08);
          border-radius: 8px;
          overflow: hidden;
        }

        .hero-card .compare-table tr + tr {
          border-top-color: rgba(255, 255, 255, 0.16);
        }

        .hero-card .compare-table th {
          color: rgba(255, 255, 255, 0.72);
        }

        .hero-card .compare-table td {
          color: #fff;
        }

        .hero-card .compare-table tr.positive td {
          color: #8cf0ce;
        }

        .hero-card .compare-table tr.negative td {
          color: #ff9b91;
        }

        .hero-card .spark-axis {
          stroke: rgba(255, 255, 255, 0.58);
        }

        .hero-card .trend-box {
          background: rgba(255, 255, 255, 0.08);
        }

        .hero-card .sparkline-caption {
          color: rgba(255, 255, 255, 0.76);
        }

        .hero-card .spark-line-chart {
          border-bottom-color: rgba(255, 255, 255, 0.52);
        }

        .hero-card .spark-line-segment {
          background: #38e4ee;
          box-shadow: 0 0 14px rgba(56, 228, 238, 0.36);
        }

        .hero-card .spark-line-segment.secondary {
          background: #f6dc55;
          box-shadow: 0 0 14px rgba(246, 220, 85, 0.34);
        }

        .hero-card .spark-dot {
          background: #38e4ee;
          border-color: rgba(255, 255, 255, 0.96);
          box-shadow: 0 0 0 1px rgba(56, 228, 238, 0.45);
        }

        .hero-card .spark-dot.secondary {
          background: #f6dc55;
          box-shadow: 0 0 0 1px rgba(246, 220, 85, 0.48);
        }

        .hero-card .spark-value-label {
          color: rgba(255, 255, 255, 0.92);
        }

        .hero-card .spark-x-label {
          color: rgba(255, 255, 255, 0.72);
        }

        .hero-card .spark-bars {
          border-bottom-color: rgba(255, 255, 255, 0.52);
        }

        .hero-card .spark-bar {
          background: linear-gradient(180deg, #f4ff9c 0%, #aeea4a 100%);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.48) inset,
            0 8px 14px rgba(0, 0, 0, 0.16);
        }

        .hero-card .spark-bar-label {
          color: rgba(255, 255, 255, 0.78);
        }

        .hero-card .spark-area {
          fill: rgba(191, 243, 139, 0.20);
        }

        .hero-card .spark-line {
          stroke: #d4ff72;
          stroke-width: 4;
        }

        .hero-card .spark-dots circle {
          fill: #bff38b;
          stroke: rgba(255, 255, 255, 0.9);
        }

        .hero-card .spark-labels text {
          fill: rgba(255, 255, 255, 0.72);
        }

        .hero-card .spark-empty {
          border-bottom-color: rgba(255, 255, 255, 0.46);
          color: rgba(255, 255, 255, 0.62);
        }

        .hero-card .metric-source {
          opacity: 0.92;
        }

        .hero-card .metric-source::before {
          border-color: rgba(255, 255, 255, 0.72);
        }

        .hero-card .metric-info-button {
          background: rgba(255, 255, 255, 0.22);
          color: #fff;
        }

        .hero-card .metric-info-toggle:checked + .metric-info-button {
          background: rgba(255, 255, 255, 0.34);
          box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.64) inset;
        }

        div[data-testid="stDataFrame"] {
          border: 1px solid var(--line);
          border-radius: 8px;
          overflow: hidden;
        }

        @media (max-width: 900px) {
          div[data-testid="stHorizontalBlock"] {
            width: calc(100% - 32px);
            flex-direction: column;
          }

          div[data-testid="column"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: 1 1 100% !important;
          }

          .top-board-inner {
            min-height: 162px;
            padding: 24px 18px 20px;
            display: block;
          }

          .board-logo {
            min-width: 0;
            margin-bottom: 16px;
            transform: none;
          }

          .board-logo strong {
            display: block;
            font-size: 18px;
            line-height: 1.25;
            white-space: normal;
            word-break: keep-all;
          }

          .board-logo span {
            font-size: 11px;
          }

          .top-nav {
            justify-content: flex-start;
            gap: 10px;
            flex-wrap: wrap;
            overflow-x: visible;
            padding-bottom: 8px;
            transform: none;
          }

          .nav-item {
            font-size: 15px;
          }

          .nav-item.active,
          .nav-item.nav-check {
            min-width: 0;
            min-height: 42px;
            height: auto;
            padding: 8px 16px;
            flex-wrap: wrap;
          }

          .top-tools {
            display: none;
          }

          .status-strip {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }

          .dashboard-summary {
            padding: 16px;
          }

          .project-board {
            padding: 0 16px 28px;
            overflow-x: auto;
          }

          .project-board-head {
            display: block;
            padding-top: 18px;
          }

          .project-board-head h2 {
            font-size: 24px;
          }

          .project-board-head p {
            margin-top: 10px;
            font-size: 13px;
          }

          .project-summary {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
          }

          .project-summary div {
            min-height: 78px;
            padding: 14px;
          }

          .project-summary strong {
            font-size: 19px;
          }

          .project-flow {
            overflow-x: auto;
            padding-bottom: 4px;
          }

          .project-flow span {
            flex: 0 0 auto;
            font-size: 12px;
          }

          .project-grid {
            grid-template-columns: repeat(2, minmax(360px, 1fr));
            gap: 12px;
          }

          .project-card {
            min-height: 0;
            padding: 18px;
          }

          .project-card h3 {
            min-height: 0;
            font-size: 21px;
          }

          .project-meta {
            grid-template-columns: 1fr;
          }

          .section-title {
            display: block;
          }

          .dashboard-grid-head {
            width: calc(100% - 32px);
            display: flex;
            align-items: flex-start;
            flex-direction: column;
            margin-top: 28px;
          }

          .grid-title {
            display: block;
          }

          .grid-title strong {
            display: block;
            font-size: 23px;
            margin-bottom: 4px;
          }

          .section-title p {
            text-align: left;
            margin-top: 4px;
          }

          .section-right {
            justify-content: flex-start;
            align-items: flex-start;
            flex-direction: column;
            margin-top: 10px;
          }

          .d-day-panel {
            min-width: 148px;
            height: 48px;
            padding: 0 14px;
            border-radius: 14px;
          }

          .d-day-text strong {
            font-size: 23px;
          }

          .cards-grid {
            width: calc(100% - 16px);
            grid-template-columns: repeat(3, minmax(360px, 1fr));
            gap: 8px;
          }

          .indicator-card {
            padding: 14px 10px 14px;
            min-height: 390px;
          }

          .metric-category {
            font-size: 11px;
            gap: 4px;
          }

          .category-icon {
            width: 22px;
            height: 22px;
          }

          .category-icon-funding::before {
            left: 4px;
            top: 4px;
            font-size: 9px;
          }

          .category-icon-funding::after {
            right: 4px;
            bottom: 4px;
            transform: scale(0.72);
            transform-origin: right bottom;
          }

          .category-icon-card::before,
          .category-icon-work::before,
          .category-icon-region::before,
          .category-icon-default::before,
          .category-icon-card::after,
          .category-icon-work::after,
          .category-icon-region::after {
            transform: scale(0.72);
            transform-origin: center;
          }

          .category-icon-sentiment::before {
            left: 5px;
            top: 6px;
            width: 12px;
            height: 8px;
          }

          .category-icon-sentiment::after {
            left: 10px;
            top: 13px;
            width: 7px;
            transform: rotate(-36deg);
            transform-origin: left center;
          }

          .metric-info-button {
            width: 20px;
            height: 20px;
            font-size: 12px;
          }

          .metric-info-panel {
            left: 10px;
            right: 10px;
            top: 58px;
            min-height: 120px;
            padding: 18px 34px 18px 18px;
          }

          .metric-info-close {
            top: 8px;
            right: 8px;
            font-size: 22px;
          }

          .metric-info-panel p {
            font-size: 13px;
          }

          .indicator-card h3 {
            min-height: auto;
            font-size: 20px;
          }

          .metric-unit {
            font-size: 11px;
          }

          .metric-value-wrap {
            min-height: 58px;
          }

          .metric-value-wrap strong {
            font-size: 24px;
          }

          .metric-value-wrap span {
            height: 24px;
            padding: 0 10px;
            font-size: 11px;
          }

          .compare-title,
          .trend-title {
            font-size: 11px;
            margin: 8px 0 5px;
          }

          .compare-table th,
          .compare-table td {
            padding: 6px 3px;
            font-size: 9px;
          }

          .trend-box,
          .sparkline-wrap {
            height: 112px;
          }

          .sparkline {
            height: 88px;
          }

          .spark-bars {
            height: 88px;
            gap: 4px;
            padding: 6px 4px 18px;
          }

          .spark-bar {
            max-width: 20px;
          }

          .spark-bar-label {
            bottom: -16px;
            font-size: 7px;
          }

          .sparkline-caption {
            font-size: 9px;
          }

          .spark-empty {
            height: 108px;
            font-size: 10px;
          }

          .metric-source {
            font-size: 9px;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section(title: str, caption: str, countdown_label: str | None = None) -> None:
    if countdown_label:
        right_html = f"""
          <div class="section-right">
            <p>{safe_text(caption)}</p>
            <div class="d-day-panel" title="2026년 7월 1일부터 자동 카운트다운">
              <span class="d-day-hourglass" aria-hidden="true"></span>
              <span class="d-day-text">
                {countdown_html(countdown_label)}
              </span>
            </div>
          </div>
        """
    else:
        right_html = f'<p>{safe_text(caption)}</p>'
    st.markdown(
        f"""
        <div class="section-title notranslate" translate="no" lang="ko">
          <h2>{safe_text(title)}</h2>
          {right_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


inject_css()

catalog_df = load_catalog()
observations_df = load_observations()
credit_df, policy_df = load_manual_tables()
import_runs_df = load_import_runs()
countdown_label, countdown_status = minsaeng_countdown()
current_view = active_view()

st.markdown(
    f"""
    <header class="top-board-header notranslate" translate="no" lang="ko">
      <div class="top-board-inner">
        <div class="board-logo">
          <span>100일의 변화</span>
          <strong>시민과 함께 더 나은 부산으로</strong>
        </div>
        <nav class="top-nav" aria-label="대시보드 메뉴">
          <a class="{nav_class('economy', current_view, 'nav-item nav-economy')}" href="?view=economy" aria-current="{str(current_view == 'economy').lower()}">
            <span class="nav-title">민생100일 경제 상황판</span>
          </a>
          <a class="{nav_class('check', current_view, 'nav-item nav-check')}" href="?view=check" aria-current="{str(current_view == 'check').lower()}">민생100일 비상대책 추진상황</a>
        </nav>
        <div class="top-tools">
          <span class="lang-chip">KR</span>
          <span class="hamburger"><span></span></span>
        </div>
      </div>
    </header>
    """,
    unsafe_allow_html=True,
)

if observations_df.empty:
    st.warning("아직 자동 수집 관측값이 없습니다. `scripts/init_db.py` 실행 후 수집기를 먼저 실행해야 합니다.")

if current_view == "check":
    render_project_dashboard(EMERGENCY_PROJECTS)
else:
    manual_cards = make_manual_cards(credit_df, policy_df)

    card_specs = [
        ("소상공인·전통시장 경기체감", [
            "smallbiz_bsi_actual_busan",
            "smallbiz_bsi_forecast_busan",
            "market_bsi_actual_busan",
            "market_bsi_forecast_busan",
        ]),
        ("소비심리·카드소비", [
            "consumer_sentiment_busan",
            "busan_bigdatawave_card_spend_busan",
            "nowcast_credit_card_spending_busan",
            "nowcast_merchant_card_sales_busan",
        ]),
        ("지역경기", [
            "coincident_index_busan",
        ]),
    ]

    extra_card_specs = [
        ("고용·물가", [
            "employment_rate_busan",
            "unemployment_rate_busan",
            "cpi_busan",
        ]),
    ]

    all_cards: list[Card] = []
    for group_name, indicator_ids in card_specs:
        rows = catalog_df[catalog_df["id"].isin(indicator_ids)]
        all_cards.extend(make_observation_card(observations_df, row, group_name) for _, row in rows.iterrows())
    all_cards.extend(manual_cards)
    all_cards.append(make_dongbaek_card())
    for group_name, indicator_ids in extra_card_specs:
        rows = catalog_df[catalog_df["id"].isin(indicator_ids)]
        all_cards.extend(make_observation_card(observations_df, row, group_name) for _, row in rows.iterrows())

    st.markdown(
        f"""
        <div class="dashboard-grid-head notranslate" translate="no" lang="ko">
          <div class="d-day-panel" title="2026년 7월 1일부터 자동 카운트다운">
            <span class="d-day-hourglass" aria-hidden="true"></span>
            <span class="d-day-text">
              {countdown_html(countdown_label)}
            </span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_card_grid(all_cards, columns=3)
