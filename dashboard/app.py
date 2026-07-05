from __future__ import annotations

import html
import base64
import binascii
import hmac
import hashlib
import json
import math
import os
import secrets
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
CATALOG_PATH = APP_HOME / "config" / "indicators.json"
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))
PROJECT_HEADER_IMAGE_PATH = APP_HOME / "dashboard" / "assets" / "minsaeng100_check_header.png"
MINSAENG_START_DATE = date(2026, 7, 1)
MINSAENG_TOTAL_DAYS = 100
KOREA_TZ = ZoneInfo("Asia/Seoul")


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


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
    with sqlite3.connect(DB_PATH) as conn:
        if not table_exists(conn, "observations") or not table_exists(conn, "indicators"):
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
        credit = (
            pd.read_sql_query(
                "SELECT * FROM manual_credit_guarantee_monthly ORDER BY base_month DESC",
                conn,
            )
            if table_exists(conn, "manual_credit_guarantee_monthly")
            else pd.DataFrame()
        )
        policy = (
            pd.read_sql_query(
                "SELECT * FROM manual_policy_fund_monthly ORDER BY base_month DESC",
                conn,
            )
            if table_exists(conn, "manual_policy_fund_monthly")
            else pd.DataFrame()
        )
    return credit, policy


@st.cache_data(ttl=300)
def load_import_runs() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        if not table_exists(conn, "import_runs"):
            return pd.DataFrame()
        return pd.read_sql_query(
            """
            SELECT source, source_ref, status, rows_written, started_at, finished_at, message
            FROM import_runs
            ORDER BY import_run_id DESC
            LIMIT 10
            """,
            conn,
        )


@st.cache_data(ttl=60)
def load_project_updates() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT
                pu.update_id,
                pu.project_id,
                pu.status,
                pu.progress_pct,
                pu.risk_level,
                pu.budget_status,
                pu.quantitative_results,
                pu.today_result,
                pu.next_plan,
                pu.issue_text,
                pu.public_summary,
                pu.created_at,
                au.username AS input_user,
                au.department AS input_department
            FROM project_updates pu
            LEFT JOIN admin_users au ON au.user_id = pu.created_by
            ORDER BY pu.created_at DESC, pu.update_id DESC
            """,
            conn,
        )


def load_admin_users() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with connect_db() as conn:
        return pd.read_sql_query(
            """
            SELECT user_id, username, role, department, is_active, created_at, updated_at
            FROM admin_users
            ORDER BY user_id
            """,
            conn,
        )


def load_user_permissions() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["user_id", "project_id"])
    with connect_db() as conn:
        return pd.read_sql_query(
            """
            SELECT user_id, project_id
            FROM admin_project_permissions
            ORDER BY user_id, project_id
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
    today_result: str = ""
    issue: str = "입력 전"
    budget_status: str = "추진중"
    risk_level: str = "정상"
    next_plan: str = ""
    updated_at: str = ""
    quantitative_results: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectMetric:
    metric_id: str
    label: str
    unit: str
    target_value: float | None
    target_text: str
    primary: bool = False


EMERGENCY_PROJECTS: list[EmergencyProject] = [
    EmergencyProject(
        "P001",
        1,
        "경영위기 소상공인 1% 저리대출",
        "소상공인 경영개선 지원",
        "경제정책과",
        "1조 2,000억원",
        "부산시 소재 소상공인 최대 1억원 대출보증, 최초 1년간 실부담이자 1.0%",
        "2026.6.~8. 추진계획 수립·MOU 체결·전산 개발, 2026.9. 추경 확보 후 자금지원 공고 및 접수",
    ),
    EmergencyProject(
        "P002",
        2,
        "소상공인 에너지 바우처 지급, 공공요금·지방세 부담 완화",
        "소상공인 경영개선 지원",
        "중소상공인지원과\n경제정책과\n세정운영담당관",
        "560억원",
        "연매출 10억원 이하 소상공인 에너지 바우처 지급, 공공요금 7종 동결 및 지방세 세정지원",
        "2026.6.~ 사업계획 수립·지급시스템 검토, 2026.9. 추경 확보 및 조례 개정, 2026.10.~ 바우처 지급",
    ),
    EmergencyProject(
        "P003",
        3,
        "화물차주·택배 종사자 등 특별 지원",
        "소상공인 경영개선 지원",
        "트라이포트기획과\n일자리노동과",
        "466.35억원",
        "화물차 유가연동보조금 추가 지원, 차량보험료 지원, 배달종사자 산재보험료 지원",
        "2026.6.~7. 관련기관 협의 및 세부계획 수립, 2026.9. 추경 확보 후 홍보·신청접수·지원금 지급",
    ),
    EmergencyProject(
        "P004",
        4,
        "동백전 카드수수료 부담 완화",
        "소상공인 경영개선 지원",
        "중소상공인지원과",
        "14.5억원",
        "동백전 QR 가맹점 집중 확대와 연매출 10억원 이하 가맹점 카드수수료 0.15% 하향",
        "2026.7.~12. QR 가맹점 확대, 2026.7.~8. 시스템 개발, 2026.9. 추경 확보 및 조례 개정, 2026.10.~12. 수수료 감면",
    ),
    EmergencyProject(
        "P005",
        5,
        "동백전 캐시백 15% 한시 상향",
        "시민부담 경감 및 상권활성화",
        "중소상공인지원과",
        "513억원",
        "동백전 캐시백률 5% 상향과 요일·업종별 특화 캐시백 운영",
        "2026.7.~ 국비 지원비율 및 추가지원 건의·하반기 계획 수립, 2026.9. 추경 확보 및 캐시백 정책 발표, 2026.9.~12. 상향 캐시백 적용",
    ),
    EmergencyProject(
        "P006",
        6,
        "소비활력 쿠폰 지급",
        "시민부담 경감 및 상권활성화",
        "중소상공인지원과\n경제정책과",
        "150억원",
        "공공배달서비스 할인쿠폰과 동백전 QR 결제 전용 소비활력 쿠폰 지급",
        "2026.7. 사업계획 수립, 2026.9. 추경 확보 및 조례 개정, 2026.9.~12. 소비활력 쿠폰 지급",
    ),
    EmergencyProject(
        "P007",
        7,
        "1만원 임대료 1,000개 빈 점포 활용 민생상권 회복",
        "시민부담 경감 및 상권활성화",
        "중소상공인지원과",
        "5억원",
        "1~2개 권역 내 빈 점포를 활용해 임차료·인테리어·운영비를 지원하고 민생상권 회복 추진",
        "2026.7. 사업계획 수립·공실점포 DB 구축, 2026.7.~8. 건물주 협약, 2026.9.~11. 시범사업 추진, 2026.12. 성과 발표",
    ),
    EmergencyProject(
        "P008",
        8,
        "공공근로형 민생지킴이 운영, 공공일자리 확대",
        "민생 안전망 구축",
        "일자리노동과\n노인복지과\n장애인복지과",
        "68.3억원",
        "공공근로형 민생지킴이 추가 운영 등 취약계층 공공일자리 30% 이상 확대",
        "2026.7. 수요기관 발굴 및 세부계획 수립, 2026.8.~9. 추경 확보, 2026.9. 사업비 교부 및 참여자 선발, 2026.10.~12. 확대 운영",
    ),
    EmergencyProject(
        "P009",
        9,
        "민생재기 원스톱 100일 프로젝트",
        "민생 안전망 구축",
        "중소상공인지원과",
        "4억원",
        "파산·회생·채무조정 등 상담부터 신청·접수·후속지원까지 원스톱 패스트트랙 구축",
        "2026.7.~ 사업계획 수립·MOU 체결, 2026.7.~10. 이동버스 운영·현장상담·홍보, 2026.11.~12. 심층상담·후속조치",
    ),
    EmergencyProject(
        "P010",
        10,
        "민생금융범죄 특별사법경찰제도 조속 도입",
        "민생 안전망 구축",
        "특별사법경찰과\n(경제정책과)",
        "비예산",
        "불법사금융·불법고금리·불법추심 등 민생경제 범죄 수사체계 구축",
        "2026.7.~ 민생경제수사TF 구성·특사경 지명 및 업무 개시, 2026.9.~ 민생경제수사팀 신설",
    ),
]


PROJECT_STAGE_MAP: dict[str, tuple[str, ...]] = {
    "P001": ("MOU 체결", "전산개발", "추경확보", "공고·접수", "대출공급"),
    "P002": ("시스템 검토", "추경확보", "조례개정", "신청접수", "바우처 지급"),
    "P003": ("기관협의", "세부계획", "추경확보", "신청접수", "지원금 지급"),
    "P004": ("QR 확대", "시스템 개발", "추경확보", "조례개정", "수수료 감면"),
    "P005": ("하반기 계획", "추경확보", "정책발표", "캐시백 적용"),
    "P006": ("사업계획", "추경확보", "조례개정", "쿠폰 발급", "쿠폰 사용"),
    "P007": ("DB 구축", "건물주 협약", "입주자 선정", "점포 조성", "운영"),
    "P008": ("수요기관 발굴", "추경확보", "참여자 선발", "일자리 운영"),
    "P009": ("MOU 체결", "이동상담", "원스톱 서비스", "후속조치"),
    "P010": ("TF 구성", "특사경 지명", "팀 신설", "단속·수사"),
}


PROJECT_NUMBER_MARKS = {
    1: "➊",
    2: "➋",
    3: "➌",
    4: "➍",
    5: "➎",
    6: "➏",
    7: "➐",
    8: "➑",
    9: "➒",
    10: "➓",
}


PROJECT_FIELD_GROUPS = {
    "P001": "소상공인 경영개선 지원",
    "P002": "소상공인 경영개선 지원",
    "P003": "소상공인 경영개선 지원",
    "P004": "소상공인 경영개선 지원",
    "P005": "시민부담 경감",
    "P006": "시민부담 경감",
    "P007": "시민부담 경감",
    "P008": "민생안전망 구축",
    "P009": "민생안전망 구축",
    "P010": "민생안전망 구축",
}


PROJECT_FIELD_CLASSES = {
    "소상공인 경영개선 지원": "field-smallbiz",
    "시민부담 경감": "field-burden",
    "민생안전망 구축": "field-safety",
}


DISPLAY_PROJECT_TITLES = {
    "P001": "소상공인 1% 저리대출",
    "P002": "소상공인 에너지바우처 지급",
    "P003": "영세 화물차주·택배종사자 특별지원",
    "P004": "동백전 카드수수료 부담완화",
    "P005": "동백전 캐시백 15% 한시상향",
    "P006": "소비활력 쿠폰지급",
    "P007": "만원 임대료 1,000개 빈점포 활용 민생상권 회복",
    "P008": "공공근로형 민생지킴이 운영, 공공일자리 확대",
    "P009": "민생재기 원스톱 100일 프로젝트",
    "P010": "특별사법경찰제도 조속 도입",
}


DISPLAY_METRIC_GROUPS = {
    "P003": (
        ("유가연동보조금(유가보조금 포함) 지급액", ("fuel_subsidy_amount",), "400억원", "만원"),
        (
            "차량보험료 지원대수",
            ("truck_insurance_vehicles_triport", "truck_insurance_vehicles_jobs"),
            "30,000대",
            "대",
            30_000,
        ),
    ),
    "P006": (
        ("공공배달 쿠폰 지급액", ("delivery_coupon_amount",), "60억원", "만원"),
        ("동백전 QR결제 쿠폰/비중", ("qr_coupon_amount", "qr_payment_share"), "20억원 / 14%", "만원, %"),
    ),
}


PROJECT_METRIC_MAP: dict[str, tuple[ProjectMetric, ...]] = {
    "P001": (
        ProjectMetric("loan_amount", "대출실행금액", "만원", 120_000_000, "1조 2,000억원", True),
        ProjectMetric("beneficiary_count", "지원 소상공인 수", "명", 40_000, "40,000명"),
    ),
    "P002": (
        ProjectMetric("voucher_amount", "바우처 지급액", "만원", 5_600_000, "560억원", True),
        ProjectMetric("voucher_places", "바우처 지급 개소", "개소", 280_000, "28만개소"),
    ),
    "P003": (
        ProjectMetric("fuel_subsidy_amount", "유가연동보조금(유가보조금 포함) 지급액", "만원", 4_000_000, "400억원", True),
        ProjectMetric(
            "truck_insurance_vehicles_triport",
            "차량보험료 지원대수(트라이포트기획과)",
            "대",
            None,
            "부서별 확인 필요",
        ),
        ProjectMetric(
            "truck_insurance_vehicles_jobs",
            "차량보험료 지원대수(일자리노동과)",
            "대",
            None,
            "부서별 확인 필요",
        ),
        ProjectMetric("accident_insurance_amount", "플랫폼 노동자 산재보험료 지원액", "만원", 80_000, "8억원"),
        ProjectMetric("accident_insurance_people", "플랫폼 노동자 산재보험료 지원 인원", "명", 4_000, "4,000명"),
    ),
    "P004": (
        ProjectMetric("qr_merchant_increase", "QR 등록 가맹점 증가 수", "개소", 4_000, "+4,000개소", True),
        ProjectMetric("fee_reduction_amount", "카드결제 수수료 감면액", "만원", 125_000, "12.5억원"),
        ProjectMetric("fee_reduction_merchants", "수수료 감면 적용 가맹점 수", "개소", 140_000, "14만개소"),
    ),
    "P005": (
        ProjectMetric("dongbaek_issue_amount", "동백전 발행액", "만원", 200_000_000, "2조원", True),
        ProjectMetric("cashback_amount", "상향 캐시백 집행액", "만원", 5_130_000, "513억원"),
        ProjectMetric("cashback_users", "캐시백 적용 이용자 수", "명", None, "부서 목표 입력"),
    ),
    "P006": (
        ProjectMetric("delivery_coupon_amount", "공공배달 쿠폰 지급액", "만원", 600_000, "60억원", True),
        ProjectMetric("qr_payment_share", "동백전 월간 QR결제 비중", "%", 14, "14%"),
        ProjectMetric("qr_coupon_amount", "QR 결제 쿠폰 지급액", "만원", 200_000, "20억원"),
        ProjectMetric("coupon_used_count", "쿠폰 사용 건수", "건", None, "부서 목표 입력"),
    ),
    "P007": (
        ProjectMetric("vacant_store_count", "빈점포 입점 완료 개소", "개소", 50, "50개소", True),
        ProjectMetric("vacant_store_setup_count", "빈점포 조성 개소", "개소", 50, "50개소"),
    ),
    "P008": (
        ProjectMetric("guardian_people", "민생지킴이 투입 인원", "명", 500, "500명", True),
        ProjectMetric("public_job_people", "공공일자리 투입 인원", "명", 4_850, "4,850명"),
    ),
    "P009": (
        ProjectMetric("support_cases", "원스톱서비스 지원건수", "건", 200, "200건", True),
        ProjectMetric("application_cost_cases", "비용 지원건수", "건", 100, "100건"),
    ),
    "P010": (
        ProjectMetric("tf_staff_count", "1단계 TF 구성 인원", "명", 2, "2명(7월~)", True),
        ProjectMetric("formal_team_staff_count", "2단계 민생경제수사팀 신설 인원", "명", 6, "총 6명(9~10월)"),
    ),
}


METRIC_VALUE_ALIASES: dict[str, tuple[str, ...]] = {
    "truck_insurance_vehicles_triport": ("truck_insurance_vehicles",),
}


PROJECT_STATUS_OPTIONS = ["계획중", "예산편성중", "추진중", "완료"]
BUDGET_STATUS_OPTIONS = ["추진완료", "추진중", "중단"]
DEFAULT_BUDGET_STATUS = "추진중"
RISK_LEVEL_OPTIONS = ["정상", "주의", "지연"]
ADMIN_ROLES = {
    "admin": "관리자",
    "department": "부서 담당자",
    "viewer": "조회자",
}
PASSWORD_ITERATIONS = 260_000


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return (
        "pbkdf2_sha256$"
        f"{PASSWORD_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(digest_text)
    except (ValueError, TypeError, binascii.Error):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(digest, expected)


def ensure_admin_schema() -> None:
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'department', 'viewer')),
                department TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admin_project_permissions (
                user_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id, project_id),
                FOREIGN KEY(user_id) REFERENCES admin_users(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_updates (
                update_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_pct REAL NOT NULL,
                risk_level TEXT NOT NULL,
                budget_status TEXT NOT NULL,
                quantitative_results TEXT,
                today_result TEXT,
                next_plan TEXT,
                issue_text TEXT,
                public_summary TEXT,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by) REFERENCES admin_users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_project_updates_latest
            ON project_updates(project_id, created_at DESC, update_id DESC);
            """
        )
        project_update_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_updates)").fetchall()
        }
        if "quantitative_results" not in project_update_columns:
            conn.execute("ALTER TABLE project_updates ADD COLUMN quantitative_results TEXT")
        user_count = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        initial_password = os.getenv("MINSAENG_ADMIN_PASSWORD", "").strip()
        if user_count == 0 and initial_password:
            conn.execute(
                """
                INSERT INTO admin_users (
                    username, password_hash, role, department, is_active, created_at, updated_at
                )
                VALUES (?, ?, 'admin', '총괄', 1, ?, ?)
                """,
                (
                    os.getenv("MINSAENG_ADMIN_USER", "admin").strip() or "admin",
                    hash_password(initial_password),
                    current_kst_timestamp(),
                    current_kst_timestamp(),
                ),
            )


def current_kst_timestamp() -> str:
    return datetime.now(KOREA_TZ).strftime("%Y-%m-%d %H:%M:%S")


def safe_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


@st.cache_data(ttl=3600)
def image_data_uri(path_text: str) -> str:
    path = Path(path_text)
    if not path.exists():
        return ""
    mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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
    today = today or datetime.now(KOREA_TZ).date()
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
                title="부산 소상공인 특별자금 월별 공급액",
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
                title="부산 소상공인 특별자금 월별 공급액",
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


def render_metric_carousel(cards: list[Card], interval_seconds: int = 10) -> None:
    if not cards:
        return
    items = []
    for card in cards:
        icon_type, _ = category_icon(card.group)
        items.append(
            {
                "group": str(card.group),
                "title": str(card.title),
                "value": str(card.value),
                "unit": str(card.unit),
                "period": str(card.period),
                "theme": icon_type,
            }
        )
    items_json = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    components.html(
        f"""
        <!doctype html>
        <html lang="ko">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <style>
            :root {{
              --font-kr: "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
            }}
            * {{ box-sizing: border-box; }}
            body {{
              margin: 0;
              background: transparent;
              font-family: var(--font-kr);
              overflow: hidden;
            }}
            .economy-carousel {{
              width: 100%;
              max-width: 1680px;
              margin: 0 auto;
              padding: 0 36px;
            }}
            .eco-carousel-stage {{
              position: relative;
              height: 300px;
              overflow: hidden;
              border-radius: 22px;
              background:
                radial-gradient(circle at 50% 58%, rgba(47, 113, 199, 0.16), transparent 28%),
                linear-gradient(180deg, #f5f8fc 0%, #eef3f8 100%);
              box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.78);
            }}
            .eco-carousel-track {{
              position: absolute;
              inset: 0;
              overflow: hidden;
            }}
            .eco-carousel-card {{
              position: absolute;
              left: 50%;
              top: 50%;
              width: 370px;
              min-height: 182px;
              padding: 24px 26px;
              border-radius: 18px;
              background: #fff;
              border: 1px solid rgba(210, 219, 230, 0.86);
              box-shadow: 0 18px 42px rgba(31, 45, 71, 0.1);
              text-align: center;
              opacity: 0;
              pointer-events: none;
              will-change: transform, opacity, filter;
              transition:
                transform 620ms cubic-bezier(0.22, 1, 0.36, 1),
                opacity 420ms ease,
                filter 420ms ease,
                box-shadow 420ms ease;
            }}
            .eco-carousel-card[data-slot="1"] {{
              width: min(560px, calc(100% - 260px));
              min-height: 232px;
              padding: 30px 36px;
              border-radius: 20px;
              box-shadow: 0 24px 58px rgba(31, 45, 71, 0.18);
              opacity: 1;
              pointer-events: auto;
              transform: translate(-50%, -50%) translateX(0) scale(1);
              z-index: 4;
            }}
            .eco-carousel-card[data-slot="0"],
            .eco-carousel-card[data-slot="2"] {{
              opacity: 0.72;
              filter: saturate(0.86);
              z-index: 2;
            }}
            .eco-carousel-card[data-slot="0"] {{
              transform: translate(-50%, -50%) translateX(-520px) scale(0.88);
            }}
            .eco-carousel-card[data-slot="2"] {{
              transform: translate(-50%, -50%) translateX(520px) scale(0.88);
            }}
            .eco-carousel-card[data-slot="far-left"] {{
              opacity: 0;
              transform: translate(-50%, -50%) translateX(-860px) scale(0.78);
              z-index: 1;
            }}
            .eco-carousel-card[data-slot="far-right"] {{
              opacity: 0;
              transform: translate(-50%, -50%) translateX(860px) scale(0.78);
              z-index: 1;
            }}
            .eco-carousel-category {{
              display: inline-flex;
              align-items: center;
              justify-content: center;
              gap: 7px;
              min-width: 0;
              margin-bottom: 10px;
              color: #687889;
              font-size: 14px;
              font-weight: 900;
              line-height: 1.2;
              word-break: keep-all;
            }}
            .eco-carousel-card[data-slot="1"] .eco-carousel-category {{
              font-size: 16px;
            }}
            .category-icon {{
              position: relative;
              width: 30px;
              height: 30px;
              border-radius: 50%;
              color: #fff;
              display: inline-flex;
              align-items: center;
              justify-content: center;
              flex: 0 0 auto;
              box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.14);
            }}
            .category-icon::before,
            .category-icon::after {{
              content: "";
              position: absolute;
              box-sizing: border-box;
            }}
            .category-icon-funding {{ background: #d84d7f; }}
            .category-icon-funding::before {{
              content: "₩";
              left: 5px;
              top: 6px;
              color: #fff;
              font-size: 12px;
              font-weight: 900;
              line-height: 1;
            }}
            .category-icon-funding::after {{
              right: 5px;
              bottom: 6px;
              width: 9px;
              height: 9px;
              background:
                linear-gradient(#fff, #fff) 0 5px / 2px 4px no-repeat,
                linear-gradient(#fff, #fff) 4px 2px / 2px 7px no-repeat,
                linear-gradient(#fff, #fff) 8px 0 / 2px 9px no-repeat;
            }}
            .category-icon-sentiment {{
              background:
                radial-gradient(circle at 50% 67%, #fff 0 2px, transparent 2.5px),
                #57b861;
            }}
            .category-icon-sentiment::before {{
              left: 7px;
              top: 8px;
              width: 16px;
              height: 10px;
              border: 2px solid #fff;
              border-bottom: 0;
              border-radius: 16px 16px 0 0;
            }}
            .category-icon-sentiment::after {{
              left: 14px;
              top: 17px;
              width: 9px;
              height: 2px;
              border-radius: 999px;
              background: #fff;
              transform: rotate(-36deg);
              transform-origin: left center;
            }}
            .category-icon-card {{ background: #397dd1; }}
            .category-icon-card::before {{
              left: 6px;
              top: 8px;
              width: 18px;
              height: 13px;
              border: 2px solid #fff;
              border-radius: 3px;
            }}
            .category-icon-card::after {{
              left: 8px;
              top: 12px;
              width: 14px;
              height: 2px;
              background: #fff;
            }}
            .category-icon-work {{ background: #d46a38; }}
            .category-icon-work::before {{
              left: 6px;
              top: 10px;
              width: 18px;
              height: 12px;
              border: 2px solid #fff;
              border-radius: 3px;
            }}
            .category-icon-work::after {{
              left: 11px;
              top: 7px;
              width: 8px;
              height: 5px;
              border: 2px solid #fff;
              border-bottom: 0;
              border-radius: 3px 3px 0 0;
            }}
            .category-icon-region {{ background: #6667c8; }}
            .category-icon-region::before {{
              left: 7px;
              top: 8px;
              width: 16px;
              height: 12px;
              border-left: 2px solid #fff;
              border-bottom: 2px solid #fff;
            }}
            .category-icon-region::after {{
              right: 6px;
              top: 7px;
              width: 7px;
              height: 7px;
              border-right: 2px solid #fff;
              border-top: 2px solid #fff;
              transform: rotate(45deg);
            }}
            .category-icon-default {{ background: #657386; }}
            .category-icon-default::before {{
              width: 12px;
              height: 12px;
              border: 2px solid #fff;
              border-radius: 50%;
            }}
            .eco-carousel-card h3 {{
              min-height: 42px;
              margin: 0 0 12px;
              color: #222b35;
              font-size: 24px;
              font-weight: 900;
              line-height: 1.22;
              letter-spacing: 0;
              word-break: keep-all;
            }}
            .eco-carousel-card[data-slot="1"] h3 {{
              min-height: 52px;
              font-size: 34px;
            }}
            .eco-carousel-value {{
              display: flex;
              align-items: baseline;
              justify-content: center;
              gap: 9px;
              margin-bottom: 10px;
              color: #2f7fe8;
            }}
            .eco-carousel-value strong {{
              color: #2f7fe8;
              font-size: 44px;
              font-weight: 900;
              line-height: 1;
              letter-spacing: 0;
              white-space: nowrap;
            }}
            .eco-carousel-card[data-slot="1"] .eco-carousel-value strong {{
              font-size: 62px;
            }}
            .eco-carousel-value em {{
              color: #77889b;
              font-size: 17px;
              font-style: normal;
              font-weight: 900;
              white-space: nowrap;
            }}
            .eco-carousel-value-combo {{
              display: inline-flex;
              align-items: baseline;
              gap: 3px;
            }}
            .eco-carousel-value-combo b {{
              color: inherit;
              font-size: inherit;
              font-weight: inherit;
              line-height: inherit;
            }}
            .eco-carousel-value-combo small {{
              color: inherit;
              font-size: 0.56em;
              font-weight: inherit;
              line-height: 1;
              white-space: nowrap;
            }}
            .eco-carousel-period {{
              display: inline-flex;
              align-items: center;
              justify-content: center;
              min-height: 30px;
              padding: 0 16px;
              border-radius: 999px;
              background: #eef2f7;
              color: #6b7c8f;
              font-size: 16px;
              font-weight: 900;
              line-height: 1;
            }}
            .eco-carousel-card[data-slot="1"] .eco-carousel-period {{
              min-height: 36px;
              padding: 0 20px;
              font-size: 20px;
            }}
            .eco-carousel-count {{
              position: absolute;
              right: 72px;
              bottom: 26px;
              color: #3e7ae4;
              font-size: 18px;
              font-weight: 900;
            }}
            .eco-carousel-arrow {{
              position: absolute;
              top: 50%;
              z-index: 8;
              width: 58px;
              height: 78px;
              border: 0;
              background: transparent;
              cursor: pointer;
            }}
            .eco-carousel-arrow::before {{
              content: "";
              position: absolute;
              top: 15px;
              width: 46px;
              height: 46px;
              border-top: 3px solid #1aa2ff;
              border-left: 3px solid #1aa2ff;
            }}
            .eco-carousel-arrow.left {{
              left: 26px;
              transform: translateY(-50%);
            }}
            .eco-carousel-arrow.left::before {{
              left: 9px;
              transform: rotate(-45deg);
            }}
            .eco-carousel-arrow.right {{
              right: 26px;
              transform: translateY(-50%);
            }}
            .eco-carousel-arrow.right::before {{
              right: 9px;
              transform: rotate(135deg);
            }}
            .eco-carousel-arrow:hover::before {{
              border-color: #0077dd;
            }}
            @media (max-width: 900px) {{
              .economy-carousel {{
                padding: 0 16px;
              }}
              .eco-carousel-stage {{
                height: 248px;
                border-radius: 16px;
              }}
              .eco-carousel-track {{
                overflow: hidden;
              }}
              .eco-carousel-card {{
                width: 260px;
              }}
              .eco-carousel-card[data-slot="0"] {{
                transform: translate(-50%, -50%) translateX(-320px) scale(0.82);
              }}
              .eco-carousel-card[data-slot="2"] {{
                transform: translate(-50%, -50%) translateX(320px) scale(0.82);
              }}
              .eco-carousel-card[data-slot="far-left"] {{
                transform: translate(-50%, -50%) translateX(-520px) scale(0.72);
              }}
              .eco-carousel-card[data-slot="far-right"] {{
                transform: translate(-50%, -50%) translateX(520px) scale(0.72);
              }}
              .eco-carousel-card[data-slot="1"] {{
                width: min(380px, calc(100% - 104px));
                min-height: 196px;
                padding: 24px 20px;
              }}
              .eco-carousel-card[data-slot="1"] h3 {{
                min-height: 42px;
                font-size: 25px;
              }}
              .eco-carousel-card[data-slot="1"] .eco-carousel-value strong {{
                font-size: 44px;
              }}
              .eco-carousel-value em {{
                font-size: 14px;
              }}
              .eco-carousel-card[data-slot="1"] .eco-carousel-period {{
                min-height: 30px;
                font-size: 16px;
              }}
              .eco-carousel-count {{
                right: 18px;
                bottom: 14px;
                font-size: 14px;
              }}
              .eco-carousel-arrow {{
                width: 42px;
                height: 58px;
              }}
              .eco-carousel-arrow::before {{
                top: 14px;
                width: 30px;
                height: 30px;
              }}
              .eco-carousel-arrow.left {{
                left: 10px;
              }}
              .eco-carousel-arrow.right {{
                right: 10px;
              }}
            }}
          </style>
        </head>
        <body>
          <section class="economy-carousel" aria-label="economy indicator carousel">
            <div class="eco-carousel-stage">
              <button class="eco-carousel-arrow left" type="button" aria-label="previous indicator"></button>
              <div class="eco-carousel-track" id="carouselTrack"></div>
              <button class="eco-carousel-arrow right" type="button" aria-label="next indicator"></button>
              <div class="eco-carousel-count" id="carouselCount"></div>
            </div>
          </section>
          <script>
            const items = {items_json};
            const intervalMs = {interval_seconds * 1000};
            const transitionMs = 680;
            const track = document.getElementById("carouselTrack");
            const count = document.getElementById("carouselCount");
            const prevButton = document.querySelector(".eco-carousel-arrow.left");
            const nextButton = document.querySelector(".eco-carousel-arrow.right");
            let currentIndex = 0;
            let timer = null;
            let animating = false;

            function normalizeIndex(index) {{
              return (index + items.length) % items.length;
            }}

            function buildValue(value) {{
              const wrap = document.createElement("div");
              wrap.className = "eco-carousel-value";
              const valueText = String(value || "");
              if (valueText.includes("(") && valueText.endsWith(")")) {{
                const openIndex = valueText.indexOf("(");
                const main = valueText.slice(0, openIndex);
                const suffix = valueText.slice(openIndex);
                const strong = document.createElement("strong");
                strong.className = "eco-carousel-value-combo";
                const mainNode = document.createElement("b");
                mainNode.textContent = main;
                const suffixNode = document.createElement("small");
                suffixNode.textContent = suffix;
                strong.append(mainNode, suffixNode);
                wrap.append(strong);
              }} else {{
                const strong = document.createElement("strong");
                strong.textContent = valueText;
                wrap.append(strong);
              }}
              return wrap;
            }}

            function buildCard(item, slot) {{
              const article = document.createElement("article");
              article.className = `eco-carousel-card card-theme-${{item.theme || "default"}}`;
              article.dataset.slot = String(slot);

              const category = document.createElement("div");
              category.className = "eco-carousel-category";
              const icon = document.createElement("span");
              icon.className = `category-icon category-icon-${{item.theme || "default"}}`;
              icon.setAttribute("aria-hidden", "true");
              const group = document.createElement("span");
              group.textContent = item.group || "";
              category.append(icon, group);

              const title = document.createElement("h3");
              title.textContent = item.title || "";

              const value = buildValue(item.value);
              const unit = document.createElement("em");
              unit.textContent = item.unit || "";
              value.append(unit);

              const period = document.createElement("span");
              period.className = "eco-carousel-period";
              period.textContent = item.period || "";

              article.append(category, title, value, period);
              return article;
            }}

            function updateCount(index = currentIndex) {{
              count.textContent = `${{index + 1}}/${{items.length}}`;
            }}

            function getSlot(slot) {{
              return track.querySelector(`.eco-carousel-card[data-slot="${{slot}}"]`);
            }}

            function renderInitial() {{
              track.replaceChildren(
                buildCard(items[normalizeIndex(currentIndex - 1)], "0"),
                buildCard(items[currentIndex], "1"),
                buildCard(items[normalizeIndex(currentIndex + 1)], "2")
              );
              updateCount();
            }}

            function settle(nextIndex) {{
              currentIndex = nextIndex;
              track.replaceChildren(
                buildCard(items[normalizeIndex(currentIndex - 1)], "0"),
                buildCard(items[currentIndex], "1"),
                buildCard(items[normalizeIndex(currentIndex + 1)], "2")
              );
              updateCount();
              animating = false;
            }}

            function go(delta) {{
              if (animating || items.length < 2) return;
              animating = true;
              const nextIndex = normalizeIndex(currentIndex + delta);
              const left = getSlot("0");
              const center = getSlot("1");
              const right = getSlot("2");

              if (delta > 0) {{
                const incoming = buildCard(items[normalizeIndex(currentIndex + 2)], "far-right");
                track.append(incoming);
                window.requestAnimationFrame(() => {{
                  left.dataset.slot = "far-left";
                  center.dataset.slot = "0";
                  right.dataset.slot = "1";
                  incoming.dataset.slot = "2";
                  updateCount(nextIndex);
                }});
              }} else {{
                const incoming = buildCard(items[normalizeIndex(currentIndex - 2)], "far-left");
                track.prepend(incoming);
                window.requestAnimationFrame(() => {{
                  incoming.dataset.slot = "0";
                  left.dataset.slot = "1";
                  center.dataset.slot = "2";
                  right.dataset.slot = "far-right";
                  updateCount(nextIndex);
                }});
              }}

              window.setTimeout(() => settle(nextIndex), transitionMs);
              restart();
            }}

            function restart() {{
              if (timer) window.clearInterval(timer);
              timer = window.setInterval(() => {{
                go(1);
              }}, intervalMs);
            }}

            prevButton.addEventListener("click", () => go(-1));
            nextButton.addEventListener("click", () => go(1));
            renderInitial();
            restart();
          </script>
        </body>
        </html>
        """,
        height=324,
        scrolling=False,
    )


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
    return raw_view if raw_view in {"economy", "check", "check_display", "admin"} else "economy"


def active_project_layout() -> str:
    raw_layout = st.query_params.get("layout", "compact")
    if isinstance(raw_layout, list):
        raw_layout = raw_layout[0] if raw_layout else "compact"
    return raw_layout if raw_layout in {"detail", "compact"} else "compact"


def nav_class(view: str, current_view: str, base_class: str) -> str:
    classes = [base_class]
    if view == current_view:
        classes.append("active")
    return " ".join(classes)


def project_title_map(projects: list[EmergencyProject]) -> dict[str, str]:
    return {project.project_id: f"{project.number:02d}. {project.title}" for project in projects}


def compact_text(value: Any, limit: int = 72) -> str:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def latest_project_update_map(updates: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if updates.empty:
        return {}
    rows = updates.sort_values(["created_at", "update_id"], ascending=[False, False])
    latest = rows.drop_duplicates("project_id", keep="first")
    return {str(row["project_id"]): row.to_dict() for _, row in latest.iterrows()}


def project_stages(project_id: str) -> tuple[str, ...]:
    return PROJECT_STAGE_MAP.get(project_id, tuple(PROJECT_STATUS_OPTIONS))


def normalize_budget_status(value: Any) -> str:
    status = "" if value is None or pd.isna(value) else str(value).strip()
    return status if status in BUDGET_STATUS_OPTIONS else DEFAULT_BUDGET_STATUS


def normalize_risk_level(value: Any) -> str:
    risk_level = "" if value is None or pd.isna(value) else str(value).strip()
    return risk_level if risk_level in RISK_LEVEL_OPTIONS else "정상"


def stage_progress_pct(project_id: str, status: str) -> int:
    stages = project_stages(project_id)
    if not stages or status not in stages:
        return 0
    return int(round(((stages.index(status) + 1) / len(stages)) * 100))


def project_metrics(project_id: str) -> tuple[ProjectMetric, ...]:
    return PROJECT_METRIC_MAP.get(project_id, ())


def parse_quantitative_results(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        raw = value
    elif value is None:
        return {}
    elif isinstance(value, str) and value.strip() == "":
        return {}
    else:
        try:
            if bool(pd.isna(value)):
                return {}
        except (TypeError, ValueError):
            pass
        try:
            raw = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return {}
    results: dict[str, float] = {}
    for key, raw_value in raw.items():
        try:
            number = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            results[str(key)] = max(number, 0.0)
    return results


def quantitative_value(results: dict[str, float], metric_id: str) -> float | None:
    value = results.get(metric_id)
    if value is not None:
        return value
    for alias in METRIC_VALUE_ALIASES.get(metric_id, ()):
        value = results.get(alias)
        if value is not None:
            return value
    return None


def metric_current(project: EmergencyProject, metric: ProjectMetric) -> float | None:
    value = quantitative_value(project.quantitative_results, metric.metric_id)
    if value is None:
        return None
    return float(value)


def metric_pct(current: float | None, target: float | None) -> float | None:
    if current is None or target is None or target <= 0:
        return None
    return max(0.0, min((current / target) * 100, 100.0))


def metric_id_pct(project: EmergencyProject, metric_id: str) -> float | None:
    metric = next(
        (candidate for candidate in project_metrics(project.project_id) if candidate.metric_id == metric_id),
        None,
    )
    if metric is None or metric.target_value is None or metric.target_value <= 0:
        return None
    current = metric_current(project, metric)
    current_value = 0.0 if current is None else current
    return metric_pct(current_value, metric.target_value)


def metric_sum_pct(project: EmergencyProject, metric_ids: tuple[str, ...]) -> float | None:
    metric_map = {metric.metric_id: metric for metric in project_metrics(project.project_id)}
    current_total = 0.0
    target_total = 0.0
    units: set[str] = set()
    for metric_id in metric_ids:
        metric = metric_map.get(metric_id)
        if metric is None or metric.target_value is None or metric.target_value <= 0:
            continue
        current_total += metric_current(project, metric) or 0.0
        target_total += metric.target_value
        units.add(metric.unit)
    if target_total <= 0 or len(units) != 1:
        return None
    return metric_pct(current_total, target_total)


def metric_group_sum_pct(
    project: EmergencyProject, metric_ids: tuple[str, ...], target_value: float | None
) -> float | None:
    if target_value is None or target_value <= 0:
        return None
    metric_map = {metric.metric_id: metric for metric in project_metrics(project.project_id)}
    current_total = 0.0
    units: set[str] = set()
    has_metric = False
    for metric_id in metric_ids:
        metric = metric_map.get(metric_id)
        if metric is None:
            continue
        has_metric = True
        current_total += metric_current(project, metric) or 0.0
        units.add(metric.unit)
    if not has_metric or len(units) != 1:
        return None
    return metric_pct(current_total, target_value)


def metric_group_pct(
    project: EmergencyProject, metric_ids: tuple[str, ...], target_value: float | None = None
) -> float | None:
    summed_pct = metric_group_sum_pct(project, metric_ids, target_value)
    if summed_pct is not None:
        return summed_pct
    summed_pct = metric_sum_pct(project, metric_ids)
    if summed_pct is not None:
        return summed_pct
    pcts = [
        pct
        for metric_id in metric_ids
        if (pct := metric_id_pct(project, metric_id)) is not None
    ]
    if not pcts:
        return None
    return sum(pcts) / len(pcts)


def display_metric_specs(project_id: str) -> list[tuple[str, tuple[str, ...], str, str, float | None]]:
    grouped = DISPLAY_METRIC_GROUPS.get(project_id)
    if grouped:
        specs: list[tuple[str, tuple[str, ...], str, str, float | None]] = []
        for group in grouped:
            label, metric_ids, target_text, unit_text, *rest = group
            target_value = float(rest[0]) if rest and rest[0] is not None else None
            specs.append((label, tuple(metric_ids), target_text, unit_text, target_value))
        return specs
    return [
        (metric.label, (metric.metric_id,), metric.target_text, metric.unit, None)
        for metric in list(project_metrics(project_id))[:2]
    ]


def display_achievement_pct(project: EmergencyProject) -> float:
    specs = display_metric_specs(project.project_id)
    metric_ids = tuple(
        metric_id
        for _label, spec_metric_ids, _target_text, _unit_text, _target_value in specs
        for metric_id in spec_metric_ids
    )
    has_custom_target = any(target_value is not None for *_unused, target_value in specs)
    if not has_custom_target:
        summed_pct = metric_sum_pct(project, metric_ids)
        if summed_pct is not None:
            return summed_pct
    group_pcts = [
        pct
        for _label, spec_metric_ids, _target_text, _unit_text, target_value in specs
        if (pct := metric_group_pct(project, spec_metric_ids, target_value)) is not None
    ]
    if not group_pcts:
        return 0.0
    return max(0.0, min(sum(group_pcts) / len(group_pcts), 100.0))


def format_metric_value(value: float | None, unit: str, compact: bool = False) -> str:
    if value is None:
        return "입력 대기"
    if unit == "만원":
        if value >= 100_000_000:
            trillion = int(value // 100_000_000)
            billion_krw = round((value % 100_000_000) / 10_000, 1)
            if billion_krw:
                return f"{trillion}조 {billion_krw:,.1f}억원"
            return f"{trillion}조원"
        if value >= 10_000:
            billion_krw = value / 10_000
            return f"{billion_krw:,.1f}억원" if billion_krw % 1 else f"{int(billion_krw):,}억원"
        return f"{value:,.0f}만원"
    suffix = unit
    if compact and value >= 10_000:
        return f"{value / 10_000:,.1f}만{suffix}"
    return f"{value:,.0f}{suffix}"


def primary_metric(project: EmergencyProject) -> ProjectMetric | None:
    metrics = project_metrics(project.project_id)
    for metric in metrics:
        if metric.primary:
            return metric
    return metrics[0] if metrics else None


def metric_rows_html(project: EmergencyProject) -> str:
    rows = []
    for metric in project_metrics(project.project_id):
        current = metric_current(project, metric)
        pct = metric_pct(current, metric.target_value)
        pct_text = f"{pct:.1f}%" if pct is not None else "목표 미설정"
        current_text = format_metric_value(current, metric.unit, compact=True)
        rows.append(
            f"""
            <div class="metric-row">
              <span>{safe_text(metric.label)}</span>
              <strong>{safe_text(current_text)}</strong>
              <em>목표 {safe_text(metric.target_text)}</em>
              <b>{safe_text(pct_text)}</b>
            </div>
            """
        )
    return "\n".join(rows)


def metric_panel_html(project: EmergencyProject) -> str:
    metric = primary_metric(project)
    if metric is None:
        return ""
    current = metric_current(project, metric)
    pct = metric_pct(current, metric.target_value)
    bar_pct = 0 if pct is None else pct
    pct_text = f"{pct:.1f}%" if pct is not None else "목표 미설정"
    current_text = format_metric_value(current, metric.unit)
    waiting_class = " is-waiting" if current is None else ""
    return f"""
      <section class="project-metric-panel">
        <div class="project-metric-main">
          <span>현재 실적</span>
          <strong class="{waiting_class}">{safe_text(current_text)}</strong>
          <em>{safe_text(metric.label)}</em>
        </div>
        <div class="project-metric-target">
          <span>정량 목표</span>
          <strong>{safe_text(metric.target_text)}</strong>
          <em>{safe_text(pct_text)}</em>
        </div>
        <div class="project-progress-line" style="--pct:{bar_pct:.3f};">
          <span></span>
        </div>
        <div class="project-metric-rows">
          {metric_rows_html(project)}
        </div>
      </section>
    """


def apply_project_updates(
    projects: list[EmergencyProject],
    updates: pd.DataFrame,
) -> list[EmergencyProject]:
    latest_map = latest_project_update_map(updates)
    merged: list[EmergencyProject] = []
    for project in projects:
        latest = latest_map.get(project.project_id)
        if not latest:
            merged.append(project)
            continue
        latest_summary = (
            compact_text(latest.get("public_summary"))
            or compact_text(latest.get("today_result"))
            or "부서 입력 완료"
        )
        latest_status = str(latest.get("status") or project.status)
        latest_budget_status = normalize_budget_status(
            latest.get("budget_status") or project.budget_status
        )
        latest_risk_level = normalize_risk_level(latest.get("risk_level") or project.risk_level)
        merged.append(
            replace(
                project,
                status=latest_status,
                progress_pct=stage_progress_pct(project.project_id, latest_status),
                latest_update=latest_summary,
                today_result=compact_text(latest.get("today_result"), 320),
                issue=compact_text(latest.get("issue_text"), 320) or "특이사항 없음",
                budget_status=latest_budget_status,
                risk_level=latest_risk_level,
                next_plan=compact_text(latest.get("next_plan"), 320),
                updated_at=str(latest.get("created_at") or ""),
                quantitative_results=parse_quantitative_results(
                    latest.get("quantitative_results")
                ),
            )
        )
    return merged


def stage_html(project_id: str, current_status: str) -> str:
    pieces = []
    stages = project_stages(project_id)
    try:
        current_index = stages.index(current_status)
    except ValueError:
        current_index = -1
    for idx, label in enumerate(stages):
        class_names = []
        if idx < current_index:
            class_names.append("is-done")
        if idx == current_index:
            class_names.append("is-current")
        class_attr = " ".join(class_names)
        pieces.append(f'<span class="{class_attr}">{safe_text(label)}</span>')
    return "\n".join(pieces)


def risk_class(risk_level: str) -> str:
    if risk_level == "지연":
        return "risk-delay"
    if risk_level == "주의":
        return "risk-watch"
    return "risk-normal"


def render_project_card(project: EmergencyProject) -> str:
    stage_markup = stage_html(project.project_id, project.status)
    metric_markup = metric_panel_html(project)
    risk_markup = f"""
      <span class="project-risk {risk_class(project.risk_level)}">{safe_text(project.risk_level)}</span>
    """
    updated_at_markup = (
        f'<span class="project-updated">최근 입력 {safe_text(project.updated_at)}</span>'
        if project.updated_at
        else '<span class="project-updated">입력 전</span>'
    )
    issue_markup = (
        f"""
        <div class="project-milestone project-issue">
          <span>추진상 문제점</span>
          <strong>{safe_text(project.issue)}</strong>
        </div>
        """
        if project.issue and project.issue != "입력 전"
        else ""
    )
    return f"""
      <article class="project-card">
        <div class="project-card-top">
          <div>
            <div class="project-card-head">
              <span class="project-number">{project.number:02d}</span>
              <span class="project-field">{safe_text(project.field)}</span>
              {risk_markup}
            </div>
            <h3>{safe_text(project.title)}</h3>
          </div>
          <div class="project-stage-badge">
            <span>추진률</span>
            <strong>{project.progress_pct}%</strong>
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
        <div class="project-section-label">사업별 진행상태</div>
        <div class="project-stage">
          {stage_markup}
        </div>
        <div class="project-check-row">
          <strong>{safe_text(project.status)}</strong>
          <span>{safe_text(project.latest_update)}</span>
        </div>
        {updated_at_markup}
        {metric_markup}
        <div class="project-milestone">
          <span>추진계획</span>
          <strong>{safe_text(project.milestone)}</strong>
        </div>
        {issue_markup}
      </article>
    """


def compact_stage_points_html(project: EmergencyProject) -> str:
    stages = project_stages(project.project_id)
    if not stages:
        return ""
    points = list(stages)
    try:
        current_index = stages.index(project.status)
    except ValueError:
        current_index = -1
    point_items = []
    for label in points:
        try:
            stage_index = stages.index(label)
        except ValueError:
            stage_index = -1
        class_names = ["project-compact-step"]
        if current_index >= 0 and stage_index < current_index:
            class_names.append("is-done")
        if current_index >= 0 and stage_index == current_index:
            class_names.append("is-current")
        point_items.append(f'<span class="{" ".join(class_names)}">{safe_text(label)}</span>')
    return f"""
      <div class="project-compact-steps" style="--pct:{project.progress_pct};">
        <div class="project-compact-step-track"><span></span></div>
        <div class="project-compact-step-labels" style="grid-template-columns: repeat({len(points)}, minmax(0, 1fr));">
          {"".join(point_items)}
        </div>
      </div>
    """


def compact_hover_detail_html(project: EmergencyProject) -> str:
    stage_markup = stage_html(project.project_id, project.status)
    metrics_markup = metric_rows_html(project)
    issue_markup = (
        f"""
        <div class="project-hover-text">
          <span>추진상 문제점</span>
          <strong>{safe_text(project.issue)}</strong>
        </div>
        """
        if project.issue and project.issue != "입력 전"
        else ""
    )
    return f"""
      <div class="project-hover-detail" aria-hidden="true">
        <div class="project-hover-head">
          <span>{project.number:02d}</span>
          <strong>상세 추진정보</strong>
        </div>
        <dl class="project-hover-meta">
          <div>
            <dt>소관부서</dt>
            <dd>{safe_text(project.department)}</dd>
          </div>
          <div>
            <dt>소요예산</dt>
            <dd>{safe_text(project.budget)}</dd>
          </div>
        </dl>
        <p class="project-hover-feature">{safe_text(project.feature)}</p>
        <div class="project-hover-label">사업별 진행상태</div>
        <div class="project-hover-stage">
          {stage_markup}
        </div>
        <div class="project-hover-status">
          <strong>{safe_text(project.status)}</strong>
          <span>{safe_text(project.latest_update)}</span>
        </div>
        <div class="project-hover-label">정량 수혜지표</div>
        <div class="project-hover-metrics">
          {metrics_markup}
        </div>
        <div class="project-hover-text">
          <span>추진계획</span>
          <strong>{safe_text(project.milestone)}</strong>
        </div>
        {issue_markup}
      </div>
    """


def compact_metric_bars_html(project: EmergencyProject, limit: int = 2) -> str:
    metrics = list(project_metrics(project.project_id))[:limit]
    if not metrics:
        return """
        <div class="project-compact-kpi">
          <div class="project-compact-kpi-item" style="--metric-pct:0;">
            <span class="project-compact-kpi-name">정량 수혜지표</span>
            <div class="project-compact-kpi-values">
              <p><b>목표</b><strong>목표 미설정</strong></p>
              <p><b>실적</b><strong>입력 대기</strong></p>
            </div>
            <em>달성률 산정 대기</em>
            <i><b></b></i>
          </div>
        </div>
        """
    items = []
    for metric in metrics:
        current = metric_current(project, metric)
        current_text = format_metric_value(current, metric.unit, compact=True)
        pct = metric_pct(current, metric.target_value)
        metric_bar_pct = 0.0 if pct is None else pct
        metric_pct_text = "달성률 산정 대기" if pct is None else f"달성률 {pct:.1f}%"
        items.append(
            f"""
            <div class="project-compact-kpi-item" style="--metric-pct:{metric_bar_pct:.3f};">
              <span class="project-compact-kpi-name">{safe_text(metric.label)}</span>
              <div class="project-compact-kpi-values">
                <p><b>목표</b><strong>{safe_text(metric.target_text)}</strong></p>
                <p><b>실적</b><strong>{safe_text(current_text)}</strong></p>
              </div>
              <em>{safe_text(metric_pct_text)}</em>
              <i><b></b></i>
            </div>
            """
        )
    return f"""
      <div class="project-compact-kpi">
        {"".join(items)}
      </div>
    """


def render_project_compact_card(project: EmergencyProject) -> str:
    metric_markup = compact_metric_bars_html(project)
    stage_markup = compact_stage_points_html(project)
    hover_detail = compact_hover_detail_html(project)
    number_mark = PROJECT_NUMBER_MARKS.get(project.number, str(project.number))
    field_group = PROJECT_FIELD_GROUPS.get(project.project_id, project.field)
    field_class = PROJECT_FIELD_CLASSES.get(field_group, "field-default")
    title_markup = safe_text(project.title)
    if project.project_id == "P002":
        title_markup = "소상공인 에너지바우처 지급<br><span class=\"project-title-sub\">공공요금·지방세 부담 완화</span>"
    return f"""
      <article class="project-compact-card project-{safe_text(project.project_id)} {safe_text(field_class)}" tabindex="0" aria-label="{safe_text(project.title)} 상세 보기">
        <h3><span>{safe_text(number_mark)}</span><strong>{title_markup}</strong></h3>
        <div class="project-compact-main">
          <div class="project-compact-info">
            <em>{safe_text(field_group)}</em>
            <p><b>예산</b>{safe_text(project.budget)}</p>
            <p class="project-compact-department"><b>담당부서</b>{safe_text(project.department)}</p>
          </div>
          <div class="project-compact-donut" style="--pct:{project.progress_pct};">
            <span>진행률</span>
            <strong>{project.progress_pct}%</strong>
          </div>
        </div>
        {metric_markup}
        {stage_markup}
        {hover_detail}
      </article>
    """


def render_project_dashboard(projects: list[EmergencyProject]) -> None:
    updates = load_project_updates()
    projects = apply_project_updates(projects, updates)
    budget_projects = [project for project in projects if project.budget != "비예산"]
    updated_project_count = len(latest_project_update_map(updates))
    avg_progress = (
        round(sum(project.progress_pct for project in projects) / len(projects), 1)
        if projects
        else 0
    )
    countdown_label, _countdown_status = minsaeng_countdown()
    if countdown_label == "D-DAY":
        countdown_caption = "D-Day"
    elif countdown_label.startswith("D-"):
        countdown_caption = f"D-Day : {countdown_label[2:]}일"
    else:
        countdown_caption = countdown_label
    header_image_uri = image_data_uri(str(PROJECT_HEADER_IMAGE_PATH))
    title_markup = (
        f'<img class="project-title-image" src="{header_image_uri}" alt="민생100일 비상조치 추진상황" />'
        if header_image_uri
        else "<strong>민생100일 비상조치 추진상황</strong>"
    )
    title_class = "project-title-art image-title" if header_image_uri else "project-title-art"
    html_cards = "\n".join(render_project_compact_card(project) for project in projects)
    board_class = "project-board compact"
    grid_class = "project-compact-grid"
    st.html(
        f"""
        <section class="{board_class} notranslate" translate="no" lang="ko">
          <div class="project-board-head">
            <div class="project-board-spacer" aria-hidden="true"></div>
            <div class="project-head-title">
              <div class="{title_class}" aria-label="민생100일 비상조치 추진상황">
                {title_markup}
              </div>
            </div>
            <div class="project-head-actions">
              <div class="project-overall-progress" style="--pct:{avg_progress};">
                <span>전체 진행률</span>
                <strong>{avg_progress}%</strong>
                <em>{safe_text(countdown_caption)}</em>
              </div>
            </div>
          </div>
          <div class="project-summary">
            <div>
              <span>관리사업</span>
              <strong>{len(projects)}개</strong>
            </div>
            <div>
              <span>총 사업규모</span>
              <strong>1조 3,781억원</strong>
            </div>
            <div>
              <span>최신 입력 사업</span>
              <strong>{updated_project_count}개</strong>
            </div>
          </div>
          <div class="project-flow">
            <span>담당부서 일일 입력</span>
            <i></i>
            <span>사업별 상태 갱신</span>
            <i></i>
            <span>부산광역시장 일일 점검</span>
          </div>
          <div class="{grid_class}">
            {html_cards}
          </div>
        </section>
        """
    )


def display_actual_text(value: float | None, unit: str) -> str:
    if value is None:
        if unit == "%":
            return "0%"
        return "0"
    return format_metric_value(value, unit, compact=True)


def display_group_actual_text(
    project: EmergencyProject, metric_ids: tuple[str, ...]
) -> tuple[str, bool]:
    metric_map = {metric.metric_id: metric for metric in project_metrics(project.project_id)}
    group_metrics = [metric_map[metric_id] for metric_id in metric_ids if metric_id in metric_map]
    if len(group_metrics) > 1 and len({metric.unit for metric in group_metrics}) == 1:
        has_value = any(metric_current(project, metric) is not None for metric in group_metrics)
        if not has_value:
            return "입력 대기", True
        current_total = sum(metric_current(project, metric) or 0.0 for metric in group_metrics)
        return format_metric_value(current_total, group_metrics[0].unit, compact=True), False

    values: list[str] = []
    has_value = False
    for metric_id in metric_ids:
        metric = metric_map.get(metric_id)
        if metric is None:
            continue
        current = metric_current(project, metric)
        if current is None:
            values.append("입력 대기")
            continue
        has_value = True
        values.append(format_metric_value(current, metric.unit, compact=True))
    if not values or not has_value:
        return "입력 대기", True
    return " / ".join(values), False


def display_metric_groups(project: EmergencyProject) -> list[tuple[str, str, str, str, bool]]:
    rows: list[tuple[str, str, str, str, bool]] = []
    for label, metric_ids, target_text, unit_text, _target_value in display_metric_specs(project.project_id):
        current_text, waiting = display_group_actual_text(project, metric_ids)
        rows.append((label, target_text, unit_text, current_text, waiting))
    return rows


def display_metric_rows_html(project: EmergencyProject) -> str:
    metrics = display_metric_groups(project)
    if not metrics:
        return """
          <div class="display-metric-row">
            <div class="display-metric-title">
              <strong>정량 수혜지표</strong>
            </div>
            <div class="display-metric-values">
              <p><span>목표</span><b>목표 미설정</b></p>
              <i></i>
              <p><span>실적</span><b class="is-waiting">입력 대기</b></p>
            </div>
          </div>
        """
    rows: list[str] = []
    for label, target_text, unit_text, current_text, waiting in metrics:
        waiting_class = " is-waiting" if waiting else ""
        unit_markup = f'<em>(단위: {safe_text(unit_text)})</em>' if unit_text else ""
        rows.append(
            f"""
            <div class="display-metric-row">
              <div class="display-metric-title">
                <strong>{safe_text(label)}</strong>
                {unit_markup}
              </div>
              <div class="display-metric-values">
                <p><span>목표</span><b>{safe_text(target_text)}</b></p>
                <i></i>
                <p><span>실적</span><b class="{waiting_class.strip()}">{safe_text(current_text)}</b></p>
              </div>
            </div>
            """
        )
    return "\n".join(rows)


def display_stage_points_html(project: EmergencyProject) -> str:
    stages = project_stages(project.project_id)
    if not stages:
        return ""
    try:
        current_index = stages.index(project.status)
    except ValueError:
        current_index = -1
    points: list[str] = []
    for idx, label in enumerate(stages):
        classes = ["display-stage-point"]
        if current_index >= 0 and idx < current_index:
            classes.append("is-done")
        if current_index >= 0 and idx == current_index:
            classes.append("is-current")
        points.append(f'<span class="{" ".join(classes)}">{safe_text(label)}</span>')
    return f"""
      <div class="display-stage-track" style="--pct:{project.progress_pct};">
        <div class="display-stage-line"><span></span></div>
        <div class="display-stage-labels" style="grid-template-columns: repeat({len(stages)}, minmax(0, 1fr));">
          {"".join(points)}
        </div>
      </div>
    """


def display_card_detail_popover_html(
    project: EmergencyProject,
    achievement: float,
    progress: float,
) -> str:
    metric_rows: list[str] = []
    for label, target_text, unit_text, current_text, waiting in display_metric_groups(project):
        waiting_class = " is-waiting" if waiting else ""
        unit_markup = f'<em>단위: {safe_text(unit_text)}</em>' if unit_text else ""
        metric_rows.append(
            f"""
            <div class="display-detail-metric">
              <div>
                <strong>{safe_text(label)}</strong>
                {unit_markup}
              </div>
              <p><span>목표</span><b>{safe_text(target_text)}</b></p>
              <p><span>실적</span><b class="{waiting_class.strip()}">{safe_text(current_text)}</b></p>
            </div>
            """
        )
    if not metric_rows:
        metric_rows.append(
            """
            <div class="display-detail-metric">
              <div><strong>정량 수혜지표</strong></div>
              <p><span>목표</span><b>목표 미설정</b></p>
              <p><span>실적</span><b class="is-waiting">입력 대기</b></p>
            </div>
            """
        )
    today_result = project.today_result or project.latest_update or "입력 이력 없음"
    next_plan = project.next_plan or "입력 이력 없음"
    issue_text = project.issue if project.issue and project.issue != "입력 전" else "특이사항 없음"
    updated_at = project.updated_at or "입력 전"
    return f"""
      <div class="display-card-detail-popover" aria-hidden="true">
        <div class="display-detail-head">
          <span>{project.number:02d}</span>
          <div>
            <b>{safe_text(project.title)}</b>
            <em>{safe_text(project.field)}</em>
          </div>
        </div>
        <div class="display-detail-badges">
          <span>추진상태 <b>{safe_text(project.status)}</b></span>
          <span>상태 <b>{safe_text(project.budget_status)}</b></span>
          <span>위험도 <b>{safe_text(project.risk_level)}</b></span>
          <span>입력일시 <b>{safe_text(updated_at)}</b></span>
        </div>
        <div class="display-detail-summary">
          <p><span>진행률</span><strong>{progress:.0f}%</strong></p>
          <p><span>달성률</span><strong>{achievement:.1f}%</strong></p>
          <p><span>예산</span><strong>{safe_text(project.budget)}</strong></p>
          <p><span>담당부서</span><strong>{safe_text(project.department)}</strong></p>
        </div>
        <div class="display-detail-section">
          <h4>정량 실적</h4>
          <div class="display-detail-metrics">
            {"".join(metric_rows)}
          </div>
        </div>
        <div class="display-detail-text-grid">
          <div class="display-detail-section">
            <h4>금일 추진사항</h4>
            <p>{safe_text(today_result)}</p>
          </div>
          <div class="display-detail-section">
            <h4>추진상 문제점</h4>
            <p>{safe_text(issue_text)}</p>
          </div>
          <div class="display-detail-section">
            <h4>향후 추진계획</h4>
            <p>{safe_text(next_plan)}</p>
          </div>
        </div>
      </div>
    """


def display_project_card(project: EmergencyProject) -> str:
    title = DISPLAY_PROJECT_TITLES.get(project.project_id, project.title)
    progress = max(0.0, min(float(project.progress_pct), 100.0))
    achievement = display_achievement_pct(project)
    field_group = PROJECT_FIELD_GROUPS.get(project.project_id, project.field)
    field_class = PROJECT_FIELD_CLASSES.get(field_group, "field-default")
    detail_popover = display_card_detail_popover_html(project, achievement, progress)
    return f"""
      <article class="display-project-card {safe_text(field_class)}">
        <div class="display-card-field">
          <span aria-hidden="true"></span>
          <b>{safe_text(field_group)}</b>
        </div>
        <h3>{safe_text(title)}</h3>
        <div class="display-card-gauge" style="--pct:{achievement:.2f}; --arc-deg:{max(achievement, 12.0) * 1.8:.2f}deg;">
          <div class="display-card-gauge-value">
            <span>달성률(%)</span>
            <strong>{achievement:.1f}</strong>
          </div>
        </div>
        <div class="display-card-metrics">
          {display_metric_rows_html(project)}
        </div>
        <div class="display-card-progress-panel">
          <div class="display-card-foot">
            <div class="display-card-meta">
              <p><span>예산</span><b>{safe_text(project.budget)}</b></p>
              <p><span>담당부서</span><b>{safe_text(project.department)}</b></p>
            </div>
            <div class="display-card-mini-gauge" style="--pct:{progress:.2f}; --arc-deg:{max(progress, 12.0) * 1.8:.2f}deg;">
              <span>진행률</span>
              <strong>{progress:.0f}%</strong>
            </div>
          </div>
          {display_stage_points_html(project)}
        </div>
        {detail_popover}
      </article>
    """


def render_project_display_board(projects: list[EmergencyProject]) -> None:
    updates = load_project_updates()
    projects = apply_project_updates(projects, updates)
    avg_progress = (
        round(sum(project.progress_pct for project in projects) / len(projects), 1)
        if projects
        else 0.0
    )
    countdown_label, _countdown_status = minsaeng_countdown()
    display_countdown = countdown_label if countdown_label.startswith("D-") else "D-0"
    cards_html = "\n".join(display_project_card(project) for project in projects)
    st.html(
        f"""
        <section class="display-board-page notranslate" translate="no" lang="ko">
          <div class="display-hero">
            <div class="display-hero-copy">
              <h1>민생100일 비상조치 추진상황판</h1>
              <div class="display-dday-card">{safe_text(display_countdown)}</div>
            </div>
            <div class="display-hero-progress">
              <div class="display-overall-label">전체 진행률(%)</div>
              <div class="display-overall-gauge" style="--pct:{avg_progress:.2f}; --arc-deg:{max(avg_progress, 12.0) * 1.8:.2f}deg;">
                <strong>{avg_progress:.1f}</strong>
              </div>
            </div>
            <div class="display-hero-brand">
              <span>미래 대전환의 중심</span>
              <strong>해양수도 부산</strong>
            </div>
          </div>
          <div class="display-card-zone">
            <div class="display-project-grid">
              {cards_html}
            </div>
          </div>
        </section>
        """,
    )


def admin_user_count() -> int:
    if not DB_PATH.exists():
        return 0
    with connect_db() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0])


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT user_id, username, password_hash, role, department, is_active
            FROM admin_users
            WHERE username = ?
            """,
            (username.strip(),),
        ).fetchone()
    if not row or not row["is_active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {
        "user_id": int(row["user_id"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "department": str(row["department"] or ""),
    }


def current_admin_user() -> dict[str, Any] | None:
    user = st.session_state.get("admin_user")
    return user if isinstance(user, dict) else None


def project_options(projects: list[EmergencyProject]) -> dict[str, str]:
    return {project.project_id: f"{project.number:02d}. {project.title}" for project in projects}


def allowed_project_ids(user: dict[str, Any], projects: list[EmergencyProject]) -> list[str]:
    if user["role"] in {"admin", "viewer"}:
        return [project.project_id for project in projects]
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT project_id
            FROM admin_project_permissions
            WHERE user_id = ?
            ORDER BY project_id
            """,
            (user["user_id"],),
        ).fetchall()
    assigned = [str(row["project_id"]) for row in rows]
    if assigned:
        return assigned
    department = user.get("department", "")
    if department:
        return [
            project.project_id
            for project in projects
            if department in project.department
        ]
    return []


def latest_update_for_project(project_id: str, updates: pd.DataFrame) -> dict[str, Any] | None:
    return latest_project_update_map(updates).get(project_id)


def insert_project_update(
    user: dict[str, Any],
    project_id: str,
    status: str,
    progress_pct: float,
    risk_level: str,
    budget_status: str,
    quantitative_results: dict[str, float],
    today_result: str,
    next_plan: str,
    issue_text: str,
    public_summary: str,
) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO project_updates (
                project_id, status, progress_pct, risk_level, budget_status,
                quantitative_results, today_result, next_plan, issue_text, public_summary,
                created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                status,
                float(progress_pct),
                risk_level,
                budget_status,
                json.dumps(quantitative_results, ensure_ascii=False),
                today_result.strip(),
                next_plan.strip(),
                issue_text.strip(),
                public_summary.strip(),
                int(user["user_id"]),
                current_kst_timestamp(),
            ),
        )
    load_project_updates.clear()


def save_user_permissions(user_id: int, project_ids: list[str]) -> None:
    with connect_db() as conn:
        conn.execute(
            "DELETE FROM admin_project_permissions WHERE user_id = ?",
            (user_id,),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO admin_project_permissions (user_id, project_id)
            VALUES (?, ?)
            """,
            [(user_id, project_id) for project_id in project_ids],
        )


def create_admin_user(
    username: str,
    password: str,
    role: str,
    department: str,
    is_active: bool,
    assigned_project_ids: list[str],
) -> None:
    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO admin_users (
                username, password_hash, role, department, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username.strip(),
                hash_password(password),
                role,
                department.strip(),
                1 if is_active else 0,
                current_kst_timestamp(),
                current_kst_timestamp(),
            ),
        )
        user_id = int(cursor.lastrowid)
    save_user_permissions(user_id, assigned_project_ids)


def update_admin_user(
    user_id: int,
    role: str,
    department: str,
    is_active: bool,
    assigned_project_ids: list[str],
    new_password: str = "",
) -> None:
    password_sql = ", password_hash = ?" if new_password else ""
    params: list[Any] = [role, department.strip(), 1 if is_active else 0, current_kst_timestamp()]
    if new_password:
        params.append(hash_password(new_password))
    params.append(user_id)
    with connect_db() as conn:
        conn.execute(
            f"""
            UPDATE admin_users
            SET role = ?, department = ?, is_active = ?, updated_at = ?{password_sql}
            WHERE user_id = ?
            """,
            params,
        )
    save_user_permissions(user_id, assigned_project_ids)


def project_history_table(updates: pd.DataFrame, projects: list[EmergencyProject]) -> pd.DataFrame:
    if updates.empty:
        return pd.DataFrame()
    title_map = project_title_map(projects)
    table = updates.copy()
    table["사업명"] = table["project_id"].map(title_map).fillna(table["project_id"])
    table["입력부서"] = table["input_department"].fillna("")
    table["입력자"] = table["input_user"].fillna("")
    table = table.rename(
        columns={
            "created_at": "입력일시",
            "status": "추진상태",
            "progress_pct": "진행률",
            "risk_level": "위험도",
            "budget_status": "상태",
            "today_result": "금일 추진사항",
            "next_plan": "향후 추진계획",
            "issue_text": "추진상 문제점",
            "public_summary": "공개 요약",
        }
    )
    return table[
        [
            "입력일시",
            "사업명",
            "추진상태",
            "진행률",
            "위험도",
            "상태",
            "금일 추진사항",
            "추진상 문제점",
            "향후 추진계획",
            "입력부서",
            "입력자",
        ]
    ]


def render_login_panel() -> None:
    st.markdown(
        """
        <section class="admin-shell notranslate" translate="no" lang="ko">
          <div class="admin-title">
            <span>부서 입력</span>
            <h2>민생100일 비상대책 추진상황 입력</h2>
            <p>부서별 계정으로 로그인해 배정된 사업의 상태와 추진실적을 입력합니다.</p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if admin_user_count() == 0:
        st.error(
            "관리자 계정이 아직 생성되지 않았습니다. 서버 환경변수 "
            "`MINSAENG_ADMIN_PASSWORD` 설정 후 앱을 재시작하면 최초 관리자 계정이 생성됩니다."
        )
        return
    with st.form("admin_login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True)
    if submitted:
        user = authenticate_user(username, password)
        if not user:
            st.error("아이디 또는 비밀번호가 맞지 않거나 비활성 계정입니다.")
            return
        st.session_state["admin_user"] = user
        st.rerun()


def render_project_update_input(user: dict[str, Any], projects: list[EmergencyProject]) -> None:
    options = project_options(projects)
    allowed_ids = allowed_project_ids(user, projects)
    if not allowed_ids:
        st.warning("입력 권한이 부여된 사업이 없습니다. 관리자에게 사업 권한 배정을 요청해야 합니다.")
        return
    allowed_labels = [options[project_id] for project_id in allowed_ids if project_id in options]
    if not allowed_labels:
        st.warning("배정된 사업 ID가 현재 사업 목록과 일치하지 않습니다. 관리자 권한을 다시 설정해야 합니다.")
        return
    selected_label = st.selectbox(
        "사업 선택",
        allowed_labels,
    )
    selected_project_id = next(
        project_id for project_id, label in options.items() if label == selected_label
    )
    selected_project = next(
        project for project in projects if project.project_id == selected_project_id
    )
    updates = load_project_updates()
    latest = latest_update_for_project(selected_project_id, updates) or {}
    stage_options = list(project_stages(selected_project_id))
    status_default = str(latest.get("status") or stage_options[0])
    budget_default = normalize_budget_status(latest.get("budget_status"))
    risk_default = str(latest.get("risk_level") or "정상")
    latest_quantitative = parse_quantitative_results(latest.get("quantitative_results"))

    with st.form("project_update_form", clear_on_submit=False):
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            status = st.selectbox(
                "추진상태",
                stage_options,
                index=stage_options.index(status_default)
                if status_default in stage_options
                else 0,
            )
        with col2:
            budget_status = st.selectbox(
                "상태",
                BUDGET_STATUS_OPTIONS,
                index=BUDGET_STATUS_OPTIONS.index(budget_default)
                if budget_default in BUDGET_STATUS_OPTIONS
                else BUDGET_STATUS_OPTIONS.index("추진중"),
            )
        with col3:
            risk_level = st.selectbox(
                "위험도",
                RISK_LEVEL_OPTIONS,
                index=RISK_LEVEL_OPTIONS.index(risk_default)
                if risk_default in RISK_LEVEL_OPTIONS
                else 0,
            )
        progress_pct = stage_progress_pct(selected_project_id, status)
        st.caption(
            f"진행률은 상황판 카드 하단의 추진상태 단계 기준으로 자동 산정됩니다. 현재 선택값: {progress_pct}%"
        )
        st.markdown("##### 정량 실적")
        st.caption("금액 지표는 만원 단위로 입력합니다. 상황판에서는 억원·조원 단위로 자동 변환됩니다.")
        quantitative_results: dict[str, float] = {}
        metric_list = list(project_metrics(selected_project_id))
        if metric_list:
            for idx in range(0, len(metric_list), 2):
                cols = st.columns(2)
                for col, metric in zip(cols, metric_list[idx : idx + 2]):
                    with col:
                        default_value = float(quantitative_value(latest_quantitative, metric.metric_id) or 0.0)
                        quantitative_results[metric.metric_id] = float(
                            st.number_input(
                                f"{metric.label} ({metric.unit})",
                                min_value=0.0,
                                value=default_value,
                                step=1.0,
                                help=f"목표: {metric.target_text}",
                                key=f"metric_{selected_project.project_id}_{metric.metric_id}",
                            )
                        )
        else:
            st.info("이 사업에는 정량 실적 항목이 설정되어 있지 않습니다.")
        today_result = st.text_area(
            "금일 추진사항",
            value=str(latest.get("today_result") or ""),
            height=110,
            placeholder="오늘 처리한 협의, 예산 작업, 신청·접수, 지급실적, 현장 조치 등을 입력",
        )
        issue_text = st.text_area(
            "추진상 문제점",
            value=str(latest.get("issue_text") or ""),
            height=90,
            placeholder="예산, 조례, 기관협의, 민원, 일정 지연 등 점검 필요 사항",
        )
        next_plan = st.text_area(
            "향후 추진계획",
            value=str(latest.get("next_plan") or ""),
            height=90,
            placeholder="다음 조치 일정, 추가 협의, 보완 계획 등을 입력",
        )
        public_summary = st.text_input(
            "상황판 공개 요약",
            value=str(latest.get("public_summary") or ""),
            placeholder="카드에 짧게 노출할 문장. 미입력 시 금일 추진사항 앞부분을 사용",
        )
        submitted = st.form_submit_button("저장", use_container_width=True)
    if submitted:
        insert_project_update(
            user=user,
            project_id=selected_project_id,
            status=status,
            progress_pct=progress_pct,
            risk_level=risk_level,
            budget_status=budget_status,
            quantitative_results=quantitative_results,
            today_result=today_result,
            next_plan=next_plan,
            issue_text=issue_text,
            public_summary=public_summary,
        )
        st.success("저장했습니다. 추진상황 화면에는 최신 입력값이 반영됩니다.")
        st.rerun()


def render_user_management(projects: list[EmergencyProject]) -> None:
    users = load_admin_users()
    permissions = load_user_permissions()
    options = project_options(projects)

    st.subheader("계정 생성")
    with st.form("create_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            username = st.text_input("신규 아이디")
            password = st.text_input("초기 비밀번호", type="password")
            department = st.text_input("부서명")
        with col2:
            role_label = st.selectbox("권한", list(ADMIN_ROLES.values()), index=1)
            role = next(key for key, value in ADMIN_ROLES.items() if value == role_label)
            is_active = st.checkbox("활성 계정", value=True)
            assigned_labels = st.multiselect(
                "배정 사업",
                list(options.values()),
                help="관리자는 전체 사업 접근이 가능하지만, 부서 담당자는 배정 사업만 입력 가능합니다.",
            )
        submitted = st.form_submit_button("계정 생성", use_container_width=True)
    if submitted:
        if not username.strip() or not password:
            st.error("아이디와 초기 비밀번호는 필수입니다.")
        else:
            assigned_project_ids = [
                project_id for project_id, label in options.items() if label in assigned_labels
            ]
            try:
                create_admin_user(username, password, role, department, is_active, assigned_project_ids)
                st.success("계정을 생성했습니다.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("이미 존재하는 아이디입니다.")

    st.subheader("계정 수정")
    if users.empty:
        st.info("등록된 계정이 없습니다.")
        return
    user_labels = [f"{row.username} ({ADMIN_ROLES.get(row.role, row.role)})" for row in users.itertuples()]
    selected = st.selectbox("수정할 계정", user_labels)
    selected_index = user_labels.index(selected)
    selected_user = users.iloc[selected_index]
    selected_user_id = int(selected_user["user_id"])
    assigned_ids = permissions[permissions["user_id"].eq(selected_user_id)]["project_id"].tolist()
    assigned_defaults = [options[project_id] for project_id in assigned_ids if project_id in options]

    with st.form("edit_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            role_label = st.selectbox(
                "권한 변경",
                list(ADMIN_ROLES.values()),
                index=list(ADMIN_ROLES).index(str(selected_user["role"])),
            )
            role = next(key for key, value in ADMIN_ROLES.items() if value == role_label)
            department = st.text_input("부서명 변경", value=str(selected_user.get("department") or ""))
        with col2:
            is_active = st.checkbox("활성 상태", value=bool(selected_user["is_active"]))
            new_password = st.text_input("비밀번호 재설정", type="password", placeholder="변경 시에만 입력")
            assigned_labels = st.multiselect("배정 사업 변경", list(options.values()), default=assigned_defaults)
        submitted = st.form_submit_button("계정 수정 저장", use_container_width=True)
    if submitted:
        assigned_project_ids = [
            project_id for project_id, label in options.items() if label in assigned_labels
        ]
        update_admin_user(
            selected_user_id,
            role,
            department,
            is_active,
            assigned_project_ids,
            new_password,
        )
        st.success("계정 정보를 수정했습니다.")
        st.rerun()

    display_users = users.copy()
    display_users["권한"] = display_users["role"].map(ADMIN_ROLES)
    display_users["활성"] = display_users["is_active"].map({1: "활성", 0: "비활성"})
    st.dataframe(
        display_users[["username", "권한", "department", "활성", "updated_at"]].rename(
            columns={
                "username": "아이디",
                "department": "부서",
                "updated_at": "수정일시",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


def render_update_history(projects: list[EmergencyProject]) -> None:
    updates = load_project_updates()
    table = project_history_table(updates, projects)
    if table.empty:
        st.info("아직 입력 이력이 없습니다.")
        return
    st.dataframe(table.head(100), hide_index=True, use_container_width=True)


def render_admin_dashboard(projects: list[EmergencyProject]) -> None:
    st.markdown(
        """
        <section class="admin-shell notranslate" translate="no" lang="ko">
          <div class="admin-title">
            <span>부서 입력 시스템</span>
            <h2>민생100일 비상대책 추진상황 관리</h2>
            <p>입력된 내용은 이력으로 보관되며, 추진상황 화면에는 사업별 최신 입력값이 표시됩니다.</p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    user = current_admin_user()
    if not user:
        render_login_panel()
        return

    col1, col2 = st.columns([1, 4])
    with col1:
        st.caption("로그인 계정")
        st.write(f"**{user['username']}**")
        st.caption(f"{ADMIN_ROLES.get(user['role'], user['role'])} · {user.get('department') or '부서 미지정'}")
        if st.button("로그아웃", use_container_width=True):
            st.session_state.pop("admin_user", None)
            st.rerun()
    with col2:
        st.info("추진상태·상태·위험도·실적은 저장 시점마다 이력으로 남습니다. 오입력 시 기존 이력을 수정하지 말고 새 이력으로 정정 입력하는 방식입니다.")

    if user["role"] == "viewer":
        render_update_history(projects)
        return

    if user["role"] == "admin":
        tabs = st.tabs(["추진실적 입력", "계정 관리", "입력 이력"])
        with tabs[0]:
            render_project_update_input(user, projects)
        with tabs[1]:
            render_user_management(projects)
        with tabs[2]:
            render_update_history(projects)
    else:
        tabs = st.tabs(["추진실적 입력", "입력 이력"])
        with tabs[0]:
            render_project_update_input(user, projects)
        with tabs[1]:
            render_update_history(projects)


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

        .economy-carousel {
          max-width: 1680px;
          margin: 18px auto 28px;
          padding: 0 36px;
          box-sizing: border-box;
        }

        .eco-carousel-stage {
          position: relative;
          height: 300px;
          overflow: hidden;
          border-radius: 22px;
          background:
            radial-gradient(circle at 50% 58%, rgba(47, 113, 199, 0.16), transparent 28%),
            linear-gradient(180deg, #f5f8fc 0%, #eef3f8 100%);
          box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.78);
        }

        .eco-carousel-slide {
          position: absolute;
          inset: 0;
          display: grid;
          grid-template-columns: minmax(0, 0.88fr) minmax(420px, 1.18fr) minmax(0, 0.88fr);
          align-items: center;
          gap: 20px;
          padding: 34px 110px;
          opacity: 0;
          pointer-events: none;
          transform: translateX(18px);
          animation: ecoCarouselShow var(--carousel-duration) linear infinite both;
          animation-delay: var(--delay);
          box-sizing: border-box;
        }

        @keyframes ecoCarouselShow {
          0% {
            opacity: 0;
            transform: translateX(18px);
          }
          0.25%,
          6.1% {
            opacity: 1;
            transform: translateX(0);
          }
          6.65%,
          100% {
            opacity: 0;
            transform: translateX(-18px);
          }
        }

        .eco-carousel-card {
          min-height: 182px;
          padding: 24px 26px;
          border-radius: 18px;
          background: #fff;
          border: 1px solid rgba(210, 219, 230, 0.86);
          box-shadow: 0 18px 42px rgba(31, 45, 71, 0.1);
          text-align: center;
          box-sizing: border-box;
        }

        .eco-carousel-card.center {
          min-height: 232px;
          padding: 30px 36px;
          border-radius: 20px;
          box-shadow: 0 24px 58px rgba(31, 45, 71, 0.18);
          transform: translateY(-2px);
        }

        .eco-carousel-card.side {
          opacity: 0.72;
          filter: saturate(0.86);
          transform: scale(0.88);
        }

        .eco-carousel-category {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 7px;
          min-width: 0;
          margin-bottom: 10px;
          color: #687889;
          font-size: 14px;
          font-weight: 900;
          line-height: 1.2;
          word-break: keep-all;
        }

        .eco-carousel-card.center .eco-carousel-category {
          font-size: 16px;
        }

        .eco-carousel-card h3 {
          min-height: 42px;
          margin: 0 0 12px;
          color: #222b35;
          font-size: 24px;
          font-weight: 900;
          line-height: 1.22;
          letter-spacing: 0;
          word-break: keep-all;
        }

        .eco-carousel-card.center h3 {
          min-height: 52px;
          font-size: 34px;
        }

        .eco-carousel-value {
          display: flex;
          align-items: baseline;
          justify-content: center;
          gap: 9px;
          margin-bottom: 10px;
          color: #2f7fe8;
        }

        .eco-carousel-value strong {
          color: #2f7fe8;
          font-size: 44px;
          font-weight: 900;
          line-height: 1;
          letter-spacing: 0;
          white-space: nowrap;
        }

        .eco-carousel-card.center .eco-carousel-value strong {
          font-size: 62px;
        }

        .eco-carousel-value em {
          color: #77889b;
          font-size: 17px;
          font-style: normal;
          font-weight: 900;
          white-space: nowrap;
        }

        .eco-carousel-value-combo {
          display: inline-flex;
          align-items: baseline;
          gap: 3px;
        }

        .eco-carousel-value-combo b {
          color: inherit;
          font-size: inherit;
          font-weight: inherit;
          line-height: inherit;
        }

        .eco-carousel-value-combo small {
          color: inherit;
          font-size: 0.56em;
          font-weight: inherit;
          line-height: 1;
          white-space: nowrap;
        }

        .eco-carousel-period {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 30px;
          padding: 0 16px;
          border-radius: 999px;
          background: #eef2f7;
          color: #6b7c8f;
          font-size: 16px;
          font-weight: 900;
          line-height: 1;
        }

        .eco-carousel-card.center .eco-carousel-period {
          min-height: 36px;
          padding: 0 20px;
          font-size: 20px;
        }

        .eco-carousel-count {
          position: absolute;
          right: 72px;
          bottom: 26px;
          color: #3e7ae4;
          font-size: 18px;
          font-weight: 900;
        }

        .eco-carousel-arrow {
          position: absolute;
          top: 50%;
          z-index: 5;
          width: 52px;
          height: 52px;
          border-top: 3px solid #1aa2ff;
          border-left: 3px solid #1aa2ff;
          opacity: 0.92;
        }

        .eco-carousel-arrow.left {
          left: 34px;
          transform: translateY(-50%) rotate(-45deg);
        }

        .eco-carousel-arrow.right {
          right: 34px;
          transform: translateY(-50%) rotate(135deg);
        }

        .economy-carousel:hover .eco-carousel-slide {
          animation-play-state: paused;
        }

        .project-board {
          max-width: 1680px;
          margin: 0 auto 54px;
          padding: 0 36px 36px;
        }

        .project-board-head {
          display: grid;
          grid-template-columns: minmax(220px, 1fr) auto minmax(300px, 1fr);
          align-items: center;
          gap: 24px;
          padding: 26px 0 10px;
        }

        .project-head-title {
          text-align: center;
        }

        .project-board-head h2 {
          margin: 0;
          color: #081521;
          font-size: clamp(36px, 3vw, 48px);
          font-weight: 900;
          letter-spacing: 0;
          line-height: 1.15;
          white-space: nowrap;
        }

        .project-head-actions {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 12px;
          min-width: 0;
        }

        .project-overall-progress {
          min-width: 240px;
          padding: 12px 14px;
          border: 1px solid #d8e5f3;
          border-radius: 18px;
          background: #fff;
          box-shadow: 0 12px 24px rgba(22, 39, 67, 0.08);
        }

        .project-overall-progress div {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 9px;
        }

        .project-overall-progress span {
          color: #617086;
          font-size: 12px;
          font-weight: 900;
          white-space: nowrap;
        }

        .project-overall-progress strong {
          color: #2563eb;
          font-size: 28px;
          font-weight: 950;
          line-height: 1;
          white-space: nowrap;
        }

        .project-overall-progress i {
          display: block;
          height: 9px;
          overflow: hidden;
          border-radius: 999px;
          background: #e1e9f3;
        }

        .project-overall-progress i b {
          display: block;
          width: calc(var(--pct) * 1%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, #2dd4bf 0%, #2563eb 100%);
        }

        .project-view-toggle {
          display: inline-flex;
          gap: 8px;
          padding: 6px;
          border-radius: 999px;
          background: #eef3f8;
          border: 1px solid #d8e0e7;
        }

        .project-view-toggle a {
          min-width: 82px;
          padding: 10px 16px;
          border-radius: 999px;
          color: #4b5c6e;
          font-size: 15px;
          font-weight: 900;
          line-height: 1;
          text-align: center;
          text-decoration: none;
        }

        .project-view-toggle a.active {
          background: linear-gradient(135deg, #f05b6d 0%, #ff9d1b 100%);
          color: #fff;
          box-shadow: 0 8px 18px rgba(220, 82, 52, 0.22);
        }

        .project-summary {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
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

        .project-risk {
          display: inline-flex;
          align-items: center;
          min-height: 28px;
          padding: 0 10px;
          border-radius: 999px;
          color: #082033;
          font-size: 12px;
          font-weight: 900;
        }

        .project-risk.risk-normal {
          background: #3eeadf;
        }

        .project-risk.risk-watch {
          background: #ffd451;
        }

        .project-risk.risk-delay {
          background: #ff776e;
          color: #fff;
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

        .project-updated {
          display: block;
          margin: -5px 0 12px;
          color: rgba(255, 255, 255, 0.62);
          font-size: 12px;
          font-weight: 800;
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

        .project-issue {
          margin-top: 12px;
        }

        .project-source {
          margin: 20px 0 0;
          color: #627181;
          font-size: 13px;
          font-weight: 800;
        }

        .admin-shell {
          width: calc(100% - 72px);
          max-width: 1500px;
          margin: 38px auto 22px;
        }

        .admin-title {
          padding: 28px 30px;
          border-radius: 20px;
          background:
            radial-gradient(circle at 94% 14%, rgba(62, 234, 223, 0.16), transparent 26%),
            linear-gradient(135deg, #0b1742 0%, #142f73 58%, #1c5a95 100%);
          color: #fff;
          box-shadow: 0 18px 38px rgba(8, 20, 54, 0.16);
        }

        .admin-title span {
          display: block;
          margin-bottom: 8px;
          color: #3eeadf;
          font-size: 15px;
          font-weight: 900;
        }

        .admin-title h2 {
          margin: 0 0 10px;
          font-size: 32px;
          font-weight: 900;
          letter-spacing: 0;
        }

        .admin-title p {
          max-width: 780px;
          margin: 0;
          color: rgba(255, 255, 255, 0.78);
          font-size: 15px;
          font-weight: 750;
          line-height: 1.6;
          word-break: keep-all;
        }

        div[data-testid="stForm"] {
          border: 1px solid #d8e0e7;
          border-radius: 16px;
          padding: 18px;
          background: #fff;
          box-shadow: 0 12px 26px rgba(19, 35, 60, 0.08);
        }

        div[data-testid="stForm"] label,
        div[data-testid="stTextInput"] label,
        div[data-testid="stTextArea"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stNumberInput"] label,
        div[data-testid="stMultiSelect"] label {
          font-weight: 850;
          color: #1d2730;
        }

        .project-board.compact {
          max-width: 1720px;
          padding: 0 28px 28px;
        }

        .project-board.compact .project-board-head {
          padding-top: 14px;
        }

        .project-board.compact .project-summary {
          gap: 10px;
          margin: 12px 0 12px;
        }

        .project-board.compact .project-summary div {
          min-height: 62px;
          padding: 12px 16px;
          border-radius: 14px;
        }

        .project-board.compact .project-summary span {
          margin-bottom: 4px;
          font-size: 12px;
        }

        .project-board.compact .project-summary strong {
          font-size: 19px;
        }

        .project-board.compact .project-flow {
          margin-bottom: 14px;
          font-size: 13px;
        }

        .project-board.compact .project-flow span {
          padding: 7px 11px;
        }

        .project-compact-grid {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 12px;
        }

        .project-compact-card {
          min-height: 212px;
          padding: 16px;
          border-radius: 16px;
          background:
            radial-gradient(circle at 92% 12%, rgba(255, 255, 255, 0.2), transparent 30%),
            linear-gradient(145deg, #22338f 0%, #15296e 50%, #163e7a 100%);
          color: #fff;
          box-shadow: 0 12px 26px rgba(7, 18, 45, 0.16);
          box-sizing: border-box;
        }

        .project-compact-card:nth-child(4n+2) {
          background:
            radial-gradient(circle at 92% 12%, rgba(255, 255, 255, 0.2), transparent 30%),
            linear-gradient(145deg, #0d7f7c 0%, #176379 50%, #194c89 100%);
        }

        .project-compact-card:nth-child(4n+3) {
          background:
            radial-gradient(circle at 92% 12%, rgba(255, 255, 255, 0.2), transparent 30%),
            linear-gradient(145deg, #b33b65 0%, #8f3c88 45%, #284894 100%);
        }

        .project-compact-card:nth-child(4n) {
          background:
            radial-gradient(circle at 92% 12%, rgba(255, 255, 255, 0.2), transparent 30%),
            linear-gradient(145deg, #315f88 0%, #22557b 46%, #11415f 100%);
        }

        .project-compact-top {
          display: grid;
          grid-template-columns: 34px minmax(0, 1fr) auto;
          align-items: center;
          gap: 8px;
          margin-bottom: 11px;
        }

        .project-compact-number {
          width: 34px;
          height: 34px;
          border-radius: 999px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: rgba(255, 255, 255, 0.18);
          border: 1px solid rgba(255, 255, 255, 0.28);
          font-size: 13px;
          font-weight: 900;
        }

        .project-compact-field {
          min-width: 0;
          overflow: hidden;
          color: rgba(255, 255, 255, 0.82);
          font-size: 12px;
          font-weight: 900;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-top strong {
          color: #3eeadf;
          font-size: 16px;
          font-weight: 900;
        }

        .project-compact-card h3 {
          min-height: 48px;
          margin: 0 0 12px;
          color: #fff;
          font-size: 17px;
          font-weight: 900;
          line-height: 1.33;
          word-break: keep-all;
        }

        .project-compact-progress {
          height: 8px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.18);
        }

        .project-compact-progress span {
          display: block;
          width: calc(var(--pct) * 1%);
          height: 100%;
          border-radius: inherit;
          background: #3eeadf;
        }

        .project-compact-meta {
          display: grid;
          grid-template-columns: 1fr 0.72fr;
          gap: 8px;
          margin: 12px 0 10px;
        }

        .project-compact-meta div {
          min-width: 0;
          padding: 9px 10px;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.12);
        }

        .project-compact-meta dt {
          margin: 0 0 4px;
          color: rgba(255, 255, 255, 0.64);
          font-size: 11px;
          font-weight: 900;
        }

        .project-compact-meta dd {
          margin: 0;
          overflow: hidden;
          color: #fff;
          font-size: 12px;
          font-weight: 900;
          line-height: 1.25;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-status {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 10px;
          padding: 8px 10px;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.12);
        }

        .project-compact-status span {
          color: #fff;
          font-size: 13px;
          font-weight: 900;
          white-space: nowrap;
        }

        .project-compact-status em {
          overflow: hidden;
          color: rgba(255, 255, 255, 0.7);
          font-size: 11px;
          font-style: normal;
          font-weight: 800;
          text-align: right;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-card p {
          display: -webkit-box;
          min-height: 34px;
          margin: 0;
          overflow: hidden;
          color: rgba(255, 255, 255, 0.82);
          font-size: 12px;
          font-weight: 800;
          line-height: 1.42;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
          word-break: keep-all;
        }

        .project-card,
        .project-card:nth-child(4n+2),
        .project-card:nth-child(4n+3),
        .project-card:nth-child(4n),
        .project-compact-card,
        .project-compact-card:nth-child(4n+2),
        .project-compact-card:nth-child(4n+3),
        .project-compact-card:nth-child(4n) {
          background: #fff;
          color: #17212b;
          border: 1px solid #dfe6ef;
          border-top: 5px solid #3578e5;
          box-shadow: 0 14px 30px rgba(27, 39, 61, 0.08);
        }

        .project-card:nth-child(3n+2),
        .project-compact-card:nth-child(3n+2) {
          border-top-color: #00a3a3;
        }

        .project-card:nth-child(3n),
        .project-compact-card:nth-child(3n) {
          border-top-color: #f06a43;
        }

        .project-card h3,
        .project-compact-card h3 {
          color: #0f172a;
          text-shadow: none;
        }

        .project-card h3 {
          min-height: 54px;
          font-size: 25px;
          line-height: 1.28;
        }

        .project-card-head {
          flex-wrap: wrap;
        }

        .project-number,
        .project-compact-number {
          background: #edf4ff;
          border-color: #b8cef7;
          color: #2563eb;
        }

        .project-field,
        .project-compact-field {
          background: #f3f6fb;
          color: #516176;
        }

        .project-risk.risk-normal {
          background: #dffcf6;
          color: #00766e;
        }

        .project-risk.risk-watch {
          background: #fff5cc;
          color: #8a6100;
        }

        .project-risk.risk-delay {
          background: #ffe5e2;
          color: #b42318;
        }

        .project-stage-badge {
          min-width: 92px;
          padding: 10px 12px;
          border-radius: 16px;
          background: #f5f8fc;
          border: 1px solid #dbe5f0;
          text-align: center;
        }

        .project-stage-badge span {
          display: block;
          margin-bottom: 3px;
          color: #6a7788;
          font-size: 12px;
          font-weight: 900;
        }

        .project-stage-badge strong {
          color: #2563eb;
          font-size: 23px;
          font-weight: 950;
        }

        .project-meta div,
        .project-check-row,
        .project-compact-meta div,
        .project-compact-status {
          background: #f7f9fc;
          border: 1px solid #e3ebf4;
        }

        .project-meta dt,
        .project-milestone span,
        .project-compact-meta dt {
          color: #6b7788;
        }

        .project-meta dd,
        .project-check-row strong,
        .project-milestone strong,
        .project-compact-meta dd,
        .project-compact-status span {
          color: #17212b;
        }

        .project-feature {
          min-height: 0;
          color: #536273;
        }

        .project-section-label {
          margin: 4px 0 9px;
          color: #26364a;
          font-size: 14px;
          font-weight: 950;
        }

        .project-stage {
          grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
          gap: 7px;
          position: relative;
        }

        .project-stage span {
          min-height: 34px;
          background: #f3f6fb;
          border: 1px solid #dfe7f0;
          color: #617086;
          font-size: 12px;
        }

        .project-stage span.is-done {
          background: #e7fbf6;
          border-color: #91eadb;
          color: #00796f;
        }

        .project-stage span.is-current {
          background: #2563eb;
          border-color: #2563eb;
          color: #fff;
          box-shadow: 0 8px 16px rgba(37, 99, 235, 0.2);
        }

        .project-check-row {
          padding: 11px 13px;
        }

        .project-check-row span,
        .project-updated,
        .project-compact-status em {
          color: #6b7788;
        }

        .project-metric-panel {
          margin: 14px 0;
          padding: 16px;
          border-radius: 18px;
          background: linear-gradient(180deg, #f8fbff 0%, #f2f6fb 100%);
          border: 1px solid #dfe8f4;
        }

        .project-metric-main {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: end;
          gap: 10px;
          margin-bottom: 6px;
        }

        .project-metric-main span,
        .project-metric-target span {
          display: block;
          color: #6a7788;
          font-size: 12px;
          font-weight: 950;
        }

        .project-metric-main strong {
          display: block;
          color: #2563eb;
          font-size: clamp(28px, 3.2vw, 46px);
          font-weight: 950;
          line-height: 1.05;
          letter-spacing: 0;
          white-space: nowrap;
        }

        .project-metric-main strong.is-waiting {
          color: #8a98aa;
          font-size: 30px;
        }

        .project-metric-main em {
          grid-column: 1 / -1;
          color: #27364a;
          font-size: 14px;
          font-style: normal;
          font-weight: 900;
        }

        .project-metric-target {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          margin: 4px 0 8px;
          color: #17212b;
        }

        .project-metric-target strong {
          color: #17212b;
          font-size: 15px;
          font-weight: 950;
          text-align: right;
        }

        .project-metric-target em {
          min-width: 72px;
          padding: 5px 8px;
          border-radius: 999px;
          background: #e8f1ff;
          color: #2563eb;
          font-size: 13px;
          font-style: normal;
          font-weight: 950;
          text-align: center;
        }

        .project-progress-line {
          height: 12px;
          overflow: hidden;
          border-radius: 999px;
          background: #dfe7f0;
        }

        .project-progress-line span {
          display: block;
          width: calc(var(--pct) * 1%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, #2dd4bf 0%, #2563eb 100%);
        }

        .project-metric-rows {
          display: grid;
          gap: 7px;
          margin-top: 12px;
        }

        .metric-row {
          display: grid;
          grid-template-columns: minmax(0, 1.2fr) auto auto auto;
          align-items: center;
          gap: 8px;
          padding: 7px 9px;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.78);
          border: 1px solid #e4ebf4;
        }

        .metric-row span {
          min-width: 0;
          overflow: hidden;
          color: #506075;
          font-size: 12px;
          font-weight: 900;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .metric-row strong {
          color: #0f172a;
          font-size: 13px;
          font-weight: 950;
          white-space: nowrap;
        }

        .metric-row em {
          color: #7a8798;
          font-size: 11px;
          font-style: normal;
          font-weight: 850;
          white-space: nowrap;
        }

        .metric-row b {
          color: #2563eb;
          font-size: 12px;
          font-weight: 950;
          white-space: nowrap;
        }

        .project-milestone {
          border-top-color: #e1e8f0;
        }

        .project-compact-top {
          grid-template-columns: 34px minmax(0, 1fr) auto;
        }

        .project-compact-top strong {
          max-width: 96px;
          overflow: hidden;
          padding: 6px 9px;
          border-radius: 999px;
          background: #eef5ff;
          color: #2563eb;
          font-size: 12px;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-card h3 {
          color: #0f172a;
        }

        .project-compact-metric {
          margin: 8px 0 10px;
        }

        .project-compact-metric span {
          display: block;
          color: #6a7788;
          font-size: 11px;
          font-weight: 950;
        }

        .project-compact-metric strong {
          display: block;
          overflow: hidden;
          color: #2563eb;
          font-size: 24px;
          font-weight: 950;
          line-height: 1.12;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-metric em,
        .project-compact-pct {
          display: block;
          color: #6b7788;
          font-size: 11px;
          font-style: normal;
          font-weight: 850;
        }

        .project-compact-progress {
          background: #dfe7f0;
        }

        .project-compact-progress span {
          background: linear-gradient(90deg, #2dd4bf 0%, #2563eb 100%);
        }

        .project-compact-pct {
          margin-top: 4px;
          text-align: right;
        }

        .project-compact-card p {
          color: #5b697a;
        }

        .project-board.compact {
          position: relative;
          width: calc(100vw - 18px);
          max-width: none;
          margin: 0 calc(50% - 50vw + 9px) 0;
          padding: 8px 26px 12px;
          overflow: visible;
          border: 1px solid #d3e3f1;
          border-radius: 24px;
          background:
            radial-gradient(circle at 80% 6%, rgba(255, 255, 255, 0.95) 0 8%, rgba(255, 255, 255, 0) 22%),
            linear-gradient(180deg, #f2f8fd 0%, #e5f0f8 100%);
          box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.9),
            0 20px 46px rgba(34, 58, 92, 0.11);
        }

        .project-board.compact .project-summary,
        .project-board.compact .project-flow {
          display: none;
        }

        .project-board.compact .project-board-head {
          position: relative;
          display: grid;
          grid-template-columns: minmax(280px, 0.7fr) minmax(620px, 1.15fr) minmax(238px, 0.6fr);
          align-items: center;
          min-height: 96px;
          padding: 0 0 4px;
          margin-bottom: 0;
          text-align: center;
        }

        .project-board.compact .project-board-head h2 {
          font-size: clamp(42px, 3vw, 56px);
          letter-spacing: 0;
        }

        .project-title-art {
          position: relative;
          display: inline-flex;
          min-height: 68px;
          align-items: center;
          justify-content: center;
          isolation: isolate;
          max-width: 100%;
          overflow: hidden;
          padding: 0 22px;
          text-align: center;
          white-space: nowrap;
        }

        .project-title-art::before {
          content: "";
          position: absolute;
          z-index: -1;
          top: 50%;
          left: 50%;
          width: min(820px, 100%);
          height: 54px;
          transform: translate(-50%, -50%);
          background:
            linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.88) 14%, rgba(255,255,255,0.92) 86%, rgba(255,255,255,0) 100%),
            radial-gradient(circle at 10px 10px, rgba(68, 101, 153, 0.17) 0 1.6px, transparent 2px) 0 0 / 17px 17px;
          opacity: 0.8;
          pointer-events: none;
        }

        .project-title-art strong {
          position: relative;
          z-index: 1;
          display: inline-block;
          color: #061f53;
          font-size: clamp(42px, 3.2vw, 58px);
          font-weight: 950;
          letter-spacing: 0;
          line-height: 1.05;
          text-shadow: 0 4px 12px rgba(8, 45, 103, 0.12);
        }

        .project-title-art.image-title {
          width: min(780px, 54vw);
          height: clamp(72px, 6vw, 96px);
          min-height: 0;
          padding: 0;
          border-radius: 18px;
          background: #0b214f;
          box-shadow: 0 18px 36px rgba(7, 26, 61, 0.14);
        }

        .project-title-art.image-title::before {
          display: none;
        }

        .project-title-image {
          display: block;
          width: 100%;
          height: 100%;
          object-fit: cover;
          object-position: center;
        }

        .project-board-spacer {
          min-width: 210px;
        }

        .project-board.compact .project-head-actions {
          position: static;
          justify-content: flex-end;
        }

        .project-overall-progress {
          position: relative;
          display: inline-flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          width: 116px;
          height: 116px;
          min-width: 116px;
          padding: 0;
          border: 1px solid #cddfed;
          border-radius: 999px;
          background:
            radial-gradient(circle, rgba(255, 255, 255, 0.98) 0 61%, transparent 62%),
            conic-gradient(#11b884 calc(var(--pct) * 1%), #d8edf4 0);
          box-shadow: 0 18px 32px rgba(36, 62, 99, 0.14);
        }

        .project-overall-progress span {
          color: #1f2937;
          font-size: 13px;
          font-weight: 950;
          line-height: 1.2;
          white-space: nowrap;
        }

        .project-overall-progress strong {
          color: #0f172a;
          font-size: 27px;
          font-weight: 950;
          line-height: 1.05;
          white-space: nowrap;
        }

        .project-overall-progress em {
          color: #344256;
          max-width: none;
          font-size: 11px;
          font-style: normal;
          font-weight: 950;
          line-height: 1.2;
          text-align: center;
          white-space: nowrap;
        }

        .project-compact-grid {
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 11px;
        }

        .project-compact-card,
        .project-compact-card:nth-child(4n+2),
        .project-compact-card:nth-child(4n+3),
        .project-compact-card:nth-child(4n),
        .project-compact-card:nth-child(3n+2),
        .project-compact-card:nth-child(3n) {
          position: relative;
          height: 426px;
          min-height: 426px;
          padding: 14px 15px 13px;
          overflow: visible;
          border: 1px solid #dce7f1;
          border-top: 0;
          border-radius: 18px;
          background: rgba(255, 255, 255, 0.96);
          color: #142033;
          box-shadow: 0 14px 28px rgba(37, 59, 93, 0.1);
        }

        .project-compact-card:focus {
          outline: 3px solid rgba(37, 99, 235, 0.24);
          outline-offset: 3px;
        }

        .project-compact-card h3 {
          display: flex;
          min-height: 36px;
          align-items: flex-start;
          gap: 5px;
          margin: 0 0 4px;
          color: #162236;
          font-size: clamp(16px, 0.94vw, 18px);
          font-weight: 950;
          line-height: 1.08;
          word-break: keep-all;
        }

        .project-compact-card h3 span {
          flex: 0 0 auto;
          color: #0f376f;
          font-size: 20px;
          font-weight: 950;
          line-height: 1.08;
        }

        .project-compact-card h3 strong {
          display: -webkit-box;
          min-width: 0;
          overflow: hidden;
          font-weight: 950;
          letter-spacing: -0.01em;
          text-overflow: ellipsis;
          word-break: keep-all;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
        }

        .project-compact-card h3 .project-title-sub {
          display: inline-block;
          margin-top: 1px;
          color: inherit;
          font: inherit;
          font-size: inherit;
          font-weight: inherit;
          letter-spacing: inherit;
          line-height: inherit;
        }

        .project-compact-card.project-P010 h3 {
          gap: 3px;
        }

        .project-compact-card.project-P010 h3 span {
          font-size: 17px;
        }

        .project-compact-card.project-P010 h3 strong {
          display: block;
          overflow: hidden;
          font-size: clamp(14px, 0.78vw, 15.5px);
          letter-spacing: -0.055em;
          text-overflow: ellipsis;
          white-space: nowrap;
          -webkit-line-clamp: unset;
        }

        .project-compact-kpi {
          display: grid;
          gap: 4px;
          margin: 0 0 5px;
          padding: 6px 8px 6px;
          border: 1px solid #c9dcf0;
          border-radius: 13px;
          background:
            linear-gradient(180deg, rgba(225, 239, 255, 0.98) 0%, rgba(205, 231, 255, 0.96) 100%);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92), 0 8px 18px rgba(34, 75, 130, 0.12);
          text-align: center;
        }

        .project-compact-kpi-item {
          min-width: 0;
          padding: 4px 6px 5px;
          border: 1px solid rgba(32, 114, 184, 0.2);
          border-radius: 10px;
          background: #f8fbff;
          box-shadow: 0 4px 10px rgba(37, 99, 235, 0.08);
        }

        .project-compact-kpi-item:nth-child(2) {
          border-color: rgba(0, 137, 123, 0.24);
          background: #f3fffb;
        }

        .project-compact-kpi-item:nth-child(3) {
          border-color: rgba(104, 73, 196, 0.24);
          background: #fbf8ff;
        }

        .project-compact-kpi-item:nth-child(4) {
          border-color: rgba(217, 119, 6, 0.24);
          background: #fffaf0;
        }

        .project-compact-kpi-item:last-child {
          padding-bottom: 5px;
        }

        .project-compact-kpi-name {
          display: inline-flex;
          min-width: min(100%, 136px);
          align-items: center;
          justify-content: center;
          overflow: hidden;
          padding: 4px 9px;
          border: 1px solid rgba(31, 93, 168, 0.26);
          border-radius: 999px;
          background: linear-gradient(135deg, #0b4a96 0%, #167bd1 100%);
          color: #ffffff;
          font-size: 12px;
          font-weight: 950;
          line-height: 1;
          box-shadow: 0 5px 12px rgba(15, 76, 154, 0.18);
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-kpi-item:nth-child(2) .project-compact-kpi-name {
          border-color: rgba(0, 121, 107, 0.3);
          background: linear-gradient(135deg, #00796b 0%, #00b894 100%);
          box-shadow: 0 5px 12px rgba(0, 137, 123, 0.18);
        }

        .project-compact-kpi-item:nth-child(3) .project-compact-kpi-name {
          border-color: rgba(104, 73, 196, 0.3);
          background: linear-gradient(135deg, #5b3fb4 0%, #8b5cf6 100%);
          box-shadow: 0 5px 12px rgba(104, 73, 196, 0.18);
        }

        .project-compact-kpi-item:nth-child(4) .project-compact-kpi-name {
          border-color: rgba(217, 119, 6, 0.3);
          background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%);
          box-shadow: 0 5px 12px rgba(217, 119, 6, 0.18);
        }

        .project-compact-kpi-values {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 4px;
          margin-top: 3px;
        }

        .project-compact-kpi-values p {
          margin: 0;
          min-width: 0;
          overflow: hidden;
          padding: 4px 6px 5px;
          border-radius: 8px;
          background: #dcecff;
          text-align: left;
        }

        .project-compact-kpi-values p:last-child {
          background: #d9f8ef;
        }

        .project-compact-kpi-item:nth-child(2) .project-compact-kpi-values p {
          background: #dff7f1;
        }

        .project-compact-kpi-item:nth-child(2) .project-compact-kpi-values p:last-child {
          background: #d7f3ff;
        }

        .project-compact-kpi-item:nth-child(3) .project-compact-kpi-values p {
          background: #eee7ff;
        }

        .project-compact-kpi-item:nth-child(3) .project-compact-kpi-values p:last-child {
          background: #f6e6ff;
        }

        .project-compact-kpi-item:nth-child(4) .project-compact-kpi-values p {
          background: #fff0c7;
        }

        .project-compact-kpi-item:nth-child(4) .project-compact-kpi-values p:last-child {
          background: #ffe8d0;
        }

        .project-compact-kpi-values b {
          display: block;
          margin-bottom: 2px;
          color: #2d5e9c;
          font-size: 12.5px;
          font-weight: 950;
          line-height: 1;
        }

        .project-compact-kpi-values p:last-child b {
          color: #087968;
        }

        .project-compact-kpi-values strong {
          display: -webkit-box;
          overflow: hidden;
          color: #111827;
          font-size: 12.5px;
          font-weight: 950;
          line-height: 1.08;
          white-space: normal;
          word-break: keep-all;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
        }

        .project-compact-kpi em {
          display: inline-flex;
          margin-top: 3px;
          padding: 3px 7px;
          border-radius: 999px;
          background: #173b75;
          color: #ffffff;
          font-size: 10px;
          font-style: normal;
          font-weight: 950;
          line-height: 1;
          box-shadow: 0 5px 10px rgba(23, 59, 117, 0.18);
        }

        .project-compact-kpi i {
          display: block;
          position: relative;
          height: 8px;
          margin-top: 4px;
          overflow: hidden;
          border: 1px solid rgba(15, 55, 111, 0.16);
          border-radius: 999px;
          background:
            linear-gradient(90deg, rgba(239, 68, 68, 0.22) 0%, rgba(245, 158, 11, 0.24) 45%, rgba(16, 185, 129, 0.28) 100%),
            #d5e3f0;
          box-shadow:
            inset 0 1px 2px rgba(15, 35, 70, 0.2),
            0 3px 7px rgba(31, 128, 255, 0.1);
        }

        .project-compact-kpi i b {
          display: block;
          width: max(7px, calc(var(--metric-pct) * 1%));
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, #0056d6 0%, #00b8ff 48%, #00d084 100%);
          box-shadow:
            0 0 12px rgba(31, 128, 255, 0.5),
            inset 0 1px 0 rgba(255, 255, 255, 0.4);
        }

        .project-compact-kpi-item:nth-child(2) i b {
          background: linear-gradient(90deg, #00897b 0%, #00d084 100%);
          box-shadow: 0 0 12px rgba(0, 137, 123, 0.48);
        }

        .project-compact-kpi-item:nth-child(3) i b {
          background: linear-gradient(90deg, #5b3fb4 0%, #a855f7 100%);
          box-shadow: 0 0 12px rgba(104, 73, 196, 0.45);
        }

        .project-compact-kpi-item:nth-child(4) i b {
          background: linear-gradient(90deg, #d97706 0%, #f97316 100%);
          box-shadow: 0 0 12px rgba(217, 119, 6, 0.42);
        }

        .project-compact-main {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 58px;
          gap: 7px;
          align-items: start;
          margin-bottom: 5px;
        }

        .project-compact-donut {
          display: inline-flex;
          justify-self: end;
          height: 58px;
          width: 58px;
          align-items: center;
          justify-content: center;
          flex-direction: column;
          border-radius: 999px;
          background:
            radial-gradient(circle, #fff 0 53%, transparent 54%),
            conic-gradient(#0aa6a4 calc(var(--pct) * 1%), #d9ebef 0);
          box-shadow: inset 0 0 0 1px rgba(13, 117, 128, 0.08);
        }

        .project-compact-donut span {
          color: #4b596b;
          font-size: 9px;
          font-weight: 950;
          line-height: 1.1;
        }

        .project-compact-donut strong {
          color: #111827;
          font-size: 18px;
          font-weight: 950;
          line-height: 1.05;
        }

        .project-compact-info {
          min-width: 0;
          justify-self: end;
          width: 100%;
          padding: 6px 9px;
          border-radius: 13px;
          background: #f3f8fc;
        }

        .project-compact-info em {
          display: inline-flex;
          max-width: 100%;
          margin-bottom: 3px;
          padding: 3px 8px;
          overflow: hidden;
          border-radius: 999px;
          background: #00a7a3;
          color: #fff;
          font-size: 10.5px;
          font-style: normal;
          font-weight: 950;
          line-height: 1.2;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-card.field-smallbiz .project-compact-info em {
          background: linear-gradient(135deg, #009c96 0%, #00b8a9 100%);
          box-shadow: 0 5px 10px rgba(0, 156, 150, 0.18);
        }

        .project-compact-card.field-burden .project-compact-info em {
          background: linear-gradient(135deg, #e85d34 0%, #ff9f1c 100%);
          box-shadow: 0 5px 10px rgba(232, 93, 52, 0.18);
        }

        .project-compact-card.field-safety .project-compact-info em {
          background: linear-gradient(135deg, #1957c2 0%, #5b6ee1 100%);
          box-shadow: 0 5px 10px rgba(25, 87, 194, 0.18);
        }

        .project-compact-info p {
          display: block;
          min-height: 0;
          margin: 1px 0;
          color: #26364c;
          font-size: 11px;
          font-weight: 850;
          line-height: 1.2;
          white-space: normal;
          word-break: keep-all;
          -webkit-line-clamp: unset;
        }

        .project-compact-info p.project-compact-department {
          display: -webkit-box;
          overflow: hidden;
          line-height: 1.22;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
        }

        .project-compact-info p b {
          display: inline-block;
          min-width: 44px;
          margin-right: 5px;
          color: #718096;
          font-weight: 950;
        }

        .project-compact-info p.project-compact-current {
          color: #111827;
          font-size: 17px;
          font-weight: 950;
        }

        .project-compact-meta {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 8px;
          align-items: center;
          margin: 8px 0 8px;
          padding: 8px 10px;
          border-radius: 12px;
          background: #f1f7fb;
        }

        .project-compact-meta span,
        .project-compact-meta strong {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-meta span {
          color: #536376;
          font-size: 13px;
          font-weight: 950;
        }

        .project-compact-meta strong {
          color: #102033;
          font-size: 13px;
          font-weight: 950;
        }

        .project-compact-budget {
          min-height: 18px;
          margin-bottom: 9px;
          overflow: hidden;
          color: #334155;
          font-size: 12px;
          font-weight: 850;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-compact-stage-title {
          margin: 0 0 6px;
          color: #142033;
          font-size: 15px;
          font-weight: 950;
        }

        .project-compact-steps {
          padding: 0 1px;
          margin-top: -1px;
        }

        .project-compact-step-track {
          position: relative;
          height: 6px;
          overflow: hidden;
          border-radius: 999px;
          background: #dce7ee;
        }

        .project-compact-step-track span {
          display: block;
          width: calc(var(--pct) * 1%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, #25c3bd 0%, #1b93cf 100%);
        }

        .project-compact-step-labels {
          display: grid;
          gap: 2px;
          margin-top: 4px;
        }

        .project-compact-step {
          position: relative;
          padding-top: 6px;
          color: #145fc7;
          font-size: 10px;
          font-weight: 950;
          line-height: 1.04;
          text-align: center;
          word-break: keep-all;
        }

        .project-compact-step::before {
          content: "";
          position: absolute;
          top: -1px;
          left: 50%;
          width: 9px;
          height: 9px;
          transform: translateX(-50%);
          border: 1.5px solid #b8cad7;
          border-radius: 999px;
          background: #fff;
        }

        .project-compact-step.is-done::before,
        .project-compact-step.is-current::before {
          border-color: #18aaa6;
          background: #18aaa6;
          box-shadow: 0 0 0 3px rgba(24, 170, 166, 0.16);
        }

        .project-compact-step.is-current {
          color: #003f9e;
          font-weight: 950;
        }

        .project-compact-step.is-current::after {
          content: "";
          position: absolute;
          left: 50%;
          top: -13px;
          width: 0;
          height: 0;
          transform: translateX(-50%);
          border-left: 5px solid transparent;
          border-right: 5px solid transparent;
          border-top: 7px solid #0070d2;
        }

        .project-hover-detail {
          position: absolute;
          z-index: 50;
          left: 50%;
          top: calc(100% - 20px);
          width: min(480px, calc(100vw - 96px));
          max-height: min(72vh, 680px);
          padding: 18px;
          overflow: auto;
          border: 1px solid #cbdbea;
          border-radius: 20px;
          background: rgba(255, 255, 255, 0.98);
          box-shadow: 0 26px 64px rgba(15, 31, 54, 0.22);
          opacity: 0;
          pointer-events: none;
          transform: translate(-50%, 14px) scale(0.985);
          transition: opacity 160ms ease, transform 160ms ease;
        }

        .project-compact-card:hover,
        .project-compact-card:focus-within {
          z-index: 20;
        }

        .project-compact-card:hover .project-hover-detail,
        .project-compact-card:focus .project-hover-detail,
        .project-compact-card:focus-within .project-hover-detail {
          opacity: 1;
          pointer-events: auto;
          transform: translate(-50%, 0) scale(1);
        }

        .project-compact-card:nth-child(n+6) .project-hover-detail {
          top: auto;
          bottom: calc(100% - 20px);
          transform: translate(-50%, -14px) scale(0.985);
        }

        .project-compact-card:nth-child(n+6):hover .project-hover-detail,
        .project-compact-card:nth-child(n+6):focus .project-hover-detail,
        .project-compact-card:nth-child(n+6):focus-within .project-hover-detail {
          transform: translate(-50%, 0) scale(1);
        }

        .project-hover-head {
          display: flex;
          align-items: center;
          gap: 9px;
          margin-bottom: 12px;
        }

        .project-hover-head span {
          display: inline-flex;
          width: 32px;
          height: 32px;
          align-items: center;
          justify-content: center;
          border-radius: 999px;
          background: #e4f3f7;
          color: #087078;
          font-size: 13px;
          font-weight: 950;
        }

        .project-hover-head strong {
          color: #0f172a;
          font-size: 18px;
          font-weight: 950;
        }

        .project-hover-meta {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          margin: 0 0 10px;
        }

        .project-hover-meta div {
          min-width: 0;
          padding: 10px 11px;
          border-radius: 12px;
          background: #f1f7fb;
        }

        .project-hover-meta dt {
          margin: 0 0 4px;
          color: #64748b;
          font-size: 11px;
          font-weight: 950;
        }

        .project-hover-meta dd {
          margin: 0;
          overflow: hidden;
          color: #0f172a;
          font-size: 13px;
          font-weight: 900;
          line-height: 1.28;
          white-space: normal;
          word-break: keep-all;
        }

        .project-hover-feature {
          margin: 0 0 12px;
          color: #334155;
          font-size: 13px;
          font-weight: 800;
          line-height: 1.45;
          word-break: keep-all;
        }

        .project-hover-label {
          margin: 12px 0 7px;
          color: #0f172a;
          font-size: 13px;
          font-weight: 950;
        }

        .project-hover-stage {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .project-hover-stage span {
          padding: 6px 8px;
          border: 1px solid #d7e3ee;
          border-radius: 999px;
          background: #f6f9fc;
          color: #5f6f82;
          font-size: 11px;
          font-weight: 900;
          line-height: 1;
        }

        .project-hover-stage span.is-done {
          border-color: #9fe2df;
          background: #e8fbfa;
          color: #08706f;
        }

        .project-hover-stage span.is-current {
          border-color: #1aa8a4;
          background: #1aa8a4;
          color: #fff;
        }

        .project-hover-status {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          gap: 8px;
          align-items: center;
          margin-top: 10px;
          padding: 10px 11px;
          border-radius: 12px;
          background: #eef8f8;
        }

        .project-hover-status strong {
          color: #08706f;
          font-size: 13px;
          font-weight: 950;
          white-space: nowrap;
        }

        .project-hover-status span {
          overflow: hidden;
          color: #334155;
          font-size: 12px;
          font-weight: 850;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-hover-metrics {
          display: grid;
          gap: 7px;
        }

        .project-hover-metrics .metric-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 4px 10px;
          padding: 9px 10px;
          border-radius: 12px;
          background: #f7fafc;
        }

        .project-hover-metrics .metric-row span {
          overflow: hidden;
          color: #475569;
          font-size: 12px;
          font-weight: 900;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .project-hover-metrics .metric-row strong {
          color: #0f172a;
          font-size: 12px;
          font-weight: 950;
          white-space: nowrap;
        }

        .project-hover-metrics .metric-row em {
          color: #64748b;
          font-size: 11px;
          font-style: normal;
          font-weight: 800;
        }

        .project-hover-metrics .metric-row b {
          color: #2563eb;
          font-size: 11px;
          font-weight: 950;
          text-align: right;
        }

        .project-hover-text {
          margin-top: 10px;
          padding: 10px 11px;
          border-radius: 12px;
          background: #f7fafc;
        }

        .project-hover-text span {
          display: block;
          margin-bottom: 5px;
          color: #64748b;
          font-size: 11px;
          font-weight: 950;
        }

        .project-hover-text strong {
          display: block;
          color: #0f172a;
          font-size: 12px;
          font-weight: 900;
          line-height: 1.45;
          word-break: keep-all;
        }

        .project-board.compact .project-source {
          margin-top: 20px;
          color: #697a8d;
          font-size: 12px;
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

        .display-board-page {
          width: 100%;
          min-width: 1500px;
          margin: 0;
          background: linear-gradient(180deg, #dcebff 0%, #eff7ff 42%, #e8f4ff 100%);
          color: #07142b;
          font-family: var(--font-kr);
          overflow-x: auto;
        }

        .display-hero {
          position: relative;
          min-height: 244px;
          display: grid;
          grid-template-columns: minmax(700px, 1fr) minmax(420px, 540px) 250px;
          align-items: end;
          gap: 24px;
          padding: 30px 34px 0;
          box-sizing: border-box;
          color: #fff;
          background:
            radial-gradient(circle at 78% 18%, rgba(0, 212, 255, 0.28), transparent 30%),
            radial-gradient(circle at 24% 80%, rgba(0, 101, 235, 0.42), transparent 35%),
            linear-gradient(120deg, #087fc3 0%, #0063db 50%, #0600d7 100%);
          overflow: hidden;
        }

        .display-hero::before {
          content: "";
          position: absolute;
          right: 17%;
          top: -150px;
          width: 450px;
          height: 450px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.08);
          filter: blur(2px);
        }

        .display-hero::after {
          content: "";
          position: absolute;
          left: 0;
          right: 0;
          bottom: 0;
          height: 1px;
          background: rgba(255, 255, 255, 0.55);
        }

        .display-hero-copy,
        .display-hero-progress,
        .display-hero-brand {
          position: relative;
          z-index: 1;
        }

        .display-hero-copy {
          align-self: stretch;
          display: flex;
          flex-direction: column;
          justify-content: center;
          gap: 24px;
          padding-bottom: 0;
        }

        .display-hero-copy h1 {
          margin: 0;
          color: #fff;
          font-size: clamp(42px, 4.1vw, 64px);
          font-weight: 950;
          line-height: 1.05;
          letter-spacing: -0.02em;
          word-break: keep-all;
          white-space: nowrap;
          text-shadow: 0 6px 20px rgba(0, 0, 0, 0.20);
        }

        .display-dday-card {
          width: 230px;
          height: 84px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 12px 12px 0 0;
          background: #edf4ff;
          color: #111b39;
          font-size: 48px;
          font-weight: 950;
          line-height: 1;
          letter-spacing: -0.02em;
          box-shadow: 0 18px 38px rgba(0, 23, 69, 0.20);
        }

        .display-hero-progress {
          min-height: 178px;
          display: grid;
          grid-template-columns: 132px minmax(0, 1fr);
          align-items: end;
          gap: 12px;
          padding-bottom: 18px;
        }

        .display-overall-label {
          color: #fff;
          font-size: 19px;
          font-weight: 900;
          text-align: right;
          white-space: nowrap;
          text-shadow: 0 3px 12px rgba(0, 0, 0, 0.22);
        }

        .display-overall-gauge {
          position: relative;
          width: min(390px, 25vw);
          height: min(195px, 12.5vw);
          min-width: 330px;
          min-height: 165px;
          overflow: hidden;
        }

        .display-overall-gauge::before {
          content: "";
          position: absolute;
          inset: 0;
          border-radius: 520px 520px 0 0;
          background:
            conic-gradient(
              from 270deg at 50% 100%,
              #ecf4ff 0deg,
              #ecf4ff 42deg,
              rgba(255, 255, 255, 0.16) 42deg,
              rgba(255, 255, 255, 0.16) 180deg,
              transparent 180deg
            );
          -webkit-mask:
            radial-gradient(circle at 50% 100%, transparent 0 48%, #000 49% 66%, transparent 67%);
          mask:
            radial-gradient(circle at 50% 100%, transparent 0 48%, #000 49% 66%, transparent 67%);
        }

        .display-overall-gauge::after {
          content: "";
          position: absolute;
          left: 0;
          bottom: 0;
          width: 100%;
          height: 100%;
          border-radius: 520px 520px 0 0;
          background:
            conic-gradient(
              from 270deg at 50% 100%,
              #17b690 0deg,
              #287cff var(--arc-deg),
              transparent var(--arc-deg),
              transparent 180deg
            );
          -webkit-mask:
            radial-gradient(circle at 50% 100%, transparent 0 48%, #000 49% 66%, transparent 67%);
          mask:
            radial-gradient(circle at 50% 100%, transparent 0 48%, #000 49% 66%, transparent 67%);
        }

        .display-overall-gauge strong {
          position: absolute;
          left: 50%;
          bottom: 16px;
          transform: translateX(-50%);
          color: #fff;
          font-size: 62px;
          font-weight: 950;
          line-height: 1;
          letter-spacing: -0.02em;
          text-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
          z-index: 2;
        }

        .display-hero-brand {
          align-self: start;
          justify-self: end;
          margin-top: 6px;
          text-align: right;
          color: #fff;
          text-shadow: 0 3px 14px rgba(0, 0, 0, 0.22);
        }

        .display-hero-brand span,
        .display-hero-brand strong {
          display: block;
          white-space: nowrap;
        }

        .display-hero-brand span {
          font-size: 17px;
          font-weight: 900;
        }

        .display-hero-brand strong {
          margin-top: 3px;
          font-size: 24px;
          font-weight: 950;
          line-height: 1.1;
        }

        .display-card-zone {
          padding: 20px 34px 22px;
          background:
            linear-gradient(90deg, rgba(255, 255, 255, 0.35), rgba(255, 255, 255, 0)),
            #eaf4ff;
        }

        .display-project-grid {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 18px 22px;
          width: 100%;
        }

        .display-project-card {
          min-height: 348px;
          padding: 24px 26px 22px;
          border-radius: 12px;
          background: #fff;
          box-shadow: 0 18px 34px rgba(26, 69, 121, 0.13);
          box-sizing: border-box;
        }

        .display-project-card h3 {
          min-height: 68px;
          margin: 0 0 10px;
          color: #050d1b;
          font-size: clamp(22px, 1.45vw, 29px);
          font-weight: 950;
          line-height: 1.23;
          letter-spacing: -0.02em;
          word-break: keep-all;
        }

        .display-card-gauge {
          position: relative;
          width: 176px;
          height: 88px;
          margin: 0 auto 6px;
          overflow: hidden;
        }

        .display-card-gauge::before,
        .display-card-gauge::after {
          content: "";
          position: absolute;
          inset: 0;
          border-radius: 230px 230px 0 0;
        }

        .display-card-gauge::before {
          background:
            conic-gradient(
              from 270deg at 50% 100%,
              #18b58f 0deg,
              #237cff var(--arc-deg),
              #e9f1fc var(--arc-deg),
              #e9f1fc 180deg,
              transparent 180deg
            );
        }

        .display-card-gauge::after {
          left: 26px;
          right: 26px;
          top: 26px;
          bottom: -1px;
          border-radius: 168px 168px 0 0;
          background: #fff;
        }

        .display-card-gauge-value {
          position: absolute;
          left: 50%;
          bottom: -1px;
          transform: translateX(-50%);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: flex-end;
          z-index: 2;
        }

        .display-card-gauge-value span {
          color: #8a95a5;
          font-size: 13px;
          font-weight: 850;
          white-space: nowrap;
        }

        .display-card-gauge-value strong {
          color: #2478f2;
          font-size: 40px;
          font-weight: 950;
          line-height: 0.94;
          letter-spacing: -0.02em;
        }

        .display-card-divider {
          height: 2px;
          margin: 6px 0 10px;
          background: #e7eef7;
        }

        .display-card-metrics {
          display: grid;
          gap: 8px;
        }

        .display-metric-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 10px;
          align-items: end;
        }

        .display-metric-row strong,
        .display-metric-row span,
        .display-metric-row em {
          display: block;
        }

        .display-metric-row strong {
          color: #050d1b;
          font-size: 13px;
          font-weight: 950;
          line-height: 1.26;
          word-break: keep-all;
        }

        .display-metric-row em {
          margin-top: 1px;
          color: #9aa5b5;
          font-size: 9px;
          font-style: normal;
          font-weight: 800;
        }

        .display-metric-row span {
          margin-top: 2px;
          color: #111827;
          font-size: 15px;
          font-weight: 850;
          line-height: 1.15;
          word-break: keep-all;
        }

        .display-metric-row b {
          color: #2478f2;
          font-size: 22px;
          font-weight: 950;
          line-height: 1;
          white-space: nowrap;
          text-align: right;
        }

        .display-board-page {
          min-width: 1360px;
          min-height: 100vh;
          overflow: hidden;
          background: #e9f3ff;
        }

        .display-hero {
          min-height: 178px;
          grid-template-columns: minmax(560px, 1fr) minmax(360px, 500px) 230px;
          gap: 22px;
          padding: 22px 36px 0;
          align-items: end;
        }

        .display-hero-copy {
          gap: 12px;
          justify-content: center;
        }

        .display-hero-copy h1 {
          font-size: clamp(42px, 4.2vw, 70px);
          line-height: 1;
          letter-spacing: -0.045em;
        }

        .display-dday-card {
          width: 210px;
          height: 74px;
          border-radius: 10px 10px 0 0;
          font-size: 46px;
        }

        .display-hero-progress {
          min-height: 150px;
          grid-template-columns: 120px minmax(0, 1fr);
          gap: 10px;
          padding-bottom: 16px;
        }

        .display-overall-label {
          font-size: 16px;
        }

        .display-overall-gauge {
          width: 310px;
          height: 155px;
          min-width: 310px;
          min-height: 155px;
        }

        .display-overall-gauge strong {
          bottom: 16px;
          font-size: 52px;
        }

        .display-hero-brand {
          margin-top: 18px;
        }

        .display-hero-brand span {
          font-size: 16px;
        }

        .display-hero-brand strong {
          font-size: 23px;
        }

        .display-card-zone {
          padding: 24px 36px 28px;
          background:
            linear-gradient(180deg, #dcecff 0%, #eef6ff 70%, #e2f0ff 100%);
        }

        .display-project-grid {
          gap: 14px 24px;
        }

        .display-project-card {
          --accent: #0aaa9f;
          --accent-2: #237cff;
          min-height: 318px;
          height: 318px;
          display: flex;
          flex-direction: column;
          padding: 12px 15px 10px;
          border-radius: 9px;
          box-shadow: 0 16px 28px rgba(21, 72, 129, 0.11);
          overflow: hidden;
        }

        .display-project-card.field-smallbiz {
          --accent: #00aaa0;
          --accent-2: #19c8ba;
        }

        .display-project-card.field-burden {
          --accent: #8128ff;
          --accent-2: #b13cff;
        }

        .display-project-card.field-safety {
          --accent: #145cff;
          --accent-2: #2388ff;
        }

        .display-card-field {
          display: flex;
          align-items: center;
          gap: 5px;
          min-height: 15px;
          margin-bottom: 2px;
          color: var(--accent);
          font-size: 10px;
          font-weight: 950;
          line-height: 1;
          white-space: nowrap;
        }

        .display-card-field span {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--accent) 14%, #fff);
          border: 2px solid var(--accent);
          box-sizing: border-box;
        }

        .display-project-card h3 {
          min-height: 42px;
          max-height: 42px;
          margin: 0 0 2px;
          font-size: clamp(17px, 1.12vw, 21px);
          line-height: 1.16;
          letter-spacing: -0.045em;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .display-card-gauge {
          width: 116px;
          height: 58px;
          margin: 0 auto 1px;
        }

        .display-card-gauge::before {
          background:
            conic-gradient(
              from 270deg at 50% 100%,
              var(--accent) 0deg,
              var(--accent-2) var(--arc-deg),
              #e9f1fc var(--arc-deg),
              #e9f1fc 180deg,
              transparent 180deg
            );
        }

        .display-card-gauge::after {
          left: 18px;
          right: 18px;
          top: 18px;
        }

        .display-card-gauge-value span {
          color: #8c97aa;
          font-size: 9px;
          font-weight: 900;
        }

        .display-card-gauge-value strong {
          color: #101346;
          font-size: 29px;
          line-height: 0.96;
        }

        .display-card-metrics {
          display: grid;
          gap: 3px;
          margin-top: 1px;
        }

        .display-metric-row {
          display: block;
          min-height: 38px;
          padding: 3px 5px 4px;
          border-radius: 7px;
          background: #f8fbff;
          border: 1px solid #d8e8f6;
          box-shadow: 0 4px 12px rgba(18, 80, 145, 0.04);
        }

        .display-metric-row > strong {
          display: block;
          margin-bottom: 1px;
          color: var(--accent);
          font-size: 8.8px;
          font-weight: 950;
          line-height: 1.08;
          letter-spacing: -0.02em;
          word-break: keep-all;
        }

        .display-metric-values {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 3px;
        }

        .display-metric-values p {
          margin: 0;
          min-width: 0;
          padding: 2px 5px;
          border-radius: 5px;
          background: #eaf3ff;
        }

        .display-metric-values p:nth-child(2) {
          background: #e6fbf3;
        }

        .display-metric-values span,
        .display-metric-values b {
          display: block;
          text-align: left;
        }

        .display-metric-values span {
          color: #0b5eb2;
          font-size: 8px;
          font-weight: 950;
          line-height: 1;
        }

        .display-metric-values b {
          margin-top: 1px;
          color: #050d1b;
          font-size: 11px;
          font-weight: 950;
          line-height: 1.05;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .display-metric-values b.is-waiting {
          color: #1b2540;
          font-size: 8px;
          line-height: 1;
          letter-spacing: -0.03em;
        }

        .display-metric-row > em {
          display: block;
          width: fit-content;
          max-width: 100%;
          margin: 2px auto 1px;
          padding: 1px 8px;
          border-radius: 999px;
          background: #0b3d81;
          color: #fff;
          font-size: 8px;
          font-style: normal;
          font-weight: 950;
          line-height: 1;
          white-space: nowrap;
        }

        .display-metric-row > i {
          display: block;
          height: 5px;
          border-radius: 999px;
          background: #d7e4f2;
          overflow: hidden;
          box-shadow: 0 0 0 1px rgba(19, 68, 120, 0.08) inset;
        }

        .display-metric-row > i > b {
          display: block;
          width: max(calc(var(--metric-pct) * 1%), 0%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--accent), var(--accent-2));
          box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 44%, transparent);
        }

        .display-card-meta {
          display: grid;
          grid-template-columns: 1fr;
          gap: 1px;
          margin-top: 3px;
          padding: 4px 6px;
          border-radius: 8px;
          background: #f0f6fc;
        }

        .display-card-meta p {
          display: grid;
          grid-template-columns: 38px minmax(0, 1fr);
          gap: 4px;
          margin: 0;
          align-items: start;
          font-size: 9.4px;
          line-height: 1.1;
        }

        .display-card-meta span {
          color: #6a7890;
          font-weight: 900;
        }

        .display-card-meta b {
          color: #07142b;
          font-weight: 950;
          white-space: pre-line;
          overflow: hidden;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }

        .display-stage-track {
          position: relative;
          margin-top: auto;
          padding-top: 7px;
        }

        .display-stage-line {
          position: relative;
          height: 4px;
          border-radius: 999px;
          background: #d7e4f2;
          overflow: hidden;
        }

        .display-stage-line span {
          display: block;
          width: calc(var(--pct) * 1%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--accent), var(--accent-2));
        }

        .display-stage-labels {
          position: relative;
          display: grid;
          gap: 2px;
          margin-top: 2px;
        }

        .display-stage-point {
          position: relative;
          display: block;
          color: #43536b;
          font-size: 7.8px;
          font-weight: 900;
          line-height: 1.12;
          text-align: center;
          word-break: keep-all;
        }

        .display-stage-point::before {
          content: "";
          position: absolute;
          top: -9px;
          left: 50%;
          width: 6px;
          height: 6px;
          transform: translateX(-50%);
          border-radius: 50%;
          background: #fff;
          border: 2px solid #b8cbe0;
          box-sizing: border-box;
        }

        .display-stage-point.is-done,
        .display-stage-point.is-current {
          color: #0b5eb2;
        }

        .display-stage-point.is-done::before,
        .display-stage-point.is-current::before {
          border-color: var(--accent);
          background: var(--accent);
        }

        .display-board-page {
          min-width: 1500px;
          background: #e6f1ff;
        }

        .display-hero {
          min-height: 152px;
          grid-template-columns: minmax(560px, 1fr) minmax(320px, 420px) 250px;
          padding: 14px 48px 0;
        }

        .display-hero-copy h1 {
          font-size: clamp(36px, 3.25vw, 56px);
          line-height: 1.04;
          letter-spacing: -0.055em;
        }

        .display-dday-card {
          width: 176px;
          height: 56px;
          font-size: 36px;
        }

        .display-hero-progress {
          min-height: 128px;
          grid-template-columns: 104px minmax(0, 1fr);
          padding-bottom: 10px;
        }

        .display-overall-label {
          font-size: 14px;
        }

        .display-overall-gauge {
          width: 250px;
          height: 125px;
          min-width: 250px;
          min-height: 125px;
        }

        .display-overall-gauge strong {
          bottom: 12px;
          font-size: 42px;
        }

        .display-hero-brand {
          margin-top: 30px;
        }

        .display-card-zone {
          padding: 28px 48px 22px;
        }

        .display-project-grid {
          gap: 16px 24px;
        }

        .display-project-card {
          overflow: visible;
        }

        .display-project-card:hover {
          z-index: 80;
        }

        .display-card-detail-popover {
          position: fixed;
          z-index: 9999;
          left: 50%;
          top: 50%;
          width: min(1280px, 78vw);
          min-height: 52vh;
          max-height: 82vh;
          padding: 26px 30px 28px;
          overflow: auto;
          border: 1px solid #c9ddf1;
          border-radius: 20px;
          background: rgba(255, 255, 255, 0.98);
          box-shadow: 0 34px 90px rgba(7, 24, 54, 0.28);
          opacity: 0;
          pointer-events: none;
          transform: translate(-50%, -50%) scale(0.985);
          transition: opacity 150ms ease, transform 150ms ease;
        }

        .display-project-card:hover .display-card-detail-popover {
          opacity: 1;
          transform: translate(-50%, -50%) scale(1);
        }

        .display-detail-head {
          display: flex;
          align-items: center;
          gap: 14px;
          margin-bottom: 16px;
          padding-bottom: 14px;
          border-bottom: 1px solid #d7e4f2;
        }

        .display-detail-head > span {
          display: grid;
          width: 42px;
          height: 42px;
          place-items: center;
          border-radius: 14px;
          background: linear-gradient(135deg, var(--accent), var(--accent-2));
          color: #fff;
          font-size: 18px;
          font-weight: 950;
        }

        .display-detail-head b {
          display: block;
          color: #07142b;
          font-size: 27px;
          font-weight: 950;
          line-height: 1.18;
          letter-spacing: -0.04em;
        }

        .display-detail-head em {
          display: block;
          margin-top: 5px;
          color: var(--accent);
          font-size: 14px;
          font-style: normal;
          font-weight: 900;
        }

        .display-detail-badges {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 8px;
          margin-bottom: 14px;
        }

        .display-detail-badges span,
        .display-detail-summary p {
          margin: 0;
          padding: 10px 12px;
          border-radius: 12px;
          background: #eef6ff;
          color: #5b6b80;
          font-size: 12px;
          font-weight: 850;
        }

        .display-detail-badges b,
        .display-detail-summary strong {
          display: block;
          margin-top: 4px;
          color: #07142b;
          font-size: 16px;
          font-weight: 950;
          line-height: 1.2;
        }

        .display-detail-summary {
          display: grid;
          grid-template-columns: 0.7fr 0.7fr 1fr 1.2fr;
          gap: 8px;
          margin-bottom: 16px;
        }

        .display-detail-section {
          margin-top: 14px;
        }

        .display-detail-text-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 12px;
          margin-top: 14px;
        }

        .display-detail-text-grid .display-detail-section {
          margin-top: 0;
        }

        .display-detail-section h4 {
          margin: 0 0 8px;
          color: #07142b;
          font-size: 17px;
          font-weight: 950;
        }

        .display-detail-section > p {
          min-height: 50px;
          margin: 0;
          padding: 14px 16px;
          border-radius: 14px;
          background: #f3f7fb;
          color: #102033;
          font-size: 16px;
          font-weight: 800;
          line-height: 1.52;
          white-space: pre-wrap;
        }

        .display-detail-text-grid .display-detail-section > p {
          min-height: 110px;
          max-height: 180px;
          overflow: auto;
        }

        .display-detail-metrics {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
        }

        .display-detail-metric {
          padding: 12px;
          border: 1px solid #d6e7f7;
          border-radius: 14px;
          background: #f8fbff;
        }

        .display-detail-metric div {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 8px;
        }

        .display-detail-metric strong {
          color: var(--accent);
          font-size: 14px;
          font-weight: 950;
        }

        .display-detail-metric em {
          color: #7e8798;
          font-size: 12px;
          font-style: normal;
          font-weight: 800;
          white-space: nowrap;
        }

        .display-detail-metric p {
          display: grid;
          grid-template-columns: 52px minmax(0, 1fr);
          gap: 8px;
          margin: 4px 0 0;
          color: #6b7788;
          font-size: 12px;
          font-weight: 850;
        }

        .display-detail-metric b {
          color: #07142b;
          font-size: 14px;
          font-weight: 950;
        }

        .display-detail-metric b.is-waiting {
          color: #c23a32;
        }

        .display-project-card {
          height: 374px;
          min-height: 374px;
          padding: 16px 18px 13px;
          border-radius: 10px;
          box-shadow: 0 18px 34px rgba(27, 81, 143, 0.16);
        }

        .display-card-field {
          margin-bottom: 4px;
          font-size: 10px;
        }

        .display-card-field span {
          width: 13px;
          height: 13px;
          border-radius: 3px;
          background: transparent;
        }

        .display-project-card h3 {
          min-height: 52px;
          max-height: 52px;
          margin-bottom: 4px;
          color: #09083b;
          font-size: clamp(20px, 1.28vw, 25px);
          line-height: 1.18;
          letter-spacing: -0.06em;
        }

        .display-card-gauge {
          width: 168px;
          height: 84px;
          margin: 2px auto 6px;
        }

        .display-card-gauge::after {
          left: 24px;
          right: 24px;
          top: 24px;
        }

        .display-card-gauge-value {
          bottom: -2px;
        }

        .display-card-gauge-value span {
          font-size: 10px;
          color: #8b92a2;
        }

        .display-card-gauge-value strong {
          color: #120a58;
          font-size: 38px;
          line-height: 0.9;
        }

        .display-card-metrics {
          gap: 5px;
          margin-top: 0;
          margin-bottom: 10px;
        }

        .display-metric-row {
          min-height: 44px;
          padding: 0;
          border: 0;
          border-radius: 0;
          background: transparent;
          box-shadow: none;
        }

        .display-metric-title {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 8px;
          min-height: 16px;
          margin-bottom: 2px;
        }

        .display-metric-title strong {
          color: var(--accent);
          font-size: 10px;
          font-weight: 950;
          line-height: 1.1;
          letter-spacing: -0.04em;
          word-break: keep-all;
        }

        .display-metric-title em {
          color: #8a93a4;
          font-size: 8px;
          font-style: normal;
          font-weight: 850;
          white-space: nowrap;
        }

        .display-metric-values {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 1px minmax(76px, auto);
          gap: 8px;
          align-items: end;
        }

        .display-metric-values p,
        .display-metric-values p:nth-child(2) {
          min-width: 0;
          margin: 0;
          padding: 0;
          border-radius: 0;
          background: transparent;
        }

        .display-metric-values > i {
          width: 1px;
          height: 18px;
          background: #cfdbea;
        }

        .display-metric-values span {
          color: #7e8798;
          font-size: 8px;
          font-weight: 850;
          line-height: 1;
        }

        .display-metric-values b {
          margin-top: 2px;
          color: #09083b;
          font-size: 13px;
          font-weight: 950;
          line-height: 1;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .display-metric-values p:last-child b {
          color: #09083b;
          font-size: 18px;
          letter-spacing: -0.06em;
          text-align: right;
        }

        .display-metric-values b.is-waiting {
          color: #09083b;
          font-size: 13px;
          line-height: 1;
          letter-spacing: -0.04em;
        }

        .display-card-progress-panel {
          margin-top: auto;
          padding: 5px 7px 4px;
          border: 1px solid #d6e7f7;
          border-radius: 9px;
          background:
            linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(231, 243, 255, 0.92)),
            color-mix(in srgb, var(--accent) 8%, #edf7ff);
          box-shadow:
            0 6px 16px rgba(28, 81, 140, 0.08),
            inset 0 1px 0 rgba(255, 255, 255, 0.9);
        }

        .display-card-foot {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 44px;
          gap: 7px;
          align-items: center;
          margin-top: 0;
          padding-top: 0;
          border-top: 0;
        }

        .display-card-meta {
          display: grid;
          gap: 3px;
          margin: 0;
          padding: 0;
          border-radius: 0;
          background: transparent;
        }

        .display-card-meta p {
          grid-template-columns: 48px minmax(0, 1fr);
          gap: 5px;
          font-size: 8.8px;
          line-height: 1.12;
        }

        .display-card-meta span {
          color: #34577e;
          font-weight: 950;
          white-space: nowrap;
        }

        .display-card-meta b {
          color: #061b3b;
          font-weight: 950;
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          -webkit-line-clamp: unset;
        }

        .display-card-mini-gauge {
          position: relative;
          width: 44px;
          height: 44px;
          border-radius: 50%;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 1px;
          text-align: center;
          background:
            conic-gradient(var(--accent) 0deg, var(--accent-2) calc(var(--pct) * 3.6deg), #eaf1fb calc(var(--pct) * 3.6deg), #eaf1fb 360deg);
        }

        .display-card-mini-gauge::after {
          content: "";
          position: absolute;
          inset: 6px;
          border-radius: 50%;
          background: #fff;
        }

        .display-card-mini-gauge span,
        .display-card-mini-gauge strong {
          position: relative;
          z-index: 1;
          display: block;
          text-align: center;
        }

        .display-card-mini-gauge span {
          color: #7d8798;
          font-size: 7px;
          font-weight: 900;
          line-height: 1;
        }

        .display-card-mini-gauge strong {
          margin-top: 0;
          color: #120a58;
          font-size: 15px;
          font-weight: 950;
          line-height: 0.98;
        }

        .display-stage-track {
          margin-top: 4px;
          padding-top: 7px;
        }

        .display-stage-line {
          height: 4px;
          overflow: visible;
        }

        .display-stage-labels {
          margin-top: 4px;
        }

        .display-stage-point {
          color: #263953;
          font-size: 7.8px;
          line-height: 1.12;
        }

        .display-stage-point::before {
          top: -12px;
          width: 8px;
          height: 8px;
        }

        .display-stage-point.is-done {
          color: var(--accent);
        }

        .display-stage-point.is-current {
          color: #003f9e;
          font-weight: 950;
        }

        .display-stage-point.is-done::before {
          width: 9px;
          height: 9px;
          border-color: var(--accent);
          background: var(--accent);
          box-shadow: 0 0 0 3px rgba(37, 195, 189, 0.16);
        }

        .display-stage-point.is-current::before {
          width: 11px;
          height: 11px;
          border-color: #fff;
          background: linear-gradient(135deg, var(--accent), var(--accent-2));
          box-shadow: 0 0 0 4px rgba(0, 112, 210, 0.18);
        }

        .display-stage-point.is-current::after {
          content: "";
          position: absolute;
          left: 50%;
          top: -21px;
          width: 0;
          height: 0;
          transform: translateX(-50%);
          border-left: 5px solid transparent;
          border-right: 5px solid transparent;
          border-top: 7px solid var(--accent-2);
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

          .economy-carousel {
            padding: 0 16px;
            margin: 18px auto 22px;
          }

          .eco-carousel-stage {
            height: 248px;
            border-radius: 16px;
          }

          .eco-carousel-slide {
            grid-template-columns: minmax(0, 1fr);
            padding: 24px 52px;
          }

          .eco-carousel-card.side {
            display: none;
          }

          .eco-carousel-card.center {
            min-height: 196px;
            padding: 24px 20px;
          }

          .eco-carousel-card.center h3 {
            min-height: 42px;
            font-size: 25px;
          }

          .eco-carousel-card.center .eco-carousel-value strong {
            font-size: 44px;
          }

          .eco-carousel-value em {
            font-size: 14px;
          }

          .eco-carousel-card.center .eco-carousel-period {
            min-height: 30px;
            font-size: 16px;
          }

          .eco-carousel-count {
            right: 18px;
            bottom: 14px;
            font-size: 14px;
          }

          .eco-carousel-arrow {
            width: 30px;
            height: 30px;
          }

          .eco-carousel-arrow.left {
            left: 18px;
          }

          .eco-carousel-arrow.right {
            right: 18px;
          }

          .project-board {
            padding: 0 16px 28px;
            overflow-x: auto;
          }

          .project-board-head {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
            padding-top: 18px;
            text-align: center;
          }

          .project-head-spacer {
            display: none;
          }

          .project-board-spacer {
            display: none;
          }

          .project-board-head h2 {
            font-size: 28px;
            white-space: normal;
          }

          .project-title-art {
            min-height: 72px;
            padding: 0 6px;
            transform: scale(0.9);
            transform-origin: center;
          }

          .project-title-art::before {
            width: 104%;
            height: 52px;
          }

          .project-title-art strong {
            font-size: 30px;
          }

          .project-head-actions {
            justify-content: center;
            flex-wrap: wrap;
          }

          .project-overall-progress {
            width: 132px;
            height: 132px;
            min-width: 132px;
          }

          .project-overall-progress span {
            font-size: 15px;
          }

          .project-overall-progress strong {
            font-size: 31px;
          }

          .project-overall-progress em {
            font-size: 13px;
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

          .project-compact-grid {
            grid-template-columns: repeat(2, minmax(260px, 1fr));
            gap: 10px;
          }

          .project-board.compact {
            width: auto;
            max-width: none;
            margin: 0;
            padding: 0 16px 28px;
            overflow-x: auto;
          }

          .project-board.compact .project-board-head {
            display: grid;
            min-height: 0;
            padding: 18px 0 10px;
          }

          .project-board.compact .project-head-actions {
            position: static;
            justify-content: center;
          }

          .project-compact-card {
            min-height: 210px;
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
ensure_admin_schema()

catalog_df = load_catalog()
observations_df = load_observations()
credit_df, policy_df = load_manual_tables()
import_runs_df = load_import_runs()
countdown_label, countdown_status = minsaeng_countdown()
current_view = active_view()

if current_view not in {"check", "check_display"}:
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
              <a class="{nav_class('check_display', current_view, 'nav-item nav-check')}" href="?view=check_display" aria-current="{str(current_view == 'check_display').lower()}">민생100일 비상대책 추진상황</a>
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
elif current_view == "check_display":
    render_project_display_board(EMERGENCY_PROJECTS)
elif current_view == "admin":
    render_admin_dashboard(EMERGENCY_PROJECTS)
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
    render_metric_carousel(all_cards, interval_seconds=10)
    render_card_grid(all_cards, columns=3)
